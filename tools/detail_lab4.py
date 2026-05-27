import os, time, re, sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

OUTPUT_DIR = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_lab_4"
os.makedirs(OUTPUT_DIR, exist_ok=True)

DETAIL_URL = "https://suchen.mobile.de/fahrzeuge/details.html?id=381986422"
VENDOR_URL = "https://home.mobile.de/2PSRL#ses"

def test_pw_warmup():
    print("\n--- Running A9: Playwright Warmup + Direct Detail ---")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=os.path.join(OUTPUT_DIR, "pw_profile_warm"),
                headless=False,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser.pages[0]
            
            print("Warming up on Vendor Page...")
            page.goto(VENDOR_URL, wait_until="domcontentloaded")
            time.sleep(4)
            
            print("Navigating to Detail URL in same tab...")
            page.goto(DETAIL_URL, wait_until="domcontentloaded")
            time.sleep(5)
            
            html = page.content()
            html_lower = html.lower()
            
            with open(os.path.join(OUTPUT_DIR, "A9_detail.html"), "w", encoding="utf-8") as f:
                f.write(html)
                
            if "edgesuite" in html_lower or "px-captcha" in html_lower or "perimeterx" in html_lower:
                print("A9 Result: Blocked.")
            else:
                found_co2 = bool(re.search(r'co2|emission', html_lower))
                print(f"A9 Result: Target fields found (CO2): {found_co2}")
                
            browser.close()
    except Exception as e:
        print("Playwright error:", e)

def test_dp_warmup():
    print("\n--- Running C3: DrissionPage Warmup + Direct Detail ---")
    from DrissionPage import ChromiumPage, ChromiumOptions
    try:
        co = ChromiumOptions()
        co.set_argument('--headless=false')
        co.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = ChromiumPage(co)
        
        print("Warming up on Vendor Page...")
        page.get(VENDOR_URL)
        time.sleep(4)
        
        print("Navigating to Detail URL in same tab...")
        page.get(DETAIL_URL)
        time.sleep(5)
        
        html = page.html
        html_lower = html.lower()
        
        with open(os.path.join(OUTPUT_DIR, "C3_detail.html"), "w", encoding="utf-8") as f:
            f.write(html)
            
        if "edgesuite" in html_lower or "px-captcha" in html_lower or "perimeterx" in html_lower:
            print("C3 Result: Blocked.")
        else:
            found_co2 = bool(re.search(r'co2|emission', html_lower))
            print(f"C3 Result: Target fields found (CO2): {found_co2}")
            
        page.quit()
    except Exception as e:
        print("DrissionPage error:", e)

if __name__ == '__main__':
    test_pw_warmup()
    test_dp_warmup()
