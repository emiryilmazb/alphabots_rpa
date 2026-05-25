"""Tests for curl/Playwright fetch strategy architecture."""

from __future__ import annotations

import asyncio

from src.config import ScraperConfig
from src.scraper.fetchers import (
    CurlFetcher,
    FetchResult,
    FetchStrategyManager,
    PlaywrightFetcher,
    StaticValidation,
)


class FakeResponse:
    def __init__(self, *, status_code=200, text="<html>" + ("x" * 220) + "</html>", url="https://example.test"):
        self.status_code = status_code
        self.text = text
        self.url = url


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        return self.response


class FakeFetcher:
    def __init__(self, result: FetchResult):
        self.result = result
        self.calls = 0

    async def fetch(self, url: str, *, attempt: int = 1) -> FetchResult:
        self.calls += 1
        self.result.attempt = attempt
        return self.result


class FakeBrowserFailure:
    last_status = 503
    last_error = "Service unavailable"
    last_screenshot_path = "debug/page.png"
    last_html_dump_path = "debug/page.html"

    async def safe_goto(self, url: str) -> bool:
        return False


def test_fetch_result_defaults_are_populated():
    result = FetchResult(url="https://example.test", html="<html></html>", strategy="curl_cffi")

    assert result.final_url == "https://example.test"
    assert result.fetched_at
    assert result.ok is True


def test_curl_fetcher_mock_success():
    response = FakeResponse(text="<html><body>" + ("dealer " * 50) + "</body></html>")
    fetcher = CurlFetcher(
        ScraperConfig(fetch_strategy="curl"),
        session_factory=lambda: FakeSession(response),
    )

    result = asyncio.run(fetcher.fetch("https://example.test"))

    assert result.strategy == "curl_cffi"
    assert result.status_code == 200
    assert "dealer" in result.html
    assert result.error_type == ""


def test_curl_fetcher_mock_http_error():
    fetcher = CurlFetcher(
        ScraperConfig(fetch_strategy="curl"),
        session_factory=lambda: FakeSession(FakeResponse(status_code=403, text="blocked")),
    )

    result = asyncio.run(fetcher.fetch("https://example.test"))

    assert result.strategy == "curl_cffi"
    assert result.status_code == 403
    assert result.error_type == "http_error"
    assert result.error_message == "HTTP 403"


def test_strategy_manager_falls_back_when_static_validation_fails():
    curl = FakeFetcher(
        FetchResult(
            url="https://example.test",
            status_code=200,
            html="<html><body>" + ("x" * 220) + "</body></html>",
            strategy="curl_cffi",
        )
    )
    playwright = FakeFetcher(
        FetchResult(
            url="https://example.test",
            status_code=200,
            html="<html><body>rendered</body></html>",
            strategy="playwright_chromium",
            browser="chromium",
        )
    )
    manager = FetchStrategyManager(
        ScraperConfig(fetch_strategy="auto"),
        curl_fetcher=curl,
        playwright_fetcher=playwright,
    )

    result = asyncio.run(
        manager.fetch(
            "https://example.test",
            validator=lambda _result: StaticValidation(False, "missing_required_fields"),
        )
    )

    assert result.strategy == "playwright_chromium"
    assert result.fallback_reason == "missing_required_fields"
    assert curl.calls == 1
    assert playwright.calls == 1
    assert result.attempt == 2


def test_strategy_manager_does_not_fallback_when_static_validation_passes():
    curl = FakeFetcher(
        FetchResult(
            url="https://example.test",
            status_code=200,
            html="<html><body>" + ("static " * 50) + "</body></html>",
            strategy="curl_cffi",
        )
    )
    playwright = FakeFetcher(FetchResult(url="https://example.test", strategy="playwright_chromium"))
    manager = FetchStrategyManager(
        ScraperConfig(fetch_strategy="auto"),
        curl_fetcher=curl,
        playwright_fetcher=playwright,
    )

    result = asyncio.run(
        manager.fetch(
            "https://example.test",
            validator=lambda _result: StaticValidation(True),
        )
    )

    assert result.strategy == "curl_cffi"
    assert playwright.calls == 0


def test_playwright_fetcher_failure_includes_debug_metadata():
    fetcher = PlaywrightFetcher(ScraperConfig(browser="chromium"), FakeBrowserFailure())

    result = asyncio.run(fetcher.fetch("https://example.test"))

    assert result.strategy == "playwright_chromium"
    assert result.status_code == 503
    assert result.error_type == "navigation_failed"
    assert result.error_message == "Service unavailable"
    assert result.screenshot_path == "debug/page.png"
    assert result.html_dump_path == "debug/page.html"


def test_static_validation_rejects_dynamic_or_blocked_html():
    blocked = FetchResult(
        url="https://example.test",
        status_code=200,
        html="<html><body>Access denied " + ("x" * 220) + "</body></html>",
        strategy="curl_cffi",
    )
    dynamic = FetchResult(
        url="https://example.test",
        status_code=200,
        html="<html><body>Please enable JavaScript " + ("x" * 220) + "</body></html>",
        strategy="curl_cffi",
    )

    assert FetchStrategyManager.validate_static_html(blocked).ok is False
    assert FetchStrategyManager.validate_static_html(dynamic).ok is False
