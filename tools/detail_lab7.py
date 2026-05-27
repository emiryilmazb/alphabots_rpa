import os, time, sys, re, json

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
OUTPUT_DIR = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_lab_7"
os.makedirs(OUTPUT_DIR, exist_ok=True)

VENDOR_URL = "https://home.mobile.de/2PSRL#ses"
FALLBACK_DETAIL_URL = "https://suchen.mobile.de/fahrzeuge/details.html?id=381986422"

def check_reality(html):
    lower_html = html.lower()
    if "zugriff verweigert" in lower_html or "access denied" in lower_html:
        return False, "Access denied page"
    if "edgesuite.net" in lower_html or "px-captcha" in lower_html or "perimeterx" in lower_html:
        return False, "Edgesuite/PerimeterX blocked"
    if "co2" in lower_html and "baureihe" in lower_html:
        return True, "Real detail page (Fields found)"
    return False, "Unknown state (might be captcha or 404)"

def test_uc_and_curl():
    print("\n--- Running F3 & D3: Undetected Chromedriver + curl_cffi Cookie Passing ---")
    try:
        import undetected_chromedriver as uc
        from curl_cffi import requests
        
        options = uc.ChromeOptions()
        options.add_argument("--disable-popup-blocking")
        driver = uc.Chrome(version_main=148, options=options)
        
        print("Going to vendor page to bypass initial checks and get cookies...")
        driver.get(VENDOR_URL)
        time.sleep(8)  # Let PX solve JS challenges
        
        # Accept cookies if possible
        try:
            driver.execute_script("""
                let btns = Array.from(document.querySelectorAll('button'));
                let accept = btns.find(b => b.innerText.includes('Akzeptieren') || b.innerText.includes('Accept'));
                if(accept) accept.click();
            """)
            time.sleep(2)
        except: pass

        # Extract all links
        links = driver.execute_script("return Array.from(document.querySelectorAll('a')).map(a => a.href);")
        detail_links = [h for h in links if ("details.html" in h or "id=" in h or "/fahrzeuge/" in h) and "home.mobile.de" not in h]
        detail_links = list(set([h for h in detail_links if h.startswith("http")]))
        
        target_url = FALLBACK_DETAIL_URL
        if detail_links:
            target_url = detail_links[0]
            print(f"Found dynamic target URL: {target_url}")
        else:
            print(f"No dynamic links found. Using fallback: {target_url}")
            
        # Extract cookies
        selenium_cookies = driver.get_cookies()
        cookie_dict = {c['name']: c['value'] for c in selenium_cookies}
        print(f"Extracted {len(cookie_dict)} cookies (including PX tokens if any).")
        
        print("\n--- [D3] Sending curl_cffi request with UC cookies ---")
        headers = {
            "User-Agent": driver.execute_script("return navigator.userAgent;"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": VENDOR_URL,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-site",
        }
        
        try:
            res = requests.get(target_url, headers=headers, cookies=cookie_dict, impersonate="chrome120", timeout=15)
            html_curl = res.text
            real_c, notes_c = check_reality(html_curl)
            print(f"curl_cffi Result: {notes_c} | Real: {real_c}")
            with open(os.path.join(OUTPUT_DIR, "D3_curl_with_uc_cookies.html"), "w", encoding="utf-8") as f:
                f.write(html_curl)
        except Exception as e:
            print("curl_cffi failed:", e)
            
        print("\n--- [F3] Running UC Direct Navigation to Target ---")
        driver.get(target_url)
        time.sleep(7)
        html_uc = driver.page_source
        real_u, notes_u = check_reality(html_uc)
        print(f"UC Direct Result: {notes_u} | Real: {real_u}")
        with open(os.path.join(OUTPUT_DIR, "F3_uc_direct.html"), "w", encoding="utf-8") as f:
            f.write(html_uc)
            
        driver.quit()
    except Exception as e:
        print("UC/Curl error:", e)

if __name__ == '__main__':
    test_uc_and_curl()
