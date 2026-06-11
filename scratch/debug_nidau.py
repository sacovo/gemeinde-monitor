import httpx
import traceback
from monitor_votes import clean_html, load_config

url = "https://www.nidau.ch/de/politik-verwaltung/abstimmungen-wahlen/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print(f"Fetching {url}...")
try:
    resp = httpx.get(url, headers=headers, follow_redirects=True, verify=False, timeout=15.0)
    print(f"Status: {resp.status_code}")
    
    config = load_config("monitor_config.json")
    print("Running clean_html...")
    cleaned = clean_html(
        resp.text,
        url,
        config["global_exclude_selectors"],
        config["url_exclude_selectors"]
    )
    print("Success! Cleaned length:", len(cleaned))
except Exception as e:
    print("Error encountered:")
    traceback.print_exc()
