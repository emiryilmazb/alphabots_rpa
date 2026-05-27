import os, time, sys, re, json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

OUT_DIR = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_observer_live_v2"
os.makedirs(OUT_DIR, exist_ok=True)

def test_uc_live():
    print("\n=== RUNNING SELENIUM UC LIVE OBSERVER ===")
    options = uc.ChromeOptions()
    options.add_argument("--disable-popup-blocking")
    driver = uc.Chrome(version_main=148, options=options)
    
    # Use a direct generic search URL which has a higher chance of showing cars immediately
    search_url = "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&isSearchRequest=true&vc=Car"
    print(f"Navigating to search page: {search_url}")
    
    driver.get(search_url)
    time.sleep(8) # Wait for PerimeterX check
    
    try:
        # Try to dismiss cookies
        driver.execute_script("""
            let btns = Array.from(document.querySelectorAll('button'));
            let accept = btns.find(b => b.innerText.includes('Akzeptieren') || b.innerText.includes('Zustimmen'));
            if(accept) accept.click();
        """)
        time.sleep(2)
    except: pass

    print("Scrolling to trigger lazy load...")
    for _ in range(5):
        driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(1)
        
    print("Looking for live vehicle links...")
    live_link = None
    links = driver.find_elements(By.TAG_NAME, "a")
    for l in links:
        try:
            href = l.get_attribute("href")
            if href and "details.html" in href:
                live_link = href
                break
        except: pass
        
    if not live_link:
        print("FATAL: No live link found on search page.")
        driver.quit()
        return
        
    print(f"Found LIVE link: {live_link}")
    print("Opening in NEW TAB (target=_blank simulation)...")
    driver.execute_script(f"window.open('{live_link}', '_blank');")
    time.sleep(2)
    
    driver.switch_to.window(driver.window_handles[-1])
    print("Switched to NEW tab. Waiting 10s for DOM to settle...")
    time.sleep(10)
    
    html = driver.page_source
    title = driver.title
    url = driver.current_url
    
    html_lower = html.lower()
    is_blocked = "zugriff verweigert" in html_lower or "edgesuite" in html_lower or "px-captcha" in html_lower
    is_real = "fahrzeugbeschreibung" in html_lower or "technische daten" in html_lower
    
    extracted = {
        "co2": bool(re.search(r'co2|emission', html_lower, re.I)),
        "baureihe": bool(re.search(r'baureihe', html_lower, re.I)),
        "ausstattungslinie": bool(re.search(r'ausstattungslinie', html_lower, re.I)),
        "pvo": bool(re.search(r'fahrzeughalter', html_lower, re.I))
    }
    
    print(f"\n--- RESULTS ---")
    print(f"URL: {url}")
    print(f"Title: {title}")
    print(f"Blocked by PerimeterX: {is_blocked}")
    print(f"Real Detail Layout: {is_real}")
    print(f"Extracted Fields: {extracted}")
    
    with open(os.path.join(OUT_DIR, "uc_live.html"), "w", encoding="utf-8") as f:
        f.write(html)
    driver.save_screenshot(os.path.join(OUT_DIR, "uc_live.png"))
    
    print("\nPAUSING 15 SECONDS FOR VISUAL OBSERVATION...")
    time.sleep(15)
    driver.quit()

if __name__ == '__main__':
    test_uc_live()
