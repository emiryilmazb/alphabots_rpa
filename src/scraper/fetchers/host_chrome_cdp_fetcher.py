"""Fetch detail pages through an existing user-launched Chrome CDP session."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import async_playwright

from src.config import ScraperConfig
from src.scraper.detail_page import classify_detail_page
from src.scraper.fetchers.base import FetchResult

logger = logging.getLogger("mobile_de.fetchers.host_chrome_cdp")


class HostChromeCdpFetcher:
    """Connect to an already-running Chrome remote-debugging endpoint."""

    strategy_name = "host-chrome-cdp"

    def __init__(self, config: ScraperConfig, *, cdp_url: str | None = None):
        self.config = config
        self.cdp_url = cdp_url or config.chrome_cdp_url
        self._playwright_cm: Any = None
        self._playwright: Any = None
        self._browser: Any = None

    async def fetch(self, url: str, *, attempt: int = 1) -> FetchResult:
        """Read rendered HTML from a normal host Chrome session via CDP."""
        started = perf_counter()
        self._increment("host_chrome_cdp_used_count")
        created_page = False
        page: Any = None
        response: Any = None
        fetch_url = self._with_german_language(url)
        try:
            await self._ensure_connected()
            context = await self._get_context()
            page = self._find_open_page(context, fetch_url)
            if page is None:
                page = await context.new_page()
                created_page = True
                response = await page.goto(fetch_url, wait_until="domcontentloaded", timeout=60000)
            elif page.url != fetch_url:
                response = await page.goto(fetch_url, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                logger.debug("Host Chrome CDP networkidle wait timed out for %s.", url)
            await page.wait_for_timeout(1500)
            await self._expand_detail_sections(page)

            title = await page.title()
            html = await page.content()
            final_url = page.url
            status_code = response.status if response is not None else None
            classification = classify_detail_page(html, url=final_url, title=title)
            elapsed = (perf_counter() - started) * 1000

            failure_type = self._failure_type(classification.classification)
            if failure_type:
                self._increment("host_chrome_cdp_failed_count")
                if classification.classification == "error_page":
                    self._increment("host_chrome_cdp_blocked_count")
                return FetchResult(
                    url=url,
                    final_url=final_url,
                    status_code=status_code,
                    html=html,
                    strategy=self.strategy_name,
                    browser="host_chrome",
                    attempt=attempt,
                    elapsed_ms=elapsed,
                    error_type=failure_type,
                    error_message=classification.reason or classification.classification,
                    classification=classification.classification,
                    detail_status=classification.classification,
                    failure_reason=classification.reason,
                )

            self._increment("host_chrome_cdp_success_count")
            return FetchResult(
                url=url,
                final_url=final_url,
                status_code=status_code,
                html=html,
                strategy=self.strategy_name,
                browser="host_chrome",
                attempt=attempt,
                elapsed_ms=elapsed,
                classification=classification.classification,
                detail_status=classification.classification,
            )
        except Exception as exc:
            self._increment("host_chrome_cdp_failed_count")
            return FetchResult(
                url=url,
                strategy=self.strategy_name,
                browser="host_chrome",
                attempt=attempt,
                elapsed_ms=(perf_counter() - started) * 1000,
                error_type=exc.__class__.__name__,
                error_message=f"Host Chrome CDP fetch failed at {self.cdp_url}: {exc}",
                detail_status="host_chrome_cdp_failed",
                failure_reason=str(exc),
            )
        finally:
            if created_page and page is not None:
                try:
                    await page.close()
                except Exception:
                    logger.debug("Could not close host Chrome CDP tab created for %s.", url, exc_info=True)

    async def close(self) -> None:
        """Release Playwright transport without closing the user's Chrome window."""
        self._browser = None
        if self._playwright_cm is not None:
            try:
                await self._playwright_cm.__aexit__(None, None, None)
            except Exception:
                logger.debug("Could not stop host Chrome CDP Playwright transport.", exc_info=True)
        self._playwright_cm = None
        self._playwright = None

    async def _ensure_connected(self) -> None:
        if self._browser is not None and self._browser.is_connected():
            return
        if self._playwright is None:
            self._playwright_cm = async_playwright()
            self._playwright = await self._playwright_cm.__aenter__()
        self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)

    async def _get_context(self) -> Any:
        if self._browser.contexts:
            return self._browser.contexts[0]
        return await self._browser.new_context()

    @staticmethod
    def _find_open_page(context: Any, url: str) -> Any:
        for page in context.pages:
            if page.url == url:
                return page
        return None

    @staticmethod
    def _with_german_language(url: str) -> str:
        parsed = urlparse(url)
        if "mobile.de" not in parsed.netloc:
            return url
        lowered_path = parsed.path.lower()
        if "/fahrzeuge/details" not in lowered_path and "/auto-inserat/" not in lowered_path:
            return url
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["lang"] = "de"
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query),
                parsed.fragment,
            )
        )

    @staticmethod
    def _failure_type(classification: str) -> str:
        if classification == "error_page":
            return "host_chrome_cdp_blocked_or_challenge"
        if classification in {"home_redirect", "listing_page", "blank_page"}:
            return "host_chrome_cdp_not_detail_page"
        return ""

    async def _expand_detail_sections(self, page: Any) -> None:
        selectors = [
            "button:has-text('Mehr anzeigen')",
            "a:has-text('Mehr anzeigen')",
            "button:has-text('Alle technischen Daten')",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = min(await locator.count(), 3)
            except Exception:
                continue
            for index in range(count):
                try:
                    await locator.nth(index).click(timeout=3000)
                    await page.wait_for_timeout(500)
                except Exception:
                    continue

    def _increment(self, name: str, amount: int = 1) -> None:
        current = getattr(self.config, name, 0) or 0
        setattr(self.config, name, int(current) + amount)
