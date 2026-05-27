import sys, time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        print("Navigating to Vendor Page...")
        page.goto("https://home.mobile.de/2PSRL#ses", wait_until="domcontentloaded")
        time.sleep(5)
        
        print(f"Total Frames: {len(page.frames)}")
        for i, frame in enumerate(page.frames):
            print(f"\n--- Frame {i}: {frame.url[:80]} ---")
            try:
                links = frame.evaluate("Array.from(document.querySelectorAll('a')).map(a => { return {href: a.href, text: a.innerText.substring(0, 30)}; })")
                car_links = [l for l in links if 'id=' in l.get('href', '') or 'details' in l.get('href', '') or 'fahrzeuge' in l.get('href', '')]
                print(f"Car Links found: {len(car_links)}")
                if car_links:
                    print(f"Sample Link 1: {car_links[0]}")
                    if len(car_links) > 1:
                        print(f"Sample Link 2: {car_links[1]}")
            except Exception as e:
                print("Cannot read frame:", e)
                
        # Let's also check for article or div.vehicle-card
        try:
            cards = page.evaluate("Array.from(document.querySelectorAll('article, div[class*=\'card\'], div[class*=\'result-item\'])).length")
            print(f"\nFound potential vehicle cards (article/card/result-item): {cards}")
        except:
            pass
            
        browser.close()

if __name__ == "__main__":
    run()
