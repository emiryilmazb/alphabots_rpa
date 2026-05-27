import os
import time
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

VENDOR_URL = "https://home.mobile.de/2PSRL#ses"

RESULTS = []
OUTPUT_DIR = os.path.join("F:\\kod\\alphabots_rpa\\mobile_de_scraper", "data", "runs", "detail_lab_2")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
    print(f"[{strategy}] Real: {real} | Status: {status} | Notes: {notes} | URL: {url} | HTML Len: {len(html)}")
    
    safe_name = strategy + ".html"
    with open(os.path.join(OUTPUT_DIR, safe_name), "w", encoding="utf-8") as f:
        f.write(html)

def check_reality(html):
    lower_html = html.lower()
    if "edgesuite.net" in lower_html or "error occurred while processing your request" in lower_html or "denied" in lower_html:
        return False, "Edgesuite/Error page blocked"
    if "px-captcha" in lower_html or "perimeterx" in lower_html:
        return False, "PerimeterX CAPTCHA blocked"
    if "co2" in lower_html and "baureihe" in lower_html and "ausstattungslinie" in lower_html:
        return True, "Real detail page loaded (Target fields found)"
    if "kraftstoffverbrauch" in lower_html or "ausstattung" in lower_html:
        return True, "Real detail page loaded (Partial fields)"
    return False, "Unknown state or CAPTCHA"

# STRATEGY A3: PLAYWRIGHT CLICK
def test_pw_click():
    print("\nRunning A3: Playwright Click from Vendor...")
    from playwright.sync_api import sync_playwright
    start = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            page = ctx.new_page()
            page.goto(VENDOR_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            
            try:
                page.locator("button:has-text('Akzeptieren')").first.click(timeout=2000)
                page.wait_for_timeout(1000)
            except:
                pass
            
            element = page.locator("a[href*='details.html']").first
            if element.count() > 0:
                element.scroll_into_view_if_needed()
                page.wait_for_timeout(1500)
                
                with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                    element.click()
                page.wait_for_timeout(4000)
                
                html = page.content()
                log_result("A3_Playwright_Click", page.url, 200, html, time.time() - start)
            else:
                log_result("A3_Playwright_Click", "N/A", 404, "No detail link found", time.time() - start)
            browser.close()
    except Exception as e:
        log_result("A3_Playwright_Click", VENDOR_URL, 500, str(e), time.time() - start)

# STRATEGY C2: DRISSIONPAGE CLICK
def test_dp_click():
    print("\nRunning C2: DrissionPage Click from Vendor...")
    from DrissionPage import ChromiumPage, ChromiumOptions
    start = time.time()
    try:
        co = ChromiumOptions()
        co.set_argument('--headless=false')
        co.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = ChromiumPage(co)
        page.get(VENDOR_URL)
        time.sleep(4)
        
        try:
            cookie_btn = page.ele("t:button@text():Akzeptieren", timeout=2)
            if cookie_btn:
                cookie_btn.click()
                time.sleep(1)
        except:
            pass

        link_ele = page.ele("tag:a@@href:details.html", timeout=3)
        if link_ele:
            link_ele.click()
            time.sleep(5)
            html = page.html
            log_result("C2_DrissionPage_Click", page.url, 200, html, time.time() - start)
        else:
            log_result("C2_DrissionPage_Click", "N/A", 404, "No detail link", time.time() - start)
        page.quit()
    except Exception as e:
        log_result("C2_DrissionPage_Click", VENDOR_URL, 500, str(e), time.time() - start)

if __name__ == "__main__":
    test_pw_click()
    test_dp_click()
    
    out_path = os.path.join(OUTPUT_DIR, "strategy_matrix.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nSaved to {out_path}")
