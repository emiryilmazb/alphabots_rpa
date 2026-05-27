import os, time, sys, re, json

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

OUTPUT_DIR = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_lab_5"
os.makedirs(OUTPUT_DIR, exist_ok=True)

DETAIL_URL = "https://suchen.mobile.de/fahrzeuge/details.html?id=381986422"
VENDOR_URL = "https://home.mobile.de/2PSRL#ses"

def check_reality(html):
    lower_html = html.lower()
    if "zugriff verweigert" in lower_html or "access denied" in lower_html:
        return False, "Access denied page"
    if "edgesuite.net" in lower_html or "px-captcha" in lower_html or "perimeterx" in lower_html:
        return False, "Edgesuite/PerimeterX blocked"
    if "co2" in lower_html and "baureihe" in lower_html:
        return True, "Real detail page (Fields found)"
    return False, "Unknown state"

def install_deps():
    import subprocess
    print("Checking dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright-stealth", "undetected-chromedriver", "selenium"])

def test_pw_stealth():
    print("\n--- Running E1: Playwright + Stealth (Direct) ---")
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import stealth_sync
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            page = ctx.new_page()
            stealth_sync(page)
            
            page.goto(DETAIL_URL, wait_until="domcontentloaded")
            time.sleep(5)
            html = page.content()
            real, notes = check_reality(html)
            print(f"E1 Result: {notes} | Real: {real}")
            
            with open(os.path.join(OUTPUT_DIR, "E1_pw_stealth.html"), "w", encoding="utf-8") as f:
                f.write(html)
            browser.close()
    except Exception as e:
        print("Playwright Stealth error:", e)

def test_uc():
    print("\n--- Running F1: Undetected Chromedriver (Direct) ---")
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        
        options = uc.ChromeOptions()
        options.add_argument("--disable-popup-blocking")
        driver = uc.Chrome(options=options)
        
        driver.get(DETAIL_URL)
        time.sleep(5)
        html = driver.page_source
        real, notes = check_reality(html)
        print(f"F1 Result: {notes} | Real: {real}")
        
        with open(os.path.join(OUTPUT_DIR, "F1_uc.html"), "w", encoding="utf-8") as f:
            f.write(html)
            
        print("\n--- Running F2: Undetected Chromedriver (Warmup + Click) ---")
        driver.get(VENDOR_URL)
        time.sleep(4)
        # find link and click
        try:
            btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Akzeptieren')]")
            if btn: btn.click()
            time.sleep(1)
        except:
            pass
            
        try:
            link = driver.find_element(By.XPATH, "//a[contains(@href, 'details.html')]")
            driver.execute_script("arguments[0].scrollIntoView(true);", link)
            time.sleep(1)
            link.click()
            time.sleep(5)
            
            html2 = driver.page_source
            real2, notes2 = check_reality(html2)
            print(f"F2 Result: {notes2} | Real: {real2}")
            
            with open(os.path.join(OUTPUT_DIR, "F2_uc_click.html"), "w", encoding="utf-8") as f:
                f.write(html2)
        except Exception as ex:
            print("F2 Click error:", ex)
            
        driver.quit()
    except Exception as e:
        print("Undetected Chromedriver error:", e)

if __name__ == '__main__':
    install_deps()
    test_pw_stealth()
    test_uc()
