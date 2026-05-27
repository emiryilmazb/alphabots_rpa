import os, time, sys, re, json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

OUT_DIR = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_observer_live"
os.makedirs(OUT_DIR, exist_ok=True)

def get_live_link_with_uc():
    print("\n=== PHASE 1: FINDING A GUARANTEED LIVE VEHICLE LINK ===")
    options = uc.ChromeOptions()
    options.add_argument("--disable-popup-blocking")
    driver = uc.Chrome(version_main=148, options=options)
    
    driver.get("https://home.mobile.de/AUTO-FAIR-HERFORD")
    time.sleep(6)
    
    try:
        # Try to dismiss cookies
        driver.execute_script("""
            let btns = Array.from(document.querySelectorAll('button'));
            let accept = btns.find(b => b.innerText.includes('Akzeptieren') || b.innerText.includes('Zustimmen'));
            if(accept) accept.click();
        """)
        time.sleep(2)
    except: pass

    driver.execute_script("window.scrollBy(0, 1500);")
    time.sleep(4)
    
    live_link = None
    links = driver.find_elements(By.TAG_NAME, "a")
    for l in links:
        try:
            href = l.get_attribute("href")
            if href and ("/auto-inserat/" in href or "details.html" in href):
                live_link = href
                break
        except: pass
        
    driver.quit()
    return live_link

def check_success(html, title, url):
    html_lower = html.lower()
    if "zugriff verweigert" in html_lower or "edgesuite" in html_lower or "px-captcha" in html_lower:
        return False, "Blocked (Edgesuite/PerimeterX)", {}
    
    # Real detail check
    is_real = "fahrzeugbeschreibung" in html_lower or "technische daten" in html_lower or "kategorie" in html_lower
    if not is_real and ("gebrauchtwagen und neuwagen" in title.lower() or url.endswith("mobile.de/")):
        return False, "Redirected to Homepage (Dead Link)", {}
        
    if is_real:
        extracted = {
            "co2": bool(re.search(r'co2|emission', html_lower, re.I)),
            "baureihe": bool(re.search(r'baureihe', html_lower, re.I)),
            "ausstattungslinie": bool(re.search(r'ausstattungslinie', html_lower, re.I)),
            "pvo": bool(re.search(r'fahrzeughalter', html_lower, re.I))
        }
        return True, "Real Detail Page Loaded", extracted
        
    return False, "Unknown/Blank", {}

def test_selenium_click(live_link):
    print("\n=== PHASE 2: RUNNING SELENIUM UC CLICK OBSERVER ===")
    options = uc.ChromeOptions()
    options.add_argument("--disable-popup-blocking")
    driver = uc.Chrome(version_main=148, options=options)
    
    driver.get("https://home.mobile.de/AUTO-FAIR-HERFORD")
    time.sleep(5)
    
    print(f"Targeting LIVE link: {live_link}")
    print("Executing JS window.open (simulating target=_blank click)...")
    driver.execute_script(f"window.open('{live_link}', '_blank');")
    time.sleep(2)
    
    # SWITCH TO NEW TAB
    driver.switch_to.window(driver.window_handles[-1])
    print("Switched to NEW tab. Waiting for DOM...")
    time.sleep(8)
    
    html = driver.page_source
    title = driver.title
    url = driver.current_url
    
    is_real, status, fields = check_success(html, title, url)
    print(f"\n[SELENIUM UC RESULT]")
    print(f"URL: {url}")
    print(f"Title: {title}")
    print(f"Status: {status}")
    print(f"Extracted: {fields}")
    
    with open(os.path.join(OUT_DIR, "uc_live_detail.html"), "w", encoding="utf-8") as f:
        f.write(html)
    driver.save_screenshot(os.path.join(OUT_DIR, "uc_live_detail.png"))
    
    print("\nPAUSING 15 SECONDS FOR LIVE OBSERVATION...")
    time.sleep(15)
    driver.quit()

def test_pw_persistent(live_link):
    print("\n=== PHASE 3: RUNNING PLAYWRIGHT PERSISTENT CLICK OBSERVER ===")
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=os.path.join(OUT_DIR, "pw_profile"),
            headless=False, 
            channel="chrome", # User asked for chrome stable channel click test
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800}
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        page.goto("https://home.mobile.de/AUTO-FAIR-HERFORD")
        time.sleep(5)
        
        print(f"Clicking LIVE link via JS in Playwright: {live_link}")
        with browser.expect_page(timeout=15000) as new_page_info:
            page.evaluate(f"window.open('{live_link}', '_blank');")
        
        new_page = new_page_info.value
        print("New tab captured! Waiting for load...")
        new_page.wait_for_load_state("domcontentloaded")
        time.sleep(8)
        
        html = new_page.content()
        title = new_page.title()
        url = new_page.url
        
        is_real, status, fields = check_success(html, title, url)
        print(f"\n[PLAYWRIGHT CHROME STABLE RESULT]")
        print(f"URL: {url}")
        print(f"Title: {title}")
        print(f"Status: {status}")
        print(f"Extracted: {fields}")
        
        with open(os.path.join(OUT_DIR, "pw_live_detail.html"), "w", encoding="utf-8") as f:
            f.write(html)
        new_page.screenshot(path=os.path.join(OUT_DIR, "pw_live_detail.png"), full_page=True)
        
        print("\nPAUSING 15 SECONDS FOR LIVE OBSERVATION...")
        time.sleep(15)
        browser.close()

if __name__ == '__main__':
    live_url = get_live_link_with_uc()
    if not live_url:
        print("FATAL: Could not find a live vehicle link on vendor page.")
        sys.exit(1)
        
    test_selenium_click(live_url)
    test_pw_persistent(live_url)
