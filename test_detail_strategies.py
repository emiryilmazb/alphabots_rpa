import asyncio
from playwright.async_api import async_playwright
import time

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        print('Navigating to vendor...')
        await page.goto('https://home.mobile.de/2PSRL', wait_until='domcontentloaded')
        await asyncio.sleep(2)
        links = await page.eval_on_selector_all('a.link--muted', 'els => els.map(e => e.href)')
        vehicles = list(set([l for l in links if 'details.html' in l]))[:2]
        
        for v in vehicles:
            print('\nTesting:', v)
            
            # Direct URL
            ctx1 = await browser.new_context()
            p1 = await ctx1.new_page()
            start = time.time()
            res = await p1.goto(v, wait_until='domcontentloaded')
            await asyncio.sleep(1)
            t1 = await p1.title()
            s1 = res.status if res else None
            if 'error' in t1.lower() or 'edgesuite' in await p1.content(): s1 = 503
            print(f'direct_url: Status {s1}, {time.time()-start:.2f}s')
            await ctx1.close()
            
            # Same Context
            p2 = await context.new_page()
            start = time.time()
            res = await p2.goto(v, wait_until='domcontentloaded', referer='https://home.mobile.de/2PSRL')
            await asyncio.sleep(1)
            t2 = await p2.title()
            s2 = res.status if res else None
            if 'error' in t2.lower() or 'edgesuite' in await p2.content(): s2 = 503
            print(f'same_context: Status {s2}, {time.time()-start:.2f}s')
            await p2.close()
            
            # Click
            try:
                await page.goto('https://home.mobile.de/2PSRL', wait_until='domcontentloaded')
                await asyncio.sleep(2)
                v_id = v.split('?id=')[-1]
                start = time.time()
                async with context.expect_page(timeout=10000) as p_info:
                    await page.locator(f'a[href*="{v_id}"]').first.click()
                p3 = await p_info.value
                await p3.wait_for_load_state('domcontentloaded')
                await asyncio.sleep(1)
                t3 = await p3.title()
                s3 = 200
                if 'error' in t3.lower() or 'edgesuite' in await p3.content(): s3 = 503
                print(f'click_from_listing: Status {s3}, {time.time()-start:.2f}s')
                await p3.close()
            except Exception as e:
                print('click_from_listing: Failed', e)

        await browser.close()

asyncio.run(main())
