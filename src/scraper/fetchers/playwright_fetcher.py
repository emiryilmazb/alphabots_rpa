"""Playwright-backed page fetcher."""

from __future__ import annotations

from time import perf_counter

from src.config import ScraperConfig
from src.scraper.browser import BrowserManager
from src.scraper.fetchers.base import FetchResult


class PlaywrightFetcher:
    """Fetch rendered page HTML through the existing BrowserManager."""

    def __init__(self, config: ScraperConfig, browser: BrowserManager):
        self.config = config
        self.browser = browser

    async def fetch(self, url: str, *, attempt: int = 1, max_retries: int | None = None) -> FetchResult:
        started = perf_counter()
        await self.browser.ensure_started()
        success = await self.browser.safe_goto(url, max_retries=max_retries)
        elapsed = (perf_counter() - started) * 1000
        html = ""
        if success:
            html = await self.browser.get_page_html()
        return FetchResult(
            url=url,
            final_url=self.browser.page.url if success else url,
            status_code=self.browser.last_status,
            html=html,
            strategy=f"playwright_{self.config.browser}",
            browser=self.config.browser,
            attempt=attempt,
            elapsed_ms=elapsed,
            error_type="" if success else "navigation_failed",
            error_message="" if success else self.browser.last_error,
            screenshot_path=self.browser.last_screenshot_path,
            html_dump_path=self.browser.last_html_dump_path,
        )
