import httpx
from bs4 import BeautifulSoup

url = "https://www.troistorrents.ch/commune/votations-elections-242.html"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    resp = httpx.get(url, headers=headers, follow_redirects=True, verify=False, timeout=15.0)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Search for "Manifestations"
    for element in soup.find_all(text=lambda t: t and "manifestations" in t.lower()):
        print("Found text:", element)
        print("Parent tag:", element.parent.name, "attrs:", element.parent.attrs)
        p = element.parent
        for i in range(4):
            if p:
                print(f"Level {i}: <{p.name} class='{p.get('class')}' id='{p.get('id')}'>")
                p = p.parent
except Exception as e:
    print("Error:", e)
