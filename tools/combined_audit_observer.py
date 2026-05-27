import os, re, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

base_dir = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs"
labs = ["detail_lab", "detail_lab_2", "detail_lab_3", "detail_lab_4", "detail_lab_5", "detail_lab_6", "detail_lab_7"]

print("=== 1. EXISTING ARTIFACT AUDIT ===")
print(f"{'FILE':<30} | {'SIZE':<8} | {'ERR/DENY':<10} | {'REAL_DETAIL':<12} | {'CLASS':<15}")

for lab in labs:
    path = os.path.join(base_dir, lab)
    if not os.path.exists(path): continue
    for root, dirs, files in os.walk(path):
        for f in files:
            if f.endswith('.html'):
                fp = os.path.join(root, f)
                with open(fp, 'r', encoding='utf-8', errors='ignore') as file:
                    html = file.read()
                    
                html_lower = html.lower()
                size = len(html)
                title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I)
                title = title_m.group(1).strip() if title_m else 'No Title'
                
                edgesuite = "edgesuite.net" in html_lower
                denied = "zugriff verweigert" in html_lower or "access denied" in html_lower
                vehicle_title = "fahrzeugbeschreibung" in html_lower or "kategorie" in html_lower or "technische daten" in html_lower
                baureihe = "baureihe" in html_lower
                
                classification = "unknown"
                if denied or edgesuite: classification = "error_page"
                elif size < 500: classification = "blank_page"
                elif "gebrauchtwagen und neuwagen" in title.lower(): classification = "listing_page"
                elif vehicle_title or baureihe: classification = "real_detail_page"
                
                err_deny = f"{edgesuite}/{denied}"
                print(f"{f[:30]:<30} | {size:<8} | {err_deny:<10} | {str(vehicle_title):<12} | {classification:<15}")

print("\n=== 3. LIVE OBSERVER MODE (POPUP CATCHING) ===")
OUT_DIR = r"F:\kod\alphabots_rpa\mobile_de_scraper\data\runs\detail_observer_v3"
os.makedirs(OUT_DIR, exist_ok=True)

from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = ctx.new_page()
        
        print("Navigating to vendor page...")
        page.goto("https://home.mobile.de/2PSRL#ses", wait_until="domcontentloaded")
        time.sleep(5)
        
        try:
            page.locator("button:has-text('Akzeptieren')").first.click(timeout=2000)
            time.sleep(1)
        except: pass
        
        print("Scrolling to load elements...")
        page.evaluate("window.scrollBy(0, 1000);")
        time.sleep(2)
        
        print("Attempting to find and click a vehicle link (forcing new tab target=_blank)...")
        page.evaluate('''() => {
            let links = Array.from(document.querySelectorAll('a'));
            let target = links.find(a => a.href.includes('details.html') || a.href.includes('/fahrzeuge/'));
            if (target) {
                target.target = '_blank';
                target.click();
            }
        }''')
        
        print("Pausing for 20 seconds for visual confirmation AND page load...")
        time.sleep(20)
        
        print(f"Total open tabs: {len(ctx.pages)}")
        for i, p in enumerate(ctx.pages):
            html = p.content()
            url = p.url
            title = p.title()
            print(f"\n--- Tab {i} ---")
            print(f"URL: {url}")
            print(f"Title: {title}")
            print(f"Size: {len(html)}")
            
            with open(os.path.join(OUT_DIR, f"tab_{i}.html"), "w", encoding="utf-8") as f:
                f.write(html)
            try:
                p.screenshot(path=os.path.join(OUT_DIR, f"tab_{i}.png"), full_page=True)
            except: pass
            
            html_lower = html.lower()
            if "fahrzeugbeschreibung" in html_lower or ("co2" in html_lower and "baureihe" in html_lower):
                print(f"!!! SUCCESS: TAB {i} IS A REAL DETAIL PAGE !!!")
                
        browser.close()
except Exception as e:
    print("Observer error:", e)
