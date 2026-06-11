import asyncio
import re
import unicodedata
import pandas as pd
import httpx
from bs4 import BeautifulSoup
import time

# Canton ID to Abbreviation mapping
CANTON_ABBR = {
    1: 'zh', 2: 'be', 3: 'lu', 4: 'ur', 5: 'sz', 6: 'ow', 7: 'nw', 8: 'gl', 9: 'zg',
    10: 'fr', 11: 'so', 12: 'bs', 13: 'bl', 14: 'sh', 15: 'ar', 16: 'ai', 17: 'sg',
    18: 'gr', 19: 'ag', 20: 'tg', 21: 'ti', 22: 'vd', 23: 'vs', 24: 'ne', 25: 'ge', 26: 'ju'
}

MANUAL_OVERRIDES = {
    6011: ["gondo.ch", "zwischbergen.ch"],  # Zwischbergen
    3203: ["stadt.sg.ch"],                 # St. Gallen
}

def remove_accents_and_umlauts(text):
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def german_umlauts_to_ae_oe_ue(text):
    text = text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
    text = text.replace('Ä', 'ae').replace('Ö', 'oe').replace('Ü', 'ue')
    return text

def generate_name_variations(name_str):
    name_str = name_str.lower().strip()
    
    # Remove parenthesized parts
    clean_name = re.sub(r'\s*\([^)]*\)', '', name_str).strip()
    
    variations = set()
    variations.add(clean_name)
    
    # Direct replacement variations:
    # 1. Replace spaces with hyphens
    variations.add(clean_name.replace(' ', '-'))
    # 2. Replace spaces with empty string
    variations.add(clean_name.replace(' ', ''))
    # 3. Replace hyphens with empty string, spaces with hyphens
    variations.add(clean_name.replace('-', '').replace(' ', '-'))
    
    # Build list of apostrophe variations
    apo_variants = [clean_name]
    if "'" in clean_name:
        apo_variants.append(clean_name.replace("'", ""))
        apo_variants.append(clean_name.replace("'", "-"))
        # Strip article prefixes like l', d', c', m', s'
        stripped_apo = re.sub(r"\b(l|d|c|m|s)'", "", clean_name)
        apo_variants.append(stripped_apo)
        
    for av in apo_variants:
        av = av.strip()
        if not av:
            continue
            
        variations.add(av)
        
        # Split by spaces, hyphens, slashes
        parts = re.split(r'[\s\-\/]+', av)
        parts = [p.replace('.', '').replace('"', '').strip() for p in parts if p.strip()]
        
        if len(parts) > 1:
            variations.add("-".join(parts))
            variations.add("".join(parts))
            
            # First two parts (e.g. "La Punt Chamues-ch" -> "la-punt", "lapunt")
            if len(parts) >= 2:
                variations.add("-".join(parts[:2]))
                variations.add("".join(parts[:2]))
            
            # Avoid adding generic words as single-word candidates
            generic_single_words = {
                'saint', 'sainte', 'st', 'ste', 'san', 'santa', 'santo',
                'castel', 'chateau', 'le', 'la', 'les', 'de', 'du', 'en',
                'am', 'im', 'bei', 'an', 'der', 'ob', 'nid', 'unter', 'ober'
            }
            if parts[0] not in generic_single_words and len(parts[0]) > 2:
                variations.add(parts[0])
            if parts[-1] not in generic_single_words and len(parts[-1]) > 2:
                variations.add(parts[-1])
            
            # French articles
            if parts[0] in ['le', 'la', 'les', 'de', 'du', 'en']:
                variations.add("-".join(parts[1:]))
                variations.add("".join(parts[1:]))
                
            # Abbreviate Saint / Sainte -> st / ste
            if parts[0] in ['saint', 'sainte']:
                st_part = 'st' if parts[0] == 'saint' else 'ste'
                variations.add("-".join([st_part] + parts[1:]))
                variations.add("".join([st_part] + parts[1:]))
                
            # German articles/prepositions
            if 'am' in parts:
                idx = parts.index('am')
                short_parts = parts[:idx] + parts[idx+1:]
                variations.add("-".join(short_parts))
            if 'im' in parts:
                idx = parts.index('im')
                short_parts = parts[:idx] + parts[idx+1:]
                variations.add("-".join(short_parts))
            if 'bei' in parts:
                idx = parts.index('bei')
                short_parts = parts[:idx] + parts[idx+1:]
                variations.add("-".join(short_parts))
                
            # Abbreviations for Italian/German terms
            for i, p in enumerate(parts):
                if p == 'inferiore':
                    parts_copy = parts.copy()
                    parts_copy[i] = 'inf'
                    variations.add("-".join(parts_copy))
                    variations.add("".join(parts_copy))
                elif p == 'superiore':
                    parts_copy = parts.copy()
                    parts_copy[i] = 'sup'
                    variations.add("-".join(parts_copy))
                    variations.add("".join(parts_copy))
                elif p == 'ober':
                    parts_copy = parts.copy()
                    parts_copy[i] = 'ob'
                    variations.add("-".join(parts_copy))
                    variations.add("".join(parts_copy))
                elif p == 'unter':
                    parts_copy = parts.copy()
                    parts_copy[i] = 'unt'
                    variations.add("-".join(parts_copy))
                    variations.add("".join(parts_copy))
        else:
            variations.add(parts[0])
            
    return list(variations)

def get_punycode(domain_label):
    try:
        return domain_label.encode('idna').decode('ascii')
    except Exception:
        return domain_label

def generate_candidates(row):
    id_gde = row['id_gde']
    if id_gde in MANUAL_OVERRIDES:
        return MANUAL_OVERRIDES[id_gde]
        
    gde_name = row['name_gde']
    canton_id = row.get('id_kant', 1)
    canton_abbr = CANTON_ABBR.get(canton_id, '')
    canton_name_de = row.get('name_kant_de', '').lower()
    
    paren_match = re.search(r'\(([^)]+)\)', gde_name)
    paren_abbr = paren_match.group(1).lower() if paren_match else ''
    
    # Generate base variations
    variations = generate_name_variations(gde_name)
    
    candidates = set()
    
    for var in variations:
        var_forms = set()
        var_forms.add(var)
        var_forms.add(german_umlauts_to_ae_oe_ue(var))
        var_forms.add(remove_accents_and_umlauts(var))
        
        for vf in var_forms:
            if not vf:
                continue
            
            # Base domain
            candidates.add(f"{vf}.ch")
            
            # Prefixes
            candidates.add(f"gemeinde-{vf}.ch")
            candidates.add(f"gemeinde{vf}.ch")
            candidates.add(f"commune-{vf}.ch")
            candidates.add(f"commune{vf}.ch")
            candidates.add(f"comune-{vf}.ch")
            candidates.add(f"comune{vf}.ch")
            
            # Canton abbreviations
            for abbr in filter(None, [canton_abbr, paren_abbr]):
                candidates.add(f"{vf}-{abbr}.ch")
                candidates.add(f"{vf}{abbr}.ch")
                candidates.add(f"gemeinde-{vf}-{abbr}.ch")
                candidates.add(f"gemeinde{vf}{abbr}.ch")
                candidates.add(f"commune-{vf}-{abbr}.ch")
                candidates.add(f"comune-{vf}-{abbr}.ch")
                
            # Canton name
            if canton_name_de:
                norm_canton = remove_accents_and_umlauts(german_umlauts_to_ae_oe_ue(canton_name_de))
                candidates.add(f"{vf}-{norm_canton}.ch")
                candidates.add(f"{vf}{norm_canton}.ch")
                
    # Handle Punycode for any non-ascii candidate
    final_candidates = set()
    for cand in candidates:
        if not all(ord(c) < 128 for c in cand):
            parts = cand.split('.')
            encoded_parts = [get_punycode(p) for p in parts]
            final_candidates.add(".".join(encoded_parts))
        else:
            final_candidates.add(cand)
            
    return list(final_candidates)

def extract_base_domain(url_or_domain):
    # E.g. https://www.wila.ch/index.php -> wila.ch
    # E.g. http://uster.ch -> uster.ch
    url_or_domain = url_or_domain.lower().strip()
    if '://' in url_or_domain:
        # Extract host
        host = url_or_domain.split('://')[1].split('/')[0]
    else:
        host = url_or_domain.split('/')[0]
        
    # Strip port if any
    host = host.split(':')[0]
    
    parts = host.split('.')
    if len(parts) >= 2:
        return parts[-2] + '.' + parts[-1]
    return host

async def fetch_domain(client, domain, semaphore):
    async with semaphore:
        result = {
            "requested_domain": domain,
            "success": False,
            "status_code": None,
            "final_url": None,
            "final_domain": None,
            "title": "",
            "meta_description": "",
            "html_snippet": "",
            "error": None
        }
        
        # Try apex domain first (HTTP and HTTPS)
        urls_to_try = [
            f"http://{domain}",
            f"https://{domain}"
        ]
        # If it doesn't already start with www., try www. fallback (HTTP and HTTPS)
        if not domain.startswith("www."):
            urls_to_try.append(f"http://www.{domain}")
            urls_to_try.append(f"https://www.{domain}")
            
        for url in urls_to_try:
            try:
                response = await client.get(url, follow_redirects=True, timeout=5.0)
                result["success"] = response.status_code == 200
                result["status_code"] = response.status_code
                result["final_url"] = str(response.url)
                result["final_domain"] = extract_base_domain(str(response.url))
                
                if response.status_code == 200:
                    html = response.text[:100000] # Read first 100KB to save memory/time
                    result["html_snippet"] = html.lower()
                    
                    try:
                        soup = BeautifulSoup(html, 'html.parser')
                        if soup.title and soup.title.string:
                            result["title"] = soup.title.string.strip()
                        desc_tag = soup.find('meta', attrs={'name': 'description'})
                        if desc_tag and desc_tag.get('content'):
                            result["meta_description"] = desc_tag.get('content').strip()
                    except Exception:
                        pass
                    # If we succeeded, break out of loop
                    break
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.LocalProtocolError,
                    httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError,
                    httpx.WriteTimeout, httpx.WriteError) as net_err:
                result["error"] = type(net_err).__name__
                # Continue loop to try next URL
                continue
            except httpx.HTTPError as http_err:
                result["error"] = type(http_err).__name__
                break
            except Exception as err:
                result["error"] = type(err).__name__
                break
                
        return result

def evaluate_domain_score(result, row):
    # Evaluate how well this domain matches the target Gemeinde
    gde_name = row['name_gde'].lower()
    canton_abbr = CANTON_ABBR.get(row.get('id_kant', 1), '').lower()
    
    # Strip parenthesis for comparison
    clean_gde_name = re.sub(r'\s*\([^)]*\)', '', gde_name).strip()
    
    score = 0
    
    if not result["success"]:
        return -100
        
    title = result["title"].lower()
    desc = result["meta_description"].lower()
    html = result["html_snippet"]
    final_domain = result["final_domain"] or result["requested_domain"]
    
    # Check for negative/parked domain patterns (only in title and description, and specific phrases in html)
    title_desc = title + " " + desc
    parked_title_keywords = [
        "domain is for sale", "domain kaufen", "buy this domain", "sedo",
        "domain parking", "under construction", "im aufbau", "en construction",
        "suchportal", "platzhalter", "vorbereitung", "coming soon"
    ]
    parked_html_keywords = [
        "hier entsteht eine neue internetpräsenz",
        "hier entsteht eine neue homepage",
        "diese domain wurde erfolgreich registriert",
        "domain is registered",
        "domain successfully registered",
        "parking.hostpoint.ch",
        "sedoparking.com",
    ]
    
    is_parked = any(k in title_desc for k in parked_title_keywords) or any(k in html for k in parked_html_keywords)
    if is_parked:
        score -= 50
        
    # Check if the exact municipality name is in the title
    if clean_gde_name in title:
        score += 20
    elif any(part in title for part in re.split(r'[\s\-\/]+', clean_gde_name) if len(part) > 3):
        score += 10
        
    # Check if the exact municipality name is in the description or page text
    if clean_gde_name in desc:
        score += 15
    if clean_gde_name in html:
        score += 15
        
    # Swiss specific official website keywords
    official_keywords_de = ["gemeinde", "einwohnergemeinde", "gemeindeverwaltung", "stadt", "gemeindehaus", "verwaltung"]
    official_keywords_fr = ["commune", "administration communale", "site officiel", "ville"]
    official_keywords_it = ["comune", "amministrazione comunale", "municipio"]
    
    all_official_keywords = official_keywords_de + official_keywords_fr + official_keywords_it
    
    # Award points if official terms are present in title, description or content
    if any(k in title for k in all_official_keywords):
        score += 15
    if any(k in desc for k in all_official_keywords):
        score += 10
    if any(k in html for k in all_official_keywords):
        score += 10
        
    # Canton code matches
    if canton_abbr in title or canton_abbr in desc or f"kanton {canton_abbr}" in html or f"ct. {canton_abbr}" in html:
        score += 5
        
    # Preference for domain names that match clean name directly
    clean_domain_base = remove_accents_and_umlauts(german_umlauts_to_ae_oe_ue(clean_gde_name)).replace("-", "").replace(" ", "")
    clean_final_domain = final_domain.replace(".ch", "").replace("-", "")
    
    if clean_domain_base == clean_final_domain:
        score += 15
    elif clean_domain_base in clean_final_domain:
        score += 8
        
    # Short domains are preferred
    score += max(0, 10 - len(final_domain))
    
    return score

async def main():
    print("Step 1: Loading domain list...")
    domains_file = 'domains_2026-06-05.txt'
    registered_domains = set()
    
    with open(domains_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip().lower()
            if not line:
                continue
            parts = line.split('.')
            if len(parts) >= 2:
                base_domain = parts[-2] + '.' + parts[-1]
                registered_domains.add(base_domain)
                
    print(f"Loaded {len(registered_domains)} unique registered .ch domains.")
    
    print("Step 2: Loading Gemeinden CSV...")
    df = pd.read_csv('ma-d-00.07.01.01-002.csv')
    print(f"Loaded {len(df)} Gemeinden.")
    
    print("Step 3: Generating domain candidates...")
    gde_candidates = {}
    all_candidate_domains = set()
    
    for idx, row in df.iterrows():
        id_gde = row['id_gde']
        candidates = generate_candidates(row)
        # If it's in MANUAL_OVERRIDES, we keep the candidate without checking registered_domains
        if id_gde in MANUAL_OVERRIDES:
            existing_cands = candidates
        else:
            existing_cands = [c for c in candidates if c in registered_domains]
        gde_candidates[id_gde] = existing_cands
        all_candidate_domains.update(existing_cands)
        
    print(f"Generated {len(all_candidate_domains)} unique candidate domains to fetch.")
    
    # Calculate how many Gemeinden have candidates
    matched_count = sum(1 for cands in gde_candidates.values() if len(cands) > 0)
    print(f"Gemeinden with at least 1 candidate: {matched_count} / {len(df)} ({matched_count/len(df)*100:.2f}%)")
    
    print("Step 4: Fetching domain contents in parallel...")
    semaphore = asyncio.Semaphore(100) # Max 100 concurrent requests
    
    # Use headers to look like a standard browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    
    start_time = time.time()
    
    async with httpx.AsyncClient(headers=headers, verify=False) as client:
        tasks = []
        for domain in sorted(all_candidate_domains):
            tasks.append(fetch_domain(client, domain, semaphore))
            
        print(f"Starting async fetch of {len(tasks)} domains...")
        
        # We process them and print progress updates
        fetched_results = {}
        completed = 0
        for task in asyncio.as_completed(tasks):
            res = await task
            fetched_results[res["requested_domain"]] = res
            completed += 1
            if completed % 100 == 0 or completed == len(tasks):
                print(f"  Progress: {completed}/{len(tasks)} domains fetched ({completed/len(tasks)*100:.1f}%)")
                
    elapsed = time.time() - start_time
    print(f"Finished fetching in {elapsed:.2f} seconds.")
    
    # Add manual overrides final domains to fetched_results if not present, to ensure they have an entry
    for gid, override_cands in MANUAL_OVERRIDES.items():
        for cand in override_cands:
            if cand not in fetched_results:
                fetched_results[cand] = {
                    "requested_domain": cand,
                    "success": True,
                    "status_code": 200,
                    "final_url": f"https://{cand}/",
                    "final_domain": cand,
                    "title": "manual override",
                    "meta_description": "",
                    "html_snippet": "gemeinde",
                    "error": None
                }
                
    print("Step 5: Selecting the official domain for each Gemeinde...")
    final_domains = []
    selection_reasons = []
    
    for idx, row in df.iterrows():
        id_gde = row['id_gde']
        candidates = gde_candidates.get(id_gde, [])
        
        if not candidates:
            final_domains.append(None)
            selection_reasons.append("no candidates generated")
            continue
            
        # Group candidates by final base domain if they redirect
        # E.g. if gemeinde-wila.ch redirects to wila.ch, we evaluate wila.ch
        evaluated_domains = {}
        
        for cand in candidates:
            res = fetched_results.get(cand)
            if not res or not res["success"]:
                continue
                
            # Use the final resolved domain as the target
            target_domain = res["final_domain"] or res["requested_domain"]
            
            # Get the fetch response for the target domain (if we crawled it directly)
            target_res = fetched_results.get(target_domain, res)
            
            score = evaluate_domain_score(target_res, row)
            
            # If the candidate domain redirected to the target domain, give it a tiny bonus
            if target_domain != cand:
                score += 2
                
            if target_domain not in evaluated_domains or score > evaluated_domains[target_domain]["score"]:
                evaluated_domains[target_domain] = {
                    "score": score,
                    "cand": cand,
                    "res": target_res
                }
                
        if not evaluated_domains:
            # Fallback to the first candidate that exists (even if it failed to fetch)
            # or mark as None
            final_domains.append(None)
            selection_reasons.append("all candidates failed to respond")
            continue
            
        # Select highest scoring domain
        best_domain = None
        best_score = -999
        best_cand = None
        
        for dom, info in evaluated_domains.items():
            if info["score"] > best_score:
                best_score = info["score"]
                best_domain = dom
                best_cand = info["cand"]
                
        # If the highest score is too low, we might not trust it
        # Min score threshold: 15 points
        if best_score < 10:
            final_domains.append(None)
            selection_reasons.append(f"highest score too low ({best_score}) for {best_domain}")
        else:
            final_domains.append(best_domain)
            selection_reasons.append(f"selected {best_domain} with score {best_score} via {best_cand}")
            
    df['official_domain'] = final_domains
    df['selection_reason'] = selection_reasons
    
    # Save output
    output_df = df[['id_gde', 'name_gde', 'id_kant', 'name_kant_de', 'official_domain', 'selection_reason']]
    output_df.to_csv('gemeinden_domains.csv', index=False)
    
    found_count = df['official_domain'].notna().sum()
    print(f"\nFinal Statistics:")
    print(f"  Total Gemeinden: {len(df)}")
    print(f"  Official Domains Found: {found_count} / {len(df)} ({found_count/len(df)*100:.2f}%)")
    print(f"  Missing Domains: {len(df) - found_count}")
    print(f"Saved results to 'gemeinden_domains.csv'.")

if __name__ == '__main__':
    asyncio.run(main())
