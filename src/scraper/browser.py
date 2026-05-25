"""Playwright browser lifecycle, consent handling, retries, and rate limiting."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
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

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


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
        self.last_screenshot_path: str = ""
        self.last_html_dump_path: str = ""

    async def start(self) -> Page:
        """Launch browser and return the main page."""
        headless = self.config.browser_mode == "headless" or self.config.headless
        logger.info(
            "Starting Playwright browser=%s mode=%s headless=%s.",
            self.config.browser,
            self.config.browser_mode,
            headless,
        )
        if self.config.browser_mode == "xvfb" and not os.getenv("DISPLAY"):
            logger.warning(
                "browser-mode=xvfb selected but DISPLAY is not set. "
                "Use the Docker entrypoint or run the command under xvfb-run."
            )

        self._pw = await async_playwright().start()
        browser_type = self._browser_type()
        launch_kwargs = self._launch_kwargs(headless)
        context_kwargs = self._context_kwargs()
        if self.config.user_data_dir is not None:
            self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
            self._context = await browser_type.launch_persistent_context(
                str(self.config.user_data_dir),
                **launch_kwargs,
                slow_mo=self.config.slow_mo,
                **context_kwargs,
            )
            self._browser = self._context.browser
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            self._browser = await browser_type.launch(
                **launch_kwargs,
                slow_mo=self.config.slow_mo,
            )
            if self.config.storage_state is not None and self.config.storage_state.exists():
                context_kwargs["storage_state"] = str(self.config.storage_state)
            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()

        logger.info("Browser started successfully.")
        return self._page

    def _context_kwargs(self) -> dict:
        """Return browser context settings shared by normal and persistent contexts."""
        return {
            "viewport": {"width": 1920, "height": 1080},
            "screen": {"width": 1920, "height": 1080},
            "locale": "de-DE",
            "timezone_id": "Europe/Berlin",
            "user_agent": DEFAULT_USER_AGENT,
            "extra_http_headers": {
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            "java_script_enabled": True,
        }

    def _browser_type(self):
        if self._pw is None:
            raise RuntimeError("Playwright not started.")
        if self.config.browser == "firefox":
            return self._pw.firefox
        return self._pw.chromium

    def _launch_kwargs(self, headless: bool) -> dict:
        kwargs: dict = {"headless": headless}
        if self.config.browser == "chrome":
            kwargs["channel"] = "chrome"
        if self.config.browser in {"chromium", "chrome"}:
            kwargs["args"] = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
            ]
        return kwargs

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
        self.last_screenshot_path = ""
        self.last_html_dump_path = ""

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
                    await self._save_debug_artifacts(url, f"http-{response.status}-attempt-{attempt}")
                    if response.status in {429, 500, 502, 503, 504} and attempt < self.config.max_retries:
                        await asyncio.sleep(self.config.retry_delay * attempt)
                        continue
                    return False

                await self.accept_cookies()
                body_text = await self._safe_body_text()
                if self._looks_blocked(body_text):
                    self.last_error = "Access denied by site protection"
                    logger.warning("%s for %s", self.last_error, url)
                    await self._save_debug_artifacts(url, f"blocked-attempt-{attempt}")
                    return False
                return True
            except Exception as e:
                self.last_error = str(e)
                await self._save_debug_artifacts(url, f"exception-attempt-{attempt}")
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

    async def _save_debug_artifacts(self, url: str, reason: str) -> None:
        """Save current page HTML and screenshot for failed navigations."""
        if not (self.config.debug or self.config.save_debug_artifacts):
            return
        if self._page is None:
            return

        html_dir = self.config.debug_dir / "html"
        screenshot_dir = self.config.debug_dir / "screenshots"
        html_dir.mkdir(parents=True, exist_ok=True)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        run_id = self.config.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = f"{run_id}_{self._artifact_base_name(url, reason)}"

        html_path = html_dir / f"{base}.html"
        screenshot_path = screenshot_dir / f"{base}.png"

        try:
            html_path.write_text(await self._page.content(), encoding="utf-8")
            self.last_html_dump_path = str(html_path)
        except Exception as exc:
            logger.debug("Could not save debug HTML for %s: %s", url, exc)

        try:
            await self._page.screenshot(path=str(screenshot_path), full_page=True)
            self.last_screenshot_path = str(screenshot_path)
        except Exception as exc:
            logger.debug("Could not save debug screenshot for %s: %s", url, exc)

        if self.last_html_dump_path or self.last_screenshot_path:
            logger.info(
                "Saved debug artifacts for %s: html=%s screenshot=%s",
                url,
                self.last_html_dump_path or "-",
                self.last_screenshot_path or "-",
            )

    @staticmethod
    def _artifact_base_name(url: str, reason: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        timestamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
        clean_reason = re.sub(r"[^a-zA-Z0-9_-]+", "-", reason).strip("-")[:48]
        return f"{timestamp}-{clean_reason}-{digest}"

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
            if self._context and self.config.storage_state is not None:
                self.config.storage_state.parent.mkdir(parents=True, exist_ok=True)
                await self._context.storage_state(path=str(self.config.storage_state))
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
