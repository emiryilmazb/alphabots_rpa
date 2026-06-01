"""Fetch strategy manager with conservative static validation."""

from __future__ import annotations

import logging
from collections.abc import Callable

from src.config import ScraperConfig
from src.scraper.browser import BrowserManager
from src.scraper.fetchers.base import FetchResult, StaticValidation
from src.scraper.fetchers.curl_fetcher import CurlFetcher
from src.scraper.fetchers.playwright_fetcher import PlaywrightFetcher

logger = logging.getLogger("mobile_de.fetchers.strategy")

Validator = Callable[[FetchResult], StaticValidation]


class FetchStrategyManager:
    """Select curl_cffi or Playwright according to config and validation."""

    def __init__(
        self,
        config: ScraperConfig,
        browser: BrowserManager | None = None,
        *,
        curl_fetcher: CurlFetcher | None = None,
        playwright_fetcher: PlaywrightFetcher | None = None,
    ):
        self.config = config
        self.browser = browser
        self.curl_fetcher = curl_fetcher or CurlFetcher(config)
        if playwright_fetcher is not None:
            self.playwright_fetcher = playwright_fetcher
        elif browser is not None:
            self.playwright_fetcher = PlaywrightFetcher(config, browser)
        else:
            self.playwright_fetcher = None

    async def fetch(
        self,
        url: str,
        *,
        validator: Validator | None = None,
        allow_curl: bool = True,
        playwright_max_retries: int | None = None,
    ) -> FetchResult:
        strategy = self.config.fetch_strategy
        if strategy == "playwright" or not allow_curl:
            return await self._fetch_playwright(
                url,
                fallback_reason="",
                max_retries=playwright_max_retries,
            )

        if strategy in {"auto", "curl"}:
            curl_result = await self.curl_fetcher.fetch(url, attempt=1)
            validation = self._validate(curl_result, validator)
            if validation.ok or strategy == "curl":
                if not validation.ok:
                    curl_result.fallback_reason = validation.reason
                return curl_result

            if curl_result.error_type != "ModuleNotFoundError":
                logger.info(
                    "Static fetch was not sufficient for %s (%s); using Playwright.",
                    url,
                    validation.reason,
                )
            return await self._fetch_playwright(
                url,
                fallback_reason=validation.reason,
                max_retries=playwright_max_retries,
            )

        return await self._fetch_playwright(
            url, fallback_reason="", max_retries=playwright_max_retries
        )

    async def _fetch_playwright(
        self,
        url: str,
        *,
        fallback_reason: str,
        max_retries: int | None = None,
    ) -> FetchResult:
        if self.playwright_fetcher is None:
            return FetchResult(
                url=url,
                strategy="playwright_unavailable",
                error_type="playwright_unavailable",
                error_message="Playwright fetcher is not configured.",
                fallback_reason=fallback_reason,
            )
        result = await self.playwright_fetcher.fetch(
            url,
            attempt=2 if fallback_reason else 1,
            max_retries=max_retries,
        )
        result.fallback_reason = fallback_reason
        return result

    @classmethod
    def _validate(
        cls,
        result: FetchResult,
        validator: Validator | None,
    ) -> StaticValidation:
        base = cls.validate_static_html(result)
        if not base.ok:
            return base
        if validator is None:
            return base
        return validator(result)

    @staticmethod
    def validate_static_html(result: FetchResult) -> StaticValidation:
        if result.error_type:
            return StaticValidation(False, result.error_message or result.error_type)
        if result.status_code is not None and not 200 <= result.status_code < 400:
            return StaticValidation(False, f"HTTP {result.status_code}")
        html = result.html or ""
        if len(html.strip()) < 200:
            return StaticValidation(False, "static_html_too_short")
        lowered = html.lower()
        blocked_markers = [
            "zugriff verweigert",
            "access denied",
            "captcha",
            "aus sicherheitsgründen",
            "error reference",
        ]
        if any(marker in lowered for marker in blocked_markers):
            return StaticValidation(False, "static_html_blocked_or_challenge")
        dynamic_markers = [
            "enable javascript",
            "please enable javascript",
            "javascript is disabled",
        ]
        if any(marker in lowered for marker in dynamic_markers):
            return StaticValidation(False, "static_html_requires_browser")
        return StaticValidation(True)
