import argparse, time, os, json, re, sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

OUT_DIR_BASE = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_observer"
FALLBACK_DETAIL_URL = "https://suchen.mobile.de/fahrzeuge/details.html?id=381986422"

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

def run_pw_strategy(strategy_name, delayed=False, persistent=False, channel="chromium"):
    print(f"\n--- Running: {strategy_name} ---")
    try:
        with sync_playwright() as p:
            args = ["--disable-blink-features=AutomationControlled"]
            if persistent:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=os.path.join(OUT_DIR_BASE, "profile_" + strategy_name),
                    headless=False, channel=channel, args=args,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                ctx = browser
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            else:
                if channel == "chromium":
                    browser = p.chromium.launch(headless=False, args=args)
                else:
                    browser = getattr(p, channel).launch(headless=False, args=args) if channel != "chrome" else p.chromium.launch(headless=False, channel="chrome", args=args)
                ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1280, "height": 800})
                page = ctx.new_page()

            print("Warming up on Vendor page...")
            page.goto("https://home.mobile.de/2PSRL#ses", wait_until="domcontentloaded")
            time.sleep(3)
            try: 
                page.locator("button:has-text('Akzeptieren')").first.click(timeout=2000)
                time.sleep(1)
            except: pass

            # Lazy load scroll
            print("Scrolling down to load links...")
            for _ in range(3):
                page.mouse.wheel(0, 600)
                time.sleep(1)

            # Find link
            hrefs = page.evaluate("Array.from(document.querySelectorAll('a')).map(a => a.href)")
            target_url = None
            for h in hrefs:
                if ("details.html" in h or "id=" in h) and "home.mobile.de" not in h:
                    target_url = h
                    break

            if delayed:
                print("Hover delay simulation...")
                time.sleep(3)

            if target_url:
                print(f"Found actual vehicle link: {target_url}")
            else:
                print(f"No vehicle link found. Using fallback: {FALLBACK_DETAIL_URL}")
                target_url = FALLBACK_DETAIL_URL

            print("Opening target in a NEW TAB (simulating click target=_blank)...")
            try:
                with ctx.expect_page(timeout=10000) as new_page_info:
                    # JavaScript kullanarak click / window.open tetikle
                    page.evaluate(f"window.open('{target_url}', '_blank');")
                new_page = new_page_info.value
                print("New tab captured! Waiting for load...")
                new_page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception as e:
                print("Error capturing new tab:", e)
                
            print("Pausing for 15 seconds for visual observation...")
            time.sleep(15)
            dump_pages(ctx, strategy_name)
            browser.close()
    except Exception as e:
        print(f"{strategy_name} Error:", e)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=str, required=True)
    args = parser.parse_args()
    
    if args.run == "pw_click_popup":
        run_pw_strategy("pw_click_popup", delayed=False, persistent=False)
    elif args.run == "pw_delayed_click":
        run_pw_strategy("pw_delayed_click", delayed=True, persistent=False)
    elif args.run == "pw_persistent_click":
        run_pw_strategy("pw_persistent_click", delayed=False, persistent=True)
    elif args.run == "pw_chrome_stable":
        run_pw_strategy("pw_chrome_stable", delayed=False, persistent=False, channel="chrome")
