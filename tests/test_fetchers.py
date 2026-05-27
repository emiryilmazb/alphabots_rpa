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
    vehicle_id_from_url,
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

    async def fetch(self, url: str, *, attempt: int = 1, **kwargs) -> FetchResult:
        self.calls += 1
        self.result.attempt = attempt
        return self.result


class FakeBrowserFailure:
    last_status = 503
    last_error = "Service unavailable"
    last_screenshot_path = "debug/page.png"
    last_html_dump_path = "debug/page.html"
    started = 0
    last_safe_goto_kwargs = {}

    async def ensure_started(self):
        self.started += 1

    async def safe_goto(self, url: str, **kwargs) -> bool:
        self.last_safe_goto_kwargs = kwargs
        return False


def test_fetch_result_defaults_are_populated():
    result = FetchResult(url="https://example.test", html="<html></html>", strategy="curl_cffi")

    assert result.final_url == "https://example.test"
    assert result.fetched_at
    assert result.ok is True


def test_vehicle_id_from_url_extracts_detail_query_id():
    assert (
        vehicle_id_from_url("https://suchen.mobile.de/fahrzeuge/details.html?id=444369609&lang=de")
        == "444369609"
    )


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
    browser = FakeBrowserFailure()
    fetcher = PlaywrightFetcher(ScraperConfig(browser="chromium"), browser)

    result = asyncio.run(fetcher.fetch("https://example.test", max_retries=1))

    assert result.strategy == "playwright_chromium"
    assert result.status_code == 503
    assert result.error_type == "navigation_failed"
    assert result.error_message == "Service unavailable"
    assert result.screenshot_path == "debug/page.png"
    assert result.html_dump_path == "debug/page.html"
    assert browser.last_safe_goto_kwargs["max_retries"] == 1


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


def test_curl_fetcher_short_circuits_after_module_not_found():
    """After first ModuleNotFoundError, CurlFetcher returns immediately without re-trying import."""

    _call_count = 0

    def _broken_session_factory():
        nonlocal _call_count
        _call_count += 1
        raise ModuleNotFoundError("No module named 'curl_cffi'")

    # Reset class state
    CurlFetcher._curl_cffi_available = None

    fetcher = CurlFetcher(
        ScraperConfig(fetch_strategy="auto"),
        session_factory=_broken_session_factory,
    )

    # First call: hits the import → sets flag
    r1 = asyncio.run(fetcher.fetch("https://example.test/1"))
    assert r1.error_type == "ModuleNotFoundError"
    assert CurlFetcher._curl_cffi_available is False
    assert _call_count == 1

    # Second call: short-circuits immediately (no import attempt)
    # Need a fetcher WITHOUT custom session_factory to test the short-circuit path
    fetcher2 = CurlFetcher(ScraperConfig(fetch_strategy="auto"))
    r2 = asyncio.run(fetcher2.fetch("https://example.test/2"))
    assert r2.error_type == "ModuleNotFoundError"
    assert r2.elapsed_ms == 0  # short-circuit returns 0 elapsed
    assert _call_count == 1  # no additional factory calls

    # Cleanup: reset class state for other tests
    CurlFetcher._curl_cffi_available = None
