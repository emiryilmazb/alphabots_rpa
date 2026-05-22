"""Playwright browser lifecycle, consent handling, retries, and rate limiting."""

from __future__ import annotations

import asyncio
import random
import logging
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from src.config import ScraperConfig

logger = logging.getLogger("mobile_de.browser")


class BrowserManager:
    """Manages a Playwright browser instance for polite, resumable scraping."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.last_status: int | None = None
        self.last_error: str = ""

    async def start(self) -> Page:
        """Launch browser and return the main page."""
        logger.info("Starting Playwright browser (headless=%s).", self.config.headless)

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
            args=[
                "--no-sandbox",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="de-DE",
            timezone_id="Europe/Berlin",
            java_script_enabled=True,
        )

        self._page = await self._context.new_page()
        logger.info("Browser started successfully.")
        return self._page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    async def accept_cookies(self) -> None:
        """Accept the cookie consent modal if it appears."""
        selectors = [
            "button.mde-consent-accept-btn",
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Akzeptieren')",
            "button:has-text('Einverstanden')",
            "button:has-text('Zustimmen')",
        ]
        for selector in selectors:
            try:
                button = self.page.locator(selector)
                if await button.count() > 0:
                    await button.first.click(timeout=5000)
                    logger.info("Cookie consent accepted via selector: %s", selector)
                    await asyncio.sleep(1)
                    return
            except Exception as e:
                logger.debug("Cookie consent selector failed (%s): %s", selector, e)

    async def polite_delay(self) -> None:
        """Wait a random duration to be polite to the server."""
        delay = random.uniform(self.config.min_delay, self.config.max_delay)
        logger.debug("Polite delay: %.1fs", delay)
        await asyncio.sleep(delay)

    async def safe_goto(self, url: str, timeout: int = 45000) -> bool:
        """
        Navigate to URL with error handling.

        Returns True on success, False on failure.
        """
        self.last_status = None
        self.last_error = ""

        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = await self.page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout,
                )
                self.last_status = response.status if response else None
                if response and response.status >= 400:
                    body_text = await self._safe_body_text()
                    self.last_error = f"HTTP {response.status}"
                    if self._looks_blocked(body_text):
                        self.last_error = f"HTTP {response.status}: access denied by site protection"
                    logger.warning("%s for %s", self.last_error, url)
                    if response.status in {429, 500, 502, 503, 504} and attempt < self.config.max_retries:
                        await asyncio.sleep(self.config.retry_delay * attempt)
                        continue
                    return False

                await self.accept_cookies()
                body_text = await self._safe_body_text()
                if self._looks_blocked(body_text):
                    self.last_error = "Access denied by site protection"
                    logger.warning("%s for %s", self.last_error, url)
                    return False
                return True
            except Exception as e:
                self.last_error = str(e)
                logger.warning(
                    "Navigation attempt %d/%d failed for %s: %s",
                    attempt,
                    self.config.max_retries,
                    url,
                    e,
                )
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay * attempt)

        return False

    async def _safe_body_text(self) -> str:
        try:
            return await self.page.locator("body").inner_text(timeout=5000)
        except Exception:
            return ""

    @staticmethod
    def _looks_blocked(text: str) -> bool:
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in [
                "zugriff verweigert",
                "access denied",
                "captcha",
                "aus sicherheitsgründen",
                "error reference",
            ]
        )

    async def get_page_html(self) -> str:
        """Return the current page's HTML content."""
        return await self.page.content()

    async def close(self) -> None:
        """Shut down browser and Playwright."""
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
            logger.info("Browser closed.")
        except Exception as e:
            logger.warning("Error closing browser: %s", e)
