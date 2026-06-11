import httpx
from bs4 import BeautifulSoup

url = "https://www.satigny.ch/pages/ma-commune/politique/votations-et-elections-1776"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    resp = httpx.get(url, headers=headers, follow_redirects=True, verify=False, timeout=15.0)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Search for "A lire aussi"
    for element in soup.find_all(text=lambda t: t and "lire aussi" in t.lower()):
        print("Found text:", element)
        print("Parent tag:", element.parent.name, "attrs:", element.parent.attrs)
        # Print parent elements up to 4 levels
        p = element.parent
        for i in range(4):
            if p:
                print(f"Level {i}: <{p.name} class='{p.get('class')}' id='{p.get('id')}'>")
                p = p.parent
except Exception as e:
    print("Error:", e)
