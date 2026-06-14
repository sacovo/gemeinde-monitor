import asyncio
import heapq
import re
import hashlib
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime
import difflib
import argparse
import pandas as pd
import httpx
from bs4 import BeautifulSoup

# Setup logging
def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")
    sys.stdout.flush()

def get_url_hash(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()

def clean_html(html_content, url, global_excludes, url_excludes):
    if html_content.startswith("__PDF_FILE_HASH__:"):
        pdf_hash = html_content.split(":", 1)[1]
        return f"PDF Document (SHA256: {pdf_hash})"
        
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Remove global exclude selectors
    for selector in global_excludes:
        try:
            for element in soup.select(selector):
                element.decompose()
        except Exception as e:
            # Ignore invalid selector errors
            pass
            
    # 2. Remove URL-specific exclude selectors
    # Checks if the configuration pattern is contained within the URL
    for pattern, selectors in url_excludes.items():
        if pattern in url:
            for selector in selectors:
                try:
                    for element in soup.select(selector):
                        element.decompose()
                except Exception as e:
                    pass
                    
    # 3. Format <a> tags as markdown-like links [Text](href)
    for a in soup.find_all('a'):
        if a.attrs is None:
            continue
        text = a.get_text().strip()
        href = a.get('href', '').strip()
        
        # Discard empty links (layout/icon tags with no text)
        if not text:
            a.replace_with("")
            continue
            
        # Normalize/Discard jobs, career, and real estate links
        text_lower = text.lower()
        if any(jobs_kw in text_lower for jobs_kw in ["open positions", "offene stellen", "stellenangebote", "vacancies", "jobs", "real estate", "immobilien", "career", "carrier", "stellenausschreibung", "stelleninserat", "jobangebot", "jobangebote", "stellenangebot", "jobinserate", "stellenbeschreibungen"]):
            a.decompose()
            continue
            
        # Normalize/Discard event/calendar links that are not related to voting
        href_lower = href.lower()
        evt_keywords = ["/agenda/", "/events/", "/event/", "/veranstaltung/", "/veranstaltungen/", "/manifestation/", "/manifestations/", "/calendrier/", "/kalender/"]
        vote_keywords = ["vote", "abstimmung", "wahl", "scrutin", "elec", "votazione", "elezioni"]
        if any(evt_kw in href_lower for evt_kw in evt_keywords):
            if not any(vote_kw in href_lower or vote_kw in text_lower for vote_kw in vote_keywords):
                a.decompose()
                continue
            
        # Normalize email protection links
        if 'email-protection' in href or 'cdn-cgi/l/email-protection' in href:
            a.replace_with(" [[email protected]] ")
            continue
        if href.startswith('javascript:link_obo_mailer'):
            a.replace_with(" [Email](javascript:email) ")
            continue
            
        # Resolve relative hrefs (keep anchor or js placeholders as is)
        if href and not href.startswith('#') and not href.startswith('javascript:'):
            try:
                href = urllib.parse.urljoin(url, href)
            except Exception:
                pass
                
        # Strip dynamic query parameters from href (like blackhole, navid, tokens, session IDs)
        if href and '?' in href:
            try:
                parsed_href = urllib.parse.urlparse(href)
                query_params = urllib.parse.parse_qsl(parsed_href.query)
                cleaned_params = []
                for k, v in query_params:
                    k_lower = k.lower()
                    if k_lower in ["blackhole", "navid", "token", "sessionid", "session", "phpsessid", "cachebuster", "_"]:
                        continue
                    if len(v) > 16 and re.match(r'^[a-fA-F0-9]+$', v):
                        continue
                    cleaned_params.append((k, v))
                new_query = urllib.parse.urlencode(cleaned_params)
                parsed_href = parsed_href._replace(query=new_query)
                href = urllib.parse.urlunparse(parsed_href)
            except Exception:
                pass
                
        # Strip dynamic collapses or accordions
        if href.startswith('#'):
            href = re.sub(r'#(?:icms_)?collapse[a-zA-Z0-9_-]*\d+', '#collapse', href, flags=re.IGNORECASE)
            href = re.sub(r'#accordion[a-zA-Z0-9_-]*\d+', '#accordion', href, flags=re.IGNORECASE)
            
        # Discard links pointing to images (which are usually rotating banners/headers)
        is_image = any(href.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp'])
        if is_image:
            a.replace_with(text)
            continue
            
        # Replace the tag with a string representation
        a.replace_with(f" [{text}]({href}) ")
        
    # 4. Extract text
    text = soup.get_text()
    
    # 5. Normalize whitespace line by line and discard empty or dynamic lines
    lines = []
    for line in text.splitlines():
        cleaned_line = " ".join(line.split()).strip()
        if not cleaned_line:
            continue
        # Skip dynamic iCal/calendar fields
        if any(cleaned_line.startswith(dyn_kw) for dyn_kw in ["DTSTART:", "DTEND:", "DTSTAMP:", "CREATED:", "LAST-MODIFIED:", "SEQUENCE:", "UID:", "PRODID:"]):
            continue
        # Skip JSON-like lines (often map widget configurations or inline coordinates)
        if cleaned_line.startswith("[{") or cleaned_line.startswith("{"):
            try:
                json.loads(cleaned_line)
                continue
            except json.JSONDecodeError:
                pass
        lines.append(cleaned_line)
            
    return "\n".join(lines)

def load_config(config_path):
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Ensure structure is valid
                config.setdefault("webhook_url", "")
                config.setdefault("check_interval_seconds", 180)
                config.setdefault("concurrency_limit", 50)
                config.setdefault("request_timeout", 10.0)
                config.setdefault("global_exclude_selectors", [])
                config.setdefault("url_exclude_selectors", {})
                return config
        else:
            log(f"Config file not found at {config_path}. Using defaults.", "WARNING")
    except Exception as e:
        log(f"Error loading config: {e}. Using defaults.", "ERROR")
        
    return {
        "webhook_url": "",
        "check_interval_seconds": 180,
        "concurrency_limit": 50,
        "request_timeout": 10.0,
        "global_exclude_selectors": [],
        "url_exclude_selectors": {}
    }

async def send_webhook(webhook_url, payload):
    if not webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 200 and resp.status_code < 300:
                log(f"Webhook delivered successfully: HTTP {resp.status_code} to {webhook_url}")
            else:
                log(f"Webhook failed: HTTP {resp.status_code} from {webhook_url}", "ERROR")
    except Exception as e:
        log(f"Error sending webhook to {webhook_url}: {e}", "ERROR")

async def fetch_url(client, url, semaphore, timeout):
    async with semaphore:
        try:
            resp = await client.get(url, follow_redirects=True, timeout=timeout)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "").lower()
                if "application/pdf" in content_type or url.lower().endswith(".pdf"):
                    pdf_hash = hashlib.sha256(resp.content).hexdigest()
                    return url, f"__PDF_FILE_HASH__:{pdf_hash}", None
                return url, resp.text, None
            else:
                return url, None, f"HTTP {resp.status_code}"
        except Exception as e:
            return url, None, f"{type(e).__name__}: {str(e)}"

async def check_url(url, html_content, cache_dir, changes_dir, config, url_to_gdes):
    url_hash = get_url_hash(url)
    cache_path = os.path.join(cache_dir, f"{url_hash}.txt")
    
    # 1. Clean HTML to text representation
    cleaned_text = clean_html(
        html_content, 
        url, 
        config["global_exclude_selectors"], 
        config["url_exclude_selectors"]
    )
    
    # Ignore transient server error pages and backend CMS failures
    lower_text = cleaned_text.lower()
    error_keywords = [
        "internal server error",
        "500 - internal error",
        "backend error",
        "error getting data from back-office",
        "500 internal error",
        "internal error",
        "temporary failure",
        "service unavailable",
        "gateway timeout",
        "bad gateway"
    ]
    if any(kw in lower_text for kw in error_keywords):
        log(f"Ignoring transient server/backend error page for {url}", "DEBUG")
        return False
        
    # Mapped municipalities list
    gdes = url_to_gdes.get(url, [])
    gde_names = [f"{g['name']} (ID {g['id']})" for g in gdes]
    gde_summary = ", ".join(gde_names) if gde_names else "Unknown Municipality"
    
    # 2. Check if cached state exists
    if not os.path.exists(cache_path):
        # Initial run: write quiet cache and update index
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_text)
        log(f"Initialized cache for {url} ({gde_summary})")
        return False
        
    # Read existing cached text
    with open(cache_path, 'r', encoding='utf-8') as f:
        cached_text = f.read()
        
    if cached_text == cleaned_text:
        return False
        
    # Change detected!
    log(f"Change detected on: {url} ({gde_summary})", "WARNING")
    
    # Generate unified diff
    cached_lines = cached_text.splitlines()
    cleaned_lines = cleaned_text.splitlines()
    diff_generator = difflib.unified_diff(
        cached_lines, 
        cleaned_lines, 
        fromfile="previous_state", 
        tofile="current_state", 
        lineterm=""
    )
    diff_text = "\n".join(list(diff_generator))
    
    # Save diff to history file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    diff_filename = f"change_{timestamp}_{url_hash}.diff"
    diff_filepath = os.path.join(changes_dir, diff_filename)
    
    # Print diff to stdout (truncated if very large to prevent console lockup)
    diff_lines = diff_text.splitlines()
    if len(diff_lines) > 100:
        truncated_diff = "\n".join(diff_lines[:100]) + f"\n... [Diff truncated to 100 lines, full diff saved to {diff_filename}]"
    else:
        truncated_diff = diff_text
        
    print(f"\n--- DIFF FOR {url} ---\n{truncated_diff}\n---------------------\n")
    sys.stdout.flush()
    
    with open(diff_filepath, 'w', encoding='utf-8') as f:
        f.write(f"URL: {url}\nMunicipalities: {gde_summary}\nTimestamp: {datetime.now().isoformat()}\n\n{diff_text}")
    log(f"Saved diff to {diff_filepath}")
    
    # Write new text to cache
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(cleaned_text)
        
    # Trigger webhook asynchronously
    payload = {
        "url": url,
        "timestamp": datetime.now().isoformat(),
        "diff": diff_text,
        "municipalities": gdes
    }
    await send_webhook(config["webhook_url"], payload)
    return True

async def check_worker(url, semaphore, client, config, url_to_gdes, cache_dir, changes_dir, stats):
    try:
        url, html_content, error = await fetch_url(client, url, semaphore, config["request_timeout"])
        if error:
            log(f"Fetch failed for {url}: {error}", "DEBUG")
            stats["fail"] += 1
            return
            
        stats["success"] += 1
        changed = await check_url(url, html_content, cache_dir, changes_dir, config, url_to_gdes)
        if changed:
            stats["change"] += 1
    except Exception as e:
        log(f"Error checking content for {url}: {e}", "ERROR")
        stats["error"] += 1

async def stats_logger(stats, queue):
    while True:
        try:
            await asyncio.sleep(60)
            log(f"Queue status: {len(queue)} items. Stats (past 60s): {stats['success']} success, {stats['fail']} failed, {stats['change']} changes detected, {stats['error']} errors.")
            # Reset stats counters for the next minute interval
            stats["success"] = 0
            stats["fail"] = 0
            stats["change"] = 0
            stats["error"] = 0
        except asyncio.CancelledError:
            break

def main():
    parser = argparse.ArgumentParser(description="Monitor Swiss Gemeinde voting results pages for changes.")
    parser.add_argument("--limit", type=int, default=None, help="Limit to the first N unique URLs (for testing)")
    parser.add_argument("--once", action="store_true", help="Run once and exit immediately")
    parser.add_argument("--config", default="monitor_config.json", help="Path to config file")
    parser.add_argument("--csv", default="gemeinden_vote_pages.csv", help="Path to CSV mapping file")
    parser.add_argument("--webhook", default=None, help="Webhook URL to override the config file webhook")
    args = parser.parse_args()
    
    # Create required directories
    cache_dir = "monitor_cache"
    changes_dir = "monitor_changes"
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(changes_dir, exist_ok=True)
    
    # 1. Parse CSV and build mapping
    if not os.path.exists(args.csv):
        print(f"Error: CSV file not found at {args.csv}")
        sys.exit(1)
        
    df = pd.read_csv(args.csv)
    url_to_gdes = {}
    
    # Extract URLs from vote_landing_page, specific_vote_page_june_2026, and specific_vote_page_july_2026
    for _, row in df.iterrows():
        gde_id = str(row['id_gde'])
        gde_name = str(row['name_gde'])
        
        for col in ['vote_landing_page', 'specific_vote_page_june_2026', 'specific_vote_page_july_2026']:
            url = row[col]
            if pd.isna(url) or not isinstance(url, str):
                continue
            url = url.strip()
            if not url.startswith('http'):
                continue
                
            gde_info = {"id": gde_id, "name": gde_name}
            if url not in url_to_gdes:
                url_to_gdes[url] = []
            if gde_info not in url_to_gdes[url]:
                url_to_gdes[url].append(gde_info)
                
    unique_urls = list(url_to_gdes.keys())
    log(f"Loaded {len(unique_urls)} unique URLs from {args.csv}")
    
    # Apply limit if specified
    if args.limit is not None:
        unique_urls = unique_urls[:args.limit]
        log(f"Limiting crawl to first {args.limit} unique URLs")
        
    # Write a mapping index for debugging hashes -> URLs
    index_path = os.path.join(cache_dir, "index.json")
    index_data = {get_url_hash(url): url for url in unique_urls}
    # Load existing index if any, update it, and write it
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
                existing.update(index_data)
                index_data = existing
        except Exception:
            pass
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=2)
        
    # Crawl loop setup
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    async def loop():
        # Keep client persistent if possible or recreate it to avoid resource leaks
        async with httpx.AsyncClient(headers=headers, verify=False, follow_redirects=True) as client:
            # Load initial config
            config = load_config(args.config)
            if args.webhook:
                config["webhook_url"] = args.webhook
            
            interval = config.get("check_interval_seconds", 180)
            
            # Initialize stats
            stats = {"success": 0, "fail": 0, "change": 0, "error": 0}
            
            # Setup priority queue (heap)
            # Stagger initial checks over the interval if not running once
            now = time.time()
            queue = []
            for i, url in enumerate(unique_urls):
                if args.once:
                    ttl = now
                else:
                    stagger = (i * (interval / len(unique_urls))) if len(unique_urls) > 0 else 0
                    ttl = now + stagger
                heapq.heappush(queue, (ttl, url))
                
            log(f"Initialized queue with {len(queue)} URLs. Check interval: {interval}s.")
            if not args.once and len(unique_urls) > 0:
                log(f"Staggering initial checks over {interval}s (approx. every {interval/len(unique_urls):.3f}s)")
                
            # Create semaphore
            semaphore = asyncio.Semaphore(config["concurrency_limit"])
            
            # Active task set
            active_tasks = set()
            
            # Start stats logger in background
            stats_logger_task = None
            if not args.once:
                stats_logger_task = asyncio.create_task(stats_logger(stats, queue))
                
            while queue:
                # Reload config dynamically
                config = load_config(args.config)
                if args.webhook:
                    config["webhook_url"] = args.webhook
                
                # Check the first item in heap
                ttl, url = queue[0]
                now = time.time()
                
                if now < ttl:
                    # Not due yet, sleep until due
                    sleep_time = ttl - now
                    await asyncio.sleep(min(sleep_time, 1.0))
                    continue
                
                # Due! Pop it
                heapq.heappop(queue)
                
                # Launch the check
                task = asyncio.create_task(
                    check_worker(url, semaphore, client, config, url_to_gdes, cache_dir, changes_dir, stats)
                )
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)
                
                # Re-enqueue if not running once
                if not args.once:
                    next_interval = config.get("check_interval_seconds", 180)
                    next_ttl = time.time() + next_interval
                    heapq.heappush(queue, (next_ttl, url))
                    
            # Queue is empty (only possible if args.once is True)
            if args.once:
                if active_tasks:
                    log(f"Waiting for {len(active_tasks)} active checks to complete...")
                    await asyncio.gather(*active_tasks, return_exceptions=True)
                log(f"Once-off check finished. Success: {stats['success']}, Failed: {stats['fail']}, Changes: {stats['change']}")
                
            if stats_logger_task:
                stats_logger_task.cancel()
                try:
                    await stats_logger_task
                except asyncio.CancelledError:
                    pass
                
    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        log("Monitor stopped by user keyboard interrupt.")

if __name__ == '__main__':
    main()
