import asyncio
import re
import urllib.parse
import json
import pandas as pd
import httpx
from bs4 import BeautifulSoup
import time

# Date regex patterns
JUNE_2026_PATS = [
    re.compile(r'14\s*\.\s*(juni|0?6|6)\s*\.?\s*2026', re.IGNORECASE),
    re.compile(r'14\s+juin\s+2026', re.IGNORECASE),
    re.compile(r'14\s+giugno\s+2026', re.IGNORECASE),
    re.compile(r'14\.0?6\.2026', re.IGNORECASE),
    re.compile(r'2026-06-14', re.IGNORECASE)
]

JULY_2026_PATS = [
    re.compile(r'14\s*\.\s*(juli|0?7|7)\s*\.?\s*2026', re.IGNORECASE),
    re.compile(r'14\s+juillet\s+2026', re.IGNORECASE),
    re.compile(r'14\s+luglio\s+2026', re.IGNORECASE),
    re.compile(r'14\.0?7\.2026', re.IGNORECASE),
    re.compile(r'2026-07-14', re.IGNORECASE)
]

MARCH_2026_PATS = [
    re.compile(r'8\s*\.\s*(m[äa]rz|0?3|3)\s*\.?\s*2026', re.IGNORECASE),
    re.compile(r'8\s+mars\s+2026', re.IGNORECASE),
    re.compile(r'8\s+marzo\s+2026', re.IGNORECASE),
    re.compile(r'0?8\.0?3\.2026', re.IGNORECASE),
    re.compile(r'2026-03-08', re.IGNORECASE),
    re.compile(r'bargeld', re.IGNORECASE),
    re.compile(r'argent\s+liquide', re.IGNORECASE),
    re.compile(r'denaro\s+contante', re.IGNORECASE)
]

VOTE_KEYWORDS = re.compile(
    r"abstimmung|abstimmungen|wahlen|urnengang|urnengaenge|votation|votations|election|elections|votazione|votazioni|elezione|elezioni|albo|pilier",
    re.IGNORECASE
)

def score_voting_link(text, href):
    text = text.lower().strip()
    href = href.lower().strip()
    
    score = 0
    # Keywords in text
    if "abstimmung" in text or "abstimmungen" in text:
        score += 30
    if "wahlen" in text or "wahl" in text:
        score += 20
    if "votation" in text or "votations" in text:
        score += 30
    if "election" in text or "elections" in text:
        score += 20
    if "votazioni" in text or "votazione" in text:
        score += 30
    if "elezioni" in text or "elezione" in text:
        score += 20
    if "urnengang" in text or "urnengaenge" in text:
        score += 15
    if "albo" in text or "albo comunale" in text or "albo pretorio" in text:
        score += 25
    if "pilier" in text or "pilier public" in text:
        score += 25
        
    # Keywords in href
    if "abstimmung" in href:
        score += 25
    if "votation" in href:
        score += 25
    if "votazioni" in href:
        score += 25
    if "wahlen" in href or "wahl" in href:
        score += 15
    if "election" in href or "elections" in href:
        score += 15
    if "albo" in href:
        score += 20
    if "pilier" in href:
        score += 20
        
    # Demerits for unrelated or secondary pages
    if "reglement" in href or "reglement" in text:
        score -= 25
    if "protokoll" in href or "protokoll" in text:
        score -= 15
    if "archiv" in href or "archiv" in text:
        score -= 5  # prefer current page over archive
    if "suche" in href or "suche" in text:
        score -= 10
        
    return score

def extract_base_domain(url_or_domain):
    url_or_domain = url_or_domain.lower().strip()
    if '://' in url_or_domain:
        host = url_or_domain.split('://')[1].split('/')[0]
    else:
        host = url_or_domain.split('/')[0]
    host = host.split(':')[0]
    parts = host.split('.')
    if len(parts) >= 2:
        return parts[-2] + '.' + parts[-1]
    return host

async def find_landing_page(client, domain):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # Try HTTPS and HTTP
    urls_to_try = [f"https://www.{domain}", f"http://www.{domain}", f"https://{domain}"]
    
    resp = None
    for url in urls_to_try:
        try:
            resp = await client.get(url, follow_redirects=True, timeout=8.0)
            if resp.status_code == 200:
                break
        except Exception:
            continue
            
    if not resp or resp.status_code != 200:
        return None, "homepage connection failed"
        
    homepage_url = str(resp.url)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Extract all links and score them
    candidates = []
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        text = a_tag.get_text().strip()
        
        if not href or href.startswith('#') or href.startswith('javascript:'):
            continue
            
        score = score_voting_link(text, href)
        if score > 15: # minimum threshold for voting page link
            abs_url = urllib.parse.urljoin(homepage_url, href)
            candidates.append({"url": abs_url, "score": score})
            
    if candidates:
        # Sort by score descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[0]["url"], "found on homepage"
        
    # Fallback to common paths
    fallback_paths = ["/abstimmungen", "/votations", "/votazioni", "/abstimmungen-wahlen", "/politik/abstimmungen"]
    for path in fallback_paths:
        test_url = urllib.parse.urljoin(homepage_url, path)
        try:
            test_resp = await client.get(test_url, follow_redirects=True, timeout=5.0)
            if test_resp.status_code == 200:
                return str(test_resp.url), "fallback path worked"
        except Exception:
            continue
            
    return None, "no voting links found"

def check_string_for_patterns(text, patterns):
    return any(pat.search(text) for pat in patterns)

def parse_html_for_vote_pages(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    
    june_links = []
    july_links = []
    march_links = []
    
    # 1. Parse data-entities attributes (JSON lists inside HTML)
    for element in soup.find_all(attrs={"data-entities": True}):
        try:
            data = json.loads(element["data-entities"])
            for item in data.get("data", []):
                # Extract text/name and date fields
                name_html = item.get("name", "")
                datum_von = item.get("datumVon", "")
                datum_sort = item.get("datumVon-sort", "")
                
                # Check date fields
                is_june = check_string_for_patterns(datum_von + " " + datum_sort, JUNE_2026_PATS)
                is_july = check_string_for_patterns(datum_von + " " + datum_sort, JULY_2026_PATS)
                is_march = check_string_for_patterns(datum_von + " " + datum_sort, MARCH_2026_PATS)
                
                if is_june or is_july or is_march:
                    # Extract href from the name html
                    name_soup = BeautifulSoup(name_html, 'html.parser')
                    a_tag = name_soup.find('a', href=True)
                    if a_tag:
                        abs_url = urllib.parse.urljoin(base_url, a_tag['href'])
                        if is_june:
                            june_links.append(abs_url)
                        if is_july:
                            july_links.append(abs_url)
                        if is_march:
                            march_links.append(abs_url)
        except Exception:
            pass
            
    # 2. Check standard rows (tr, div, li, p) for date + link combo
    for row in soup.find_all(['tr', 'div', 'li', 'p']):
        row_text = row.get_text()
        
        # Check if this row mentions any of the dates
        is_june = check_string_for_patterns(row_text, JUNE_2026_PATS)
        is_july = check_string_for_patterns(row_text, JULY_2026_PATS)
        is_march = check_string_for_patterns(row_text, MARCH_2026_PATS)
        
        if is_june or is_july or is_march:
            a_tags = row.find_all('a', href=True)
            # Only consider rows/elements that are small and have up to 3 links
            if 0 < len(a_tags) <= 3:
                for a_tag in a_tags:
                    href = a_tag['href'].strip()
                    if not href or href.startswith('#') or href.startswith('javascript:'):
                        continue
                    abs_url = urllib.parse.urljoin(base_url, href)
                    if is_june:
                        june_links.append(abs_url)
                    if is_july:
                        july_links.append(abs_url)
                    if is_march:
                        march_links.append(abs_url)

    # 3. Check individual anchor links (if text or href matches date/initiatives)
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        text = a_tag.get_text().strip()
        
        if not href or href.startswith('#') or href.startswith('javascript:'):
            continue
            
        combined = text + " " + href
        is_june = check_string_for_patterns(combined, JUNE_2026_PATS)
        is_july = check_string_for_patterns(combined, JULY_2026_PATS)
        is_march = check_string_for_patterns(combined, MARCH_2026_PATS)
        
        abs_url = urllib.parse.urljoin(base_url, href)
        if is_june:
            june_links.append(abs_url)
        if is_july:
            july_links.append(abs_url)
        if is_march:
            march_links.append(abs_url)
            
    # 4. Regex fallback on raw HTML content for raw URL paths (e.g. Bäretswil inside data attributes)
    clean_html = html.replace('\\/', '/').replace('&quot;', '"').replace('\\"', '"')
    # Find any anlass/termine paths
    paths = re.findall(r'/(?:_rte/)?(?:anlass|termine)/\d+', clean_html)
    for path in paths:
        # Check if the text surrounding the path mentions the date
        idx = clean_html.find(path)
        if idx != -1:
            context = clean_html[max(0, idx-300):idx+300]
            is_june = check_string_for_patterns(context, JUNE_2026_PATS)
            is_july = check_string_for_patterns(context, JULY_2026_PATS)
            is_march = check_string_for_patterns(context, MARCH_2026_PATS)
            
            abs_url = urllib.parse.urljoin(base_url, path)
            if is_june:
                june_links.append(abs_url)
            if is_july:
                july_links.append(abs_url)
            if is_march:
                march_links.append(abs_url)

    # De-duplicate lists
    june_links = list(dict.fromkeys(june_links))
    july_links = list(dict.fromkeys(july_links))
    march_links = list(dict.fromkeys(march_links))
    
    return (
        june_links[0] if june_links else None,
        july_links[0] if july_links else None,
        march_links[0] if march_links else None
    )

async def process_gemeinde(client, row, semaphore):
    async with semaphore:
        domain = row['official_domain']
        gde_id = row['id_gde']
        gde_name = row['name_gde']
        
        result = {
            "id_gde": gde_id,
            "name_gde": gde_name,
            "official_domain": domain,
            "vote_landing_page": None,
            "specific_vote_page_june_2026": None,
            "specific_vote_page_july_2026": None,
            "past_vote_page_march_2026": None,
            "status": "failed"
        }
        
        if pd.isna(domain) or not domain:
            result["status"] = "no official domain found"
            return result
            
        try:
            # Step 1: Find voting landing page
            landing_url, landing_status = await find_landing_page(client, domain)
            if not landing_url:
                result["status"] = landing_status
                return result
                
            result["vote_landing_page"] = landing_url
            
            # Step 2: Fetch landing page to parse specific vote dates
            resp = await client.get(landing_url, follow_redirects=True, timeout=8.0)
            if resp.status_code == 200:
                june_page, july_page, march_page = parse_html_for_vote_pages(resp.text, str(resp.url))
                
                result["specific_vote_page_june_2026"] = june_page or landing_url
                result["specific_vote_page_july_2026"] = july_page or landing_url
                result["past_vote_page_march_2026"] = march_page
                result["status"] = "success"
            else:
                result["specific_vote_page_june_2026"] = landing_url
                result["specific_vote_page_july_2026"] = landing_url
                result["status"] = f"landing page fetched with status {resp.status_code}"
                
        except Exception as e:
            result["status"] = f"error: {type(e).__name__}"
            
        return result

async def main():
    print("Step 1: Loading Gemeinden domains...")
    df = pd.read_csv('gemeinden_domains.csv')
    print(f"Loaded {len(df)} rows.")
    
    # Filter rows that have an official domain
    valid_df = df[df['official_domain'].notna() & (df['official_domain'] != '')]
    print(f"Rows with official domains: {len(valid_df)}")
    
    # Limit for testing/speed if needed, but we will process all of them
    # valid_df = valid_df.head(100) # uncomment for quick test
    
    print("Step 2: Starting parallel crawl...")
    semaphore = asyncio.Semaphore(80) # Concurrency limit 80
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    start_time = time.time()
    
    async with httpx.AsyncClient(headers=headers, verify=False, follow_redirects=True) as client:
        tasks = []
        for idx, row in valid_df.iterrows():
            tasks.append(process_gemeinde(client, row, semaphore))
            
        print(f"Crawl launched for {len(tasks)} municipalities...")
        
        results = []
        completed = 0
        for task in asyncio.as_completed(tasks):
            res = await task
            results.append(res)
            completed += 1
            if completed % 100 == 0 or completed == len(tasks):
                print(f"  Progress: {completed}/{len(tasks)} processed ({completed/len(tasks)*100:.1f}%)")
                
    elapsed = time.time() - start_time
    print(f"Crawl completed in {elapsed:.2f} seconds.")
    
    # Build final DataFrame
    results_df = pd.DataFrame(results)
    
    # Merge back with the original df to include the ones without domains
    all_results_df = df[['id_gde', 'name_gde', 'official_domain']].merge(results_df, on=['id_gde', 'name_gde', 'official_domain'], how='left')
    
    # Save output
    all_results_df.to_csv('gemeinden_vote_pages.csv', index=False)
    
    # Statistics
    total = len(all_results_df)
    success = all_results_df[all_results_df['status'] == 'success']
    print(f"\nFinal Statistics:")
    print(f"  Total Swiss Gemeinden: {total}")
    print(f"  Successfully Crawled: {len(success)} / {total} ({len(success)/total*100:.2f}%)")
    print(f"  Specific June 2026 Pages Found: {all_results_df['specific_vote_page_june_2026'].notna().sum()} / {total}")
    print(f"  Specific Past March 2026 Pages Found: {all_results_df['past_vote_page_march_2026'].notna().sum()} / {total}")
    print(f"Saved results to 'gemeinden_vote_pages.csv'.")

if __name__ == '__main__':
    asyncio.run(main())
