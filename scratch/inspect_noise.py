import httpx
from bs4 import BeautifulSoup

urls = [
    "https://dardagny.ch",
    "https://www.aire-la-ville.ch/votations-et-elections/",
    "https://www.grone.ch/commune/votations-federales-139.html"
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

for url in urls:
    print(f"\nFetching {url}...")
    try:
        resp = httpx.get(url, headers=headers, follow_redirects=True, verify=False, timeout=10.0)
        if resp.status_code != 200:
            print(f"Failed to fetch: {resp.status_code}")
            continue
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Look for the noise keywords in the HTML and print their paths
        keywords = ["Bientôt l’été", "nature se réveille", "parc de la Mairie", "cerisiers en fleurs", "vallon-rechy"]
        found = False
        
        for k in keywords:
            for element in soup.find_all(text=lambda t: t and k in t):
                found = True
                print(f"Found keyword '{k}' inside tag <{element.parent.name}> with attrs {element.parent.attrs}")
                # Print up to 3 parent levels
                p = element.parent
                path = []
                for _ in range(4):
                    if p:
                        path.append(f"{p.name}.{'.'.join(p.get('class', []))}" if p.get('class') else p.name)
                        p = p.parent
                print(f"  Parent path: {' -> '.join(reversed(path))}")
                
        if not found:
            # Let's search for any divs that might be carousels or flexsliders
            print("No exact keywords found. Searching for slider/carousel classes:")
            for cls in ["slider", "flexslider", "carousel", "slideshow", "hero", "swiper"]:
                for el in soup.find_all(class_=lambda c: c and cls in c):
                    print(f"  Found class matching '{cls}': <{el.name} class='{el.get('class')}'>")
                    
    except Exception as e:
        print(f"Error fetching: {e}")
