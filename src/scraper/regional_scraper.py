"""
Regional page scraper.

Crawls the paginated state dealer directory to collect all dealer URLs.
"""

from __future__ import annotations

import logging
from src.config import ScraperConfig
from src.scraper.browser import BrowserManager
from src.scraper.parsers import parse_regional_page, normalize_dealer_url

logger = logging.getLogger("mobile_de.regional")


class RegionalScraper:
    """Scrapes the regional directory pages for a given German state."""

    def __init__(self, browser: BrowserManager, config: ScraperConfig):
        self.browser = browser
        self.config = config

    async def collect_dealer_entries(self) -> list[dict[str, str]]:
        """
        Paginate through all state pages and collect dealer entries.

        Returns:
            Deduplicated list of dealer dicts with keys:
            name, url, street, plz, city
        """
        all_dealers: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        page_num = 0

        while True:
            # Check page limit
            if self.config.max_pages_per_state > 0 and page_num >= self.config.max_pages_per_state:
                logger.info("Page limit reached (%d pages).", self.config.max_pages_per_state)
                break

            url = self.config.state_page_url.format(page=page_num)
            logger.info("Scraping regional page %d: %s", page_num, url)

            success = await self.browser.safe_goto(url)
            if not success:
                logger.warning(
                    "Failed to load regional page %d (%s). Stopping pagination.",
                    page_num,
                    self.browser.last_error or "unknown error",
                )
                break

            # Wait briefly for either rendered dealer links or the empty page state.
            try:
                await self.browser.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.debug("Network idle wait timed out on regional page %d.", page_num)

            html = await self.browser.get_page_html()
            dealers = parse_regional_page(html)

            if not dealers:
                logger.info("No dealers found on page %d. End of pagination.", page_num)
                break

            # Deduplicate
            new_count = 0
            for d in dealers:
                d["url"] = normalize_dealer_url(d.get("url", ""))
                if d["url"] and d["url"] not in seen_urls:
                    seen_urls.add(d["url"])
                    all_dealers.append(d)
                    new_count += 1

            logger.info("Page %d: found %d dealers (%d new, %d total)",
                        page_num, len(dealers), new_count, len(all_dealers))

            if new_count == 0:
                logger.info("No new dealers on page %d. Stopping.", page_num)
                break

            # Check vendor limit
            if self.config.max_vendors > 0 and len(all_dealers) >= self.config.max_vendors:
                all_dealers = all_dealers[:self.config.max_vendors]
                logger.info("Vendor limit reached (%d vendors).", self.config.max_vendors)
                break

            page_num += 1
            await self.browser.polite_delay()

        logger.info("Regional scraping complete: %d unique dealers collected.", len(all_dealers))
        return all_dealers
