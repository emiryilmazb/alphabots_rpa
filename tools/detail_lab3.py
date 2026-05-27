import os, time, json, re, sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

OUTPUT_DIR = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_lab_3"
os.makedirs(OUTPUT_DIR, exist_ok=True)

DETAIL_URL = "https://suchen.mobile.de/fahrzeuge/details.html?id=381986422"
VENDOR_URL = "https://home.mobile.de/2PSRL#ses"

def test_curl():
    print("\n--- Running D2: curl_cffi ---")
    try:
        from curl_cffi import requests
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://home.mobile.de/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
            "Upgrade-Insecure-Requests": "1"
        }
        res = requests.get(DETAIL_URL, headers=headers, impersonate="chrome120", timeout=15)
        html = res.text
        with open(os.path.join(OUTPUT_DIR, "D2_curl_cffi.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"D2 Status: {res.status_code}, Length: {len(html)}")
        if "edgesuite" in html.lower() or "perimeterx" in html.lower() or "px-captcha" in html.lower():
            print("D2 Blocked by PerimeterX/Edgesuite.")
        else:
            found_co2 = bool(re.search(r'co2|emission', html, re.I))
            print(f"D2 Success! Target fields found: {found_co2}")
    except Exception as e:
        print("curl_cffi error:", e)

def test_pw():
    print("\n--- Running A8: Playwright Persistent Context ---")
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=os.path.join(OUTPUT_DIR, "pw_profile"),
            headless=False,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.pages[0]
        
        print("Loading Vendor Page...")
        page.goto(VENDOR_URL, wait_until="domcontentloaded")
        time.sleep(5)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "1_vendor_page.png"))
        
        content = page.content().lower()
        if "edgesuite" in content or "px-captcha" in content:
            print("Vendor page blocked by bot protection!")
        
        # Bütün linkleri javascript üzerinden toplayalım (UI'da görünmez olsalar bile alır)
        links = page.locator("a").evaluate_all("els => els.map(e => e.href)")
        det_links = [l for l in links if "details.html" in l]
        print(f"Found {len(det_links)} details.html links.")
        
        if det_links:
            target = det_links[0]
            print(f"Navigating to detail URL in same tab: {target[:80]}...")
            try:
                page.goto(target, wait_until="domcontentloaded")
                time.sleep(5)
                page.screenshot(path=os.path.join(OUTPUT_DIR, "2_detail_page.png"))
                html = page.content()
                with open(os.path.join(OUTPUT_DIR, "2_detail_page.html"), "w", encoding="utf-8") as f:
                    f.write(html)
                
                html_lower = html.lower()
                found_co2 = bool(re.search(r'co2|emission', html_lower))
                found_baureihe = bool(re.search(r'baureihe', html_lower))
                print(f"A8 Result -> CO2: {found_co2}, Baureihe: {found_baureihe}")
                
                if "edgesuite" in html_lower or "px-captcha" in html_lower:
                    print("A8 Result -> Blocked by Edgesuite or PerimeterX.")
            except Exception as e:
                print("Error on detail page:", e)
        
        browser.close()

if __name__ == '__main__':
    test_curl()
    test_pw()
