"""Tests for browser lifecycle recovery behavior."""

from __future__ import annotations

import asyncio

import pytest

from src.config import ScraperConfig
from src.scraper.browser import BrowserManager, TargetClosedError


class FakeResponse:
    status = 200


class FakeLocator:
    async def count(self):
        return 0

    async def inner_text(self, timeout=0):
        return ""


class FlakyPage:
    url = "https://example.test"

    def __init__(self):
        self.calls = 0

    async def goto(self, url, wait_until=None, timeout=0):
        self.calls += 1
        if self.calls == 1:
            raise TargetClosedError("Target page, context or browser has been closed")
        return FakeResponse()

    def locator(self, selector):
        return FakeLocator()


def test_safe_goto_recovers_from_target_closed_once(monkeypatch):
    if TargetClosedError is None:
        pytest.skip("TargetClosedError is not importable in this Playwright version")

    async def run():
        manager = BrowserManager(ScraperConfig(max_retries=2, retry_delay=0))
        page = FlakyPage()
        manager._page = page
        manager._healthy = True

        async def fake_recover(exc):
            manager._healthy = True
            manager._page = page
            return True

        monkeypatch.setattr(manager, "_recover_from_target_closed", fake_recover)
        assert await manager.safe_goto("https://example.test") is True
        assert page.calls == 2

    asyncio.run(run())


def test_close_attempts_all_resources_when_page_close_fails():
    class Resource:
        def __init__(self, fail=False):
            self.fail = fail
            self.closed = False

        async def close(self):
            self.closed = True
            if self.fail:
                raise RuntimeError("close failed")

    class PlaywrightResource:
        def __init__(self):
            self.stopped = False

        async def stop(self):
            self.stopped = True

    async def run():
        manager = BrowserManager(ScraperConfig(use_storage_state=False))
        page = Resource(fail=True)
        context = Resource()
        browser = Resource()
        playwright = PlaywrightResource()
        manager._page = page
        manager._context = context
        manager._browser = browser
        manager._pw = playwright

        await manager.close()

        assert page.closed is True
        assert context.closed is True
        assert browser.closed is True
        assert playwright.stopped is True

    asyncio.run(run())


def test_accept_cookies_clicks_visible_modal_verifies_dismissal_and_saves_state(
    tmp_path,
):
    class CookieButton:
        def __init__(self, page):
            self.page = page

        async def count(self):
            return 1 if self.page.modal_visible else 0

        def nth(self, index):
            return self

        async def is_visible(self, timeout=0):
            return self.page.modal_visible

        async def click(self, timeout=0):
            self.page.clicked = True
            self.page.modal_visible = False

    class EmptyLocator:
        async def count(self):
            return 0

        def nth(self, index):
            return self

        async def is_visible(self, timeout=0):
            return False

    class CookiePage:
        def __init__(self):
            self.modal_visible = True
            self.clicked = False

        def locator(self, selector):
            if "Einverstanden" in selector or "mde-consent-accept-btn" in selector:
                return CookieButton(self)
            return EmptyLocator()

        async def wait_for_timeout(self, timeout):
            return None

    class CookieContext:
        def __init__(self):
            self.saved_path = ""

        async def storage_state(self, path):
            self.saved_path = path

    async def run():
        config = ScraperConfig(
            storage_state=tmp_path / "mobile_de_storage_state.json",
            use_storage_state=True,
        )
        manager = BrowserManager(config)
        page = CookiePage()
        context = CookieContext()
        manager._page = page
        manager._context = context

        await manager.accept_cookies()

        assert page.clicked is True
        assert context.saved_path == str(config.storage_state)
        assert config.cookie_modal_visible_count == 1
        assert config.cookie_consent_click_count == 1
        assert config.cookie_modal_remaining_count == 0

    asyncio.run(run())
