"""Playwright browser lifecycle, consent handling, retries, and rate limiting."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import re
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

try:
    from playwright._impl._errors import TargetClosedError
except Exception:  # pragma: no cover - compatibility fallback for Playwright internals
    TargetClosedError = None  # type: ignore[assignment]

TARGET_CLOSED_ERROR_TYPES = (
    (TargetClosedError,) if TargetClosedError is not None else ()
)


def _is_target_closed_error(exc: Exception) -> bool:
    """Check if an exception indicates the page/context/browser was closed."""
    if TARGET_CLOSED_ERROR_TYPES and isinstance(exc, TARGET_CLOSED_ERROR_TYPES):
        return True
    if type(exc).__name__ == "TargetClosedError":
        return True
    msg = str(exc).lower()
    return (
        "target page, context or browser has been closed" in msg
        or "target closed" in msg
    )


from src.config import ScraperConfig

logger = logging.getLogger("mobile_de.browser")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

COOKIE_ACCEPT_BUTTON_SELECTORS = [
    "button.mde-consent-accept-btn",
    "button:has-text('Einverstanden')",
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Akzeptieren')",
    "button:has-text('Zustimmen')",
]

COOKIE_MODAL_SELECTORS = [
    "[role='dialog']:has-text('Einverstanden')",
    "[role='dialog']:has-text('Cookie')",
    "[class*='consent']:has-text('Einverstanden')",
    "[class*='Consent']:has-text('Einverstanden')",
]


class BrowserManager:
    """Manages a Playwright browser instance for polite, resumable scraping."""

    def __init__(self, config: ScraperConfig, *, role: str = "generic"):
        self.config = config
        self.role = role
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._counted_open: bool = False
        self._cookies_accepted: bool = False
        self._consent_checked: bool = False
        self._healthy: bool = False
        self.last_status: int | None = None
        self.last_error: str = ""
        self.last_screenshot_path: str = ""
        self.last_html_dump_path: str = ""

    async def start(self) -> Page:
        """Launch browser and return the main page."""
        if self._page is not None and self._healthy:
            return self._page
        if (
            self._page is not None
            or self._context is not None
            or self._browser is not None
            or self._pw is not None
        ):
            await self.close()

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
            self._page = (
                self._context.pages[0]
                if self._context.pages
                else await self._context.new_page()
            )
        else:
            self._browser = await browser_type.launch(
                **launch_kwargs,
                slow_mo=self.config.slow_mo,
            )
            if (
                self.config.storage_state is not None
                and self.config.storage_state.exists()
            ):
                if getattr(self.config, "use_storage_state", False):
                    context_kwargs["storage_state"] = str(self.config.storage_state)
                    logger.info(
                        "Loaded storage state from %s", self.config.storage_state
                    )
            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()

        self._healthy = True
        self._cookies_accepted = False
        self._consent_checked = False
        self._record_browser_opened()
        logger.info("Browser started successfully.")
        return self._page

    @property
    def is_healthy(self) -> bool:
        return self._healthy and self._page is not None

    @property
    def has_open_browser(self) -> bool:
        return any(
            resource is not None
            for resource in (self._page, self._context, self._browser, self._pw)
        )

    def mark_unhealthy(self, reason: str = "") -> None:
        self._healthy = False
        if reason:
            self.last_error = reason

    async def ensure_started(self) -> Page:
        if not self.is_healthy:
            await self.close()
            return await self.start()
        return self.page

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
        if self._page is None:
            return

        visible_button = None
        modal_visible = False
        for _ in range(10):
            visible_button = await self._first_visible_locator(
                COOKIE_ACCEPT_BUTTON_SELECTORS
            )
            modal_visible = (
                visible_button is not None
                or await self._cookie_modal_container_visible()
            )
            if visible_button is not None or not modal_visible:
                break
            await self.page.wait_for_timeout(500)
        if not modal_visible:
            self._consent_checked = True
            return

        self._increment_config_counter("cookie_modal_visible_count")
        logger.info("Cookie modal visible; accepting")

        if visible_button is None:
            self._increment_config_counter("cookie_modal_remaining_count")
            logger.warning("Cookie modal remaining; no visible accept button found.")
            return

        try:
            await self.page.wait_for_timeout(1000)
            visible_button = await self._first_visible_locator(
                COOKIE_ACCEPT_BUTTON_SELECTORS
            )
            if visible_button is None:
                self._increment_config_counter("cookie_modal_remaining_count")
                logger.warning(
                    "Cookie modal remaining; accept button disappeared before click."
                )
                return
            await visible_button.click(timeout=5000)
            self._increment_config_counter("cookie_consent_click_count")
            await self._wait_for_cookie_modal_to_disappear()
        except Exception as e:
            self._increment_config_counter("cookie_modal_remaining_count")
            logger.debug("Cookie consent click failed: %s", e)
            return

        if await self._cookie_modal_visible():
            await self._retry_cookie_accept_click()
            if await self._cookie_modal_visible():
                self._increment_config_counter("cookie_modal_remaining_count")
                logger.warning("Cookie modal remaining after accept attempt.")
                return

        self._cookies_accepted = True
        self._consent_checked = True
        logger.info("Cookie modal dismissed")
        await self._save_storage_state()

    async def _first_visible_locator(self, selectors: list[str]):
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = await locator.count()
                for index in range(min(count, 5)):
                    candidate = locator.nth(index)
                    if await candidate.is_visible(timeout=1000):
                        return candidate
            except Exception as e:
                logger.debug("Cookie consent selector failed (%s): %s", selector, e)
        return None

    async def _cookie_modal_container_visible(self) -> bool:
        return await self._first_visible_locator(COOKIE_MODAL_SELECTORS) is not None

    async def _cookie_modal_visible(self) -> bool:
        return (
            await self._first_visible_locator(COOKIE_ACCEPT_BUTTON_SELECTORS)
            is not None
            or await self._cookie_modal_container_visible()
        )

    async def _wait_for_cookie_modal_to_disappear(self) -> None:
        for _ in range(12):
            await self.page.wait_for_timeout(500)
            if not await self._cookie_modal_visible():
                return

    async def _retry_cookie_accept_click(self) -> None:
        for selector in COOKIE_ACCEPT_BUTTON_SELECTORS:
            button = await self._first_visible_locator([selector])
            if button is None:
                continue
            for force in [False, True]:
                try:
                    await button.click(timeout=5000, force=force)
                    self._increment_config_counter("cookie_consent_click_count")
                    await self._wait_for_cookie_modal_to_disappear()
                    if not await self._cookie_modal_visible():
                        return
                except Exception as e:
                    logger.debug(
                        "Cookie consent retry failed (%s force=%s): %s",
                        selector,
                        force,
                        e,
                    )

    async def _save_storage_state(self) -> None:
        if not (
            getattr(self.config, "use_storage_state", False)
            and self.config.storage_state is not None
            and self._context is not None
        ):
            return
        try:
            self.config.storage_state.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(self.config.storage_state))
            logger.info("Saved storage state")
        except Exception as ex:
            logger.debug("Failed to save storage state: %s", ex)

    def _increment_config_counter(self, name: str) -> None:
        setattr(self.config, name, int(getattr(self.config, name, 0) or 0) + 1)

    def _record_browser_opened(self) -> None:
        if self._counted_open:
            return
        self._increment_config_counter("playwright_browser_opened_count")
        role_counter = f"{self.role}_browser_opened_count"
        if hasattr(self.config, role_counter):
            self._increment_config_counter(role_counter)
        active = (
            int(getattr(self.config, "active_playwright_browser_count", 0) or 0) + 1
        )
        setattr(self.config, "active_playwright_browser_count", active)
        max_active = max(
            int(getattr(self.config, "max_active_playwright_browser_count", 0) or 0),
            active,
        )
        setattr(self.config, "max_active_playwright_browser_count", max_active)
        self._counted_open = True
        logger.info(
            "Playwright browser opened for role=%s active=%d.", self.role, active
        )

    def _record_browser_closed(self) -> None:
        if not self._counted_open:
            return
        active = max(
            0, int(getattr(self.config, "active_playwright_browser_count", 0) or 0) - 1
        )
        setattr(self.config, "active_playwright_browser_count", active)
        self._counted_open = False
        logger.info(
            "Playwright browser closed for role=%s active=%d.", self.role, active
        )

    def _page_is_about_blank(self) -> bool:
        try:
            return self._page is not None and self._page.url == "about:blank"
        except Exception:
            return False

    async def polite_delay(self) -> None:
        """Wait a random duration to be polite to the server."""
        delay = random.uniform(self.config.min_delay, self.config.max_delay)
        logger.debug("Polite delay: %.1fs", delay)
        await asyncio.sleep(delay)

    async def safe_goto(
        self, url: str, timeout: int = 45000, max_retries: int | None = None
    ) -> bool:
        """
        Navigate to URL with error handling.

        Returns True on success, False on failure.
        """
        self.last_status = None
        self.last_error = ""
        self.last_screenshot_path = ""
        self.last_html_dump_path = ""
        target_closed_recovered = False

        retry_count = max(
            1, int(max_retries if max_retries is not None else self.config.max_retries)
        )
        for attempt in range(1, retry_count + 1):
            try:
                response = await self.page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout,
                )
                self.last_status = response.status if response else None
                await self.accept_cookies()
                if response and response.status >= 400:
                    body_text = await self._safe_body_text()
                    self.last_error = f"HTTP {response.status}"
                    if self._looks_edgesuite_error(body_text):
                        self.last_error = (
                            f"HTTP {response.status}: detail_site_blocked_or_503"
                        )
                    elif self._looks_blocked(body_text):
                        self.last_error = (
                            f"HTTP {response.status}: access denied by site protection"
                        )
                    logger.warning("%s for %s", self.last_error, url)
                    await self._save_debug_artifacts(
                        url, f"http-{response.status}-attempt-{attempt}"
                    )
                    if (
                        response.status in {429, 500, 502, 503, 504}
                        and attempt < retry_count
                    ):
                        await asyncio.sleep(self.config.retry_delay * attempt)
                        continue
                    return False

                body_text = await self._safe_body_text()
                if self._looks_blocked(body_text):
                    self.last_error = "Access denied by site protection"
                    logger.warning("%s for %s", self.last_error, url)
                    await self._save_debug_artifacts(url, f"blocked-attempt-{attempt}")
                    return False
                return True
            except TARGET_CLOSED_ERROR_TYPES as e:
                if not target_closed_recovered:
                    logger.warning(
                        "TargetClosedError on attempt %d for %s; restarting browser and retrying once.",
                        attempt,
                        url,
                    )
                    if await self._recover_from_target_closed(e):
                        target_closed_recovered = True
                        continue
                self.last_error = f"TargetClosedError: {e}"
                self.mark_unhealthy(self.last_error)
                return False
            except Exception as e:
                if _is_target_closed_error(e) and not target_closed_recovered:
                    logger.warning(
                        "TargetClosedError on attempt %d for %s; restarting browser and retrying once.",
                        attempt,
                        url,
                    )
                    if await self._recover_from_target_closed(e):
                        target_closed_recovered = True
                        continue
                    self.last_error = f"TargetClosedError: browser restart failed: {e}"
                    self.mark_unhealthy(self.last_error)
                    return False

                self.last_error = str(e)
                await self._save_debug_artifacts(url, f"exception-attempt-{attempt}")
                logger.warning(
                    "Navigation attempt %d/%d failed for %s: %s",
                    attempt,
                    retry_count,
                    url,
                    e,
                )
                if attempt < retry_count:
                    await asyncio.sleep(self.config.retry_delay * attempt)

        return False

    async def _recover_from_target_closed(self, exc: Exception) -> bool:
        """Restart this manager's browser after a TargetClosedError."""
        self.mark_unhealthy(f"TargetClosedError: {exc}")
        try:
            await self.close()
            await self.start()
            return self._page is not None
        except Exception as exc:
            logger.error("Failed to restart browser after TargetClosedError: %s", exc)
            self.mark_unhealthy(str(exc))
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
        run_id = self.config.run_id or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
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

    @staticmethod
    def _looks_edgesuite_error(text: str) -> bool:
        lowered = text.lower()
        return (
            "an error occurred while processing your request" in lowered
            or "errors.edgesuite.net" in lowered
            or "edgesuite" in lowered
        )

    async def get_page_html(self) -> str:
        """Return the current page's HTML content."""
        return await self.page.content()

    async def close(self) -> None:
        """Shut down browser and Playwright. Each step is independent to prevent leaks."""
        await self._save_storage_state()
        if self._page_is_about_blank():
            self._increment_config_counter("idle_about_blank_count")
            logger.info("Closing idle about:blank page for role=%s.", self.role)

        for resource_name, resource in [
            ("page", self._page),
            ("context", self._context),
            ("browser", self._browser),
        ]:
            try:
                if resource is not None:
                    await resource.close()
            except Exception as e:
                logger.debug("Error closing %s: %s", resource_name, e)

        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception as e:
            logger.debug("Error stopping Playwright: %s", e)

        self._page = None
        self._context = None
        self._browser = None
        self._pw = None
        self._cookies_accepted = False
        self._consent_checked = False
        self._healthy = False
        self._record_browser_closed()
        logger.info("Browser closed.")
