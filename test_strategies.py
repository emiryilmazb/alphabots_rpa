
import asyncio
from playwright.async_api import async_playwright

async def test_strategies():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        
        # STRATEGY 1: DIRECT URL
        print("--- DIRECT URL STRATEGY ---")
        page1 = await context.new_page()
        resp1 = await page1.goto("https://suchen.mobile.de/fahrzeuge/details.html?id=452636100", wait_until="domcontentloaded")
        content1 = await page1.content()
        print(f"Direct HTTP Status: {resp1.status}")
        print(f"Edgesuite/Error in page: {'errors.edgesuite.net' in content1 or 'error occurred' in content1}")
        await page1.close()

        # STRATEGY 2: SAME CONTEXT CLICK
        print("--- CLICK FROM VENDOR STRATEGY ---")
        page2 = await context.new_page()
        resp2 = await page2.goto("https://home.mobile.de/2PSRL", wait_until="domcontentloaded")
        print(f"Vendor HTTP Status: {resp2.status if resp2 else 'None'}")
        await asyncio.sleep(2)
        
        # Attempt to find a vehicle link and click it
        links = await page2.locator('a[href*="/fahrzeuge/details"]').all()
        if links:
            print(f"Found {len(links)} vehicle links. Clicking the first one...")
            async with page2.expect_navigation(wait_until="domcontentloaded") as nav_info:
                await links[0].click()
            resp_click = await nav_info.value
            content2 = await page2.content()
            print(f"Click HTTP Status: {resp_click.status if resp_click else 'None'}")
            print(f"Edgesuite/Error in page: {'errors.edgesuite.net' in content2 or 'error occurred' in content2}")
        else:
            print("No vehicle links found to click.")
        await page2.close()
        await browser.close()

asyncio.run(test_strategies())
