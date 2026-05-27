import argparse, time, os, json, re, sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

OUT_DIR_BASE = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_observer"

def classify_page(html, title, url):
    html_lower = html.lower()
    if "zugriff verweigert" in html_lower or "access denied" in html_lower or "edgesuite.net" in html_lower:
        return "error_page"
    if "px-captcha" in html_lower or "perimeterx" in html_lower:
        return "captcha_page"
    if "fahrzeugbeschreibung" in html_lower or ("co2" in html_lower and "baureihe" in html_lower):
        return "real_detail_page"
    if "kraftstoffverbrauch" in html_lower or "ausstattung" in html_lower:
        return "real_detail_page"
    if "gebrauchtwagen und neuwagen" in title.lower() or "home.mobile.de" in url:
        return "listing_page"
    if len(html) < 500:
        return "blank_page"
    return "unknown"

def dump_pages(ctx, strategy_name):
    out_dir = os.path.join(OUT_DIR_BASE, strategy_name)
    os.makedirs(out_dir, exist_ok=True)
    pages = ctx.pages
    print(f"\nTotal open pages/tabs: {len(pages)}")
    results = []
    for i, p in enumerate(pages):
        try:
            url = p.url
            title = p.title()
            html = p.content()
            cls = classify_page(html, title, url)
            
            file_prefix = os.path.join(out_dir, f"page_{i}_{cls}")
            with open(file_prefix + ".html", "w", encoding="utf-8") as f:
                f.write(html)
            try:
                p.screenshot(path=file_prefix + ".png", full_page=True)
            except: pass
            
            html_lower = html.lower()
            res = {
                "index": i,
                "url": url,
                "title": title,
                "classification": cls,
                "html_size": len(html),
                "contains_co2": bool(re.search(r'co2|emission', html_lower, re.I)),
                "contains_baureihe": bool(re.search(r'baureihe', html_lower, re.I))
            }
            results.append(res)
            print(f"-> Tab {i}: {cls} | {title[:50]} | {url[:80]}")
        except Exception as e:
            print(f"Error dumping tab {i}: {e}")
            
    with open(os.path.join(out_dir, "observer_result.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

def run_pw_click(strategy_name, delayed=False, persistent=False, channel="chromium"):
    print(f"\n--- Running: {strategy_name} ---")
    try:
        with sync_playwright() as p:
            args = ["--disable-blink-features=AutomationControlled"]
            if persistent:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=os.path.join(OUT_DIR_BASE, "profile_" + strategy_name),
                    headless=False, channel=channel, args=args,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                ctx = browser
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            else:
                if channel == "chromium":
                    browser = p.chromium.launch(headless=False, args=args)
                else:
                    browser = getattr(p, channel).launch(headless=False, args=args) if channel != "chrome" else p.chromium.launch(headless=False, channel="chrome", args=args)
                ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
                page = ctx.new_page()

            page.goto("https://home.mobile.de/2PSRL#ses", wait_until="domcontentloaded")
            time.sleep(3)
            try: 
                page.locator("button:has-text('Akzeptieren')").first.click(timeout=2000)
                time.sleep(1)
            except: pass

            # More robust link finding
            links = page.locator("a").element_handles()
            target_loc = None
            for link in links:
                href = link.get_attribute("href") or ""
                if "details.html" in href or "/fahrzeuge/" in href:
                    target_loc = link
                    break
            
            if target_loc:
                try: target_loc.scroll_into_view_if_needed()
                except: pass
                time.sleep(1)

                if delayed:
                    print("Hovering for 2 seconds...")
                    try: target_loc.hover()
                    except: pass
                    time.sleep(2)

                print("Clicking link (forcing new tab)...")
                try:
                    with ctx.expect_page(timeout=10000) as new_page_info:
                        target_loc.click(modifiers=["Control"])
                    new_page = new_page_info.value
                    print("New tab detected!")
                    new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception as e:
                    print("New tab capture failed, trying normal click:", e)
                    try: target_loc.click()
                    except: pass
            else:
                print("No vehicle link found!")

            print("Pausing for 12 seconds for visual observation...")
            time.sleep(12)
            dump_pages(ctx, strategy_name)
            browser.close()
    except Exception as e:
        print(f"{strategy_name} Error:", e)

def run_selenium_click():
    print("\n--- Running: selenium_click ---")
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        options = uc.ChromeOptions()
        options.add_argument("--disable-popup-blocking")
        driver = uc.Chrome(version_main=148, options=options)
        
        driver.get("https://home.mobile.de/2PSRL#ses")
        time.sleep(4)
        
        try:
            btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Akzeptieren')]")
            if btn: btn.click()
        except: pass
        time.sleep(1)
        
        links = driver.find_elements(By.TAG_NAME, "a")
        target = None
        for l in links:
            href = l.get_attribute("href") or ""
            if "details.html" in href or "/fahrzeuge/" in href:
                target = l
                break
        
        if target:
            driver.execute_script("arguments[0].scrollIntoView(true);", target)
            time.sleep(1)
            try:
                driver.execute_script("window.open(arguments[0].href, '_blank');", target)
                print("Opened link in new tab via JS.")
            except:
                target.click()
            
            print("Pausing for 12 seconds for visual observation...")
            time.sleep(12)
        else:
            print("No detail link found.")
            
        out_dir = os.path.join(OUT_DIR_BASE, "selenium_click")
        os.makedirs(out_dir, exist_ok=True)
        results = []
        
        handles = driver.window_handles
        print(f"\nTotal open tabs: {len(handles)}")
        for i, h in enumerate(handles):
            driver.switch_to.window(h)
            url = driver.current_url
            title = driver.title
            html = driver.page_source
            cls = classify_page(html, title, url)
            
            prefix = os.path.join(out_dir, f"page_{i}_{cls}")
            with open(prefix + ".html", "w", encoding="utf-8") as f: f.write(html)
            driver.save_screenshot(prefix + ".png")
            
            results.append({"index": i, "url": url, "title": title, "classification": cls, "html_size": len(html)})
            print(f"-> Tab {i}: {cls} | {title[:50]} | {url[:80]}")
            
        with open(os.path.join(out_dir, "observer_result.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
            
        driver.quit()
    except Exception as e:
        print("Selenium error:", e)

if __name__ == '__main__':
    run_pw_click("pw_click_popup", delayed=False, persistent=False)
    run_pw_click("pw_delayed_click", delayed=True, persistent=False)
    run_pw_click("pw_persistent_click", delayed=False, persistent=True)
    run_pw_click("pw_chrome_stable", delayed=False, persistent=False, channel="chrome")
    run_selenium_click()
