import os
import time
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

URLS = [
    "https://suchen.mobile.de/fahrzeuge/details.html?id=377508779",
    "https://suchen.mobile.de/fahrzeuge/details.html?id=381986422"
]
VENDOR_URL = "https://home.mobile.de/2PSRL#ses"

RESULTS = []

def log_result(strategy, url, status, html, duration):
    real, notes = check_reality(html)
    matches = {
        "co2": bool(re.search(r'co2|emission', html, re.I)),
        "baureihe": bool(re.search(r'baureihe', html, re.I)),
        "ausstattungslinie": bool(re.search(r'ausstattungslinie', html, re.I)),
        "pvo": bool(re.search(r'fahrzeughalter', html, re.I))
    }
    
    res = {
        "strategy": strategy,
        "url": url,
        "status": status,
        "real_detail_loaded": real,
        "notes": notes,
        "matches": matches,
        "duration": round(duration, 2),
        "html_length": len(html)
    }
    RESULTS.append(res)
    print(f"[{strategy}] Real: {real} | Status: {status} | Notes: {notes} | URL: {url}")

def check_reality(html):
    lower_html = html.lower()
    if "edgesuite.net" in lower_html or "error occurred while processing your request" in lower_html or "denied" in lower_html:
        return False, "Edgesuite/Error page blocked"
    if "co2" in lower_html and "baureihe" in lower_html and "ausstattungslinie" in lower_html:
        return True, "Real detail page loaded (Target fields found)"
    if "kraftstoffverbrauch" in lower_html or "ausstattung" in lower_html:
        return True, "Real detail page loaded (Partial fields)"
    return False, "Unknown state or CAPTCHA"

# STRATEGY A1: PLAYWRIGHT DIRECT HEADED
def test_pw_direct():
    print("\nRunning A1: Playwright Direct Headed...")
    from playwright.sync_api import sync_playwright
    for url in URLS:
        start = time.time()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                html = page.content()
                status = resp.status if resp else 0
                browser.close()
                log_result("A1_Playwright_Direct", url, status, html, time.time() - start)
        except Exception as e:
            log_result("A1_Playwright_Direct", url, 500, str(e), time.time() - start)

# STRATEGY A3: PLAYWRIGHT CLICK FROM CATEGORY
def test_pw_click():
    print("\nRunning A3: Playwright Click from Vendor...")
    from playwright.sync_api import sync_playwright
    start = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            page = ctx.new_page()
            page.goto(VENDOR_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            
            # find first vehicle link
            element = page.locator("a[href*='details.html']").first
            if element:
                detail_url = element.get_attribute("href")
                if not detail_url.startswith("http"):
                    detail_url = "https://home.mobile.de" + detail_url
                # Native click and wait for navigation
                with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                    element.click()
                page.wait_for_timeout(4000)
                html = page.content()
                log_result("A3_Playwright_Click", detail_url, 200, html, time.time() - start)
            else:
                log_result("A3_Playwright_Click", "N/A", 404, "No detail link found on vendor page", time.time() - start)
            browser.close()
    except Exception as e:
        log_result("A3_Playwright_Click", VENDOR_URL, 500, str(e), time.time() - start)

# STRATEGY C1: DRISSIONPAGE DIRECT HEADED
def test_dp_direct():
    print("\nRunning C1: DrissionPage Direct Headed...")
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "DrissionPage"])
        from DrissionPage import ChromiumPage, ChromiumOptions

    for url in URLS:
        start = time.time()
        try:
            co = ChromiumOptions()
            co.set_argument('--headless=false')
            co.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            page = ChromiumPage(co)
            page.get(url)
            time.sleep(4)
            html = page.html
            page.quit()
            log_result("C1_DrissionPage_Direct", url, 200, html, time.time() - start)
        except Exception as e:
            log_result("C1_DrissionPage_Direct", url, 500, str(e), time.time() - start)

# STRATEGY D1: CURL_CFFI
def test_curl_cffi():
    print("\nRunning D1: curl_cffi Impersonation...")
    try:
        from curl_cffi import requests
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "curl_cffi"])
        from curl_cffi import requests

    for url in URLS:
        start = time.time()
        try:
            res = requests.get(url, impersonate="chrome120", timeout=15)
            log_result("D1_curl_cffi_Direct", url, res.status_code, res.text, time.time() - start)
        except Exception as e:
            log_result("D1_curl_cffi_Direct", url, 500, str(e), time.time() - start)

if __name__ == "__main__":
    os.makedirs(os.path.join("..", "data", "runs", "detail_lab"), exist_ok=True)
    print("Starting detail lab tests...")
    
    test_pw_direct()
    test_pw_click()
    test_dp_direct()
    test_curl_cffi()
    
    out_path = os.path.join("..", "data", "runs", "detail_lab", "strategy_matrix.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nTests completed. Results saved to {out_path}")
