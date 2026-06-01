"""Tests for regional dealer discovery limits."""

from __future__ import annotations

import asyncio

from src.config import ScraperConfig
from src.scraper.fetchers import FetchResult
from src.scraper.regional_scraper import RegionalScraper


class FakeFetchManager:
    def __init__(self, html: str):
        self.html = html

    async def fetch(self, url, validator=None):
        return FetchResult(
            url=url, html=self.html, status_code=200, strategy="curl_cffi"
        )


def test_regional_on_dealer_respects_max_vendors():
    async def run():
        html = """
        <html><body>
          <a href="https://home.mobile.de/ALPHA"><strong>Alpha Auto</strong><span>Teststr. 1 50667 Köln</span></a>
          <a href="https://home.mobile.de/BETA"><strong>Beta Auto</strong><span>Teststr. 2 50667 Köln</span></a>
          <a href="https://home.mobile.de/GAMMA"><strong>Gamma Auto</strong><span>Teststr. 3 50667 Köln</span></a>
        </body></html>
        """
        scraper = RegionalScraper(
            browser=type(
                "FakeBrowser",
                (),
                {"polite_delay": lambda self: __import__("asyncio").sleep(0)},
            )(),
            config=ScraperConfig(max_vendors=2),
        )
        scraper.fetch_manager = FakeFetchManager(html)
        emitted = []

        async def on_dealer(dealer):
            emitted.append(dealer["url"])

        dealers = await scraper.collect_dealer_entries(on_dealer=on_dealer)
        return dealers, emitted

    dealers, emitted = asyncio.run(run())

    assert len(dealers) == 2
    assert emitted == [
        "https://home.mobile.de/ALPHA",
        "https://home.mobile.de/BETA",
        "https://home.mobile.de/GAMMA",
    ]


def test_regional_parses_32_but_emits_only_max_vendors():
    async def run():
        links = "\n".join(
            f'<a href="https://home.mobile.de/DEALER{i:02d}">'
            f"<strong>Dealer {i:02d}</strong><span>Teststr. {i} 50667 Köln</span></a>"
            for i in range(32)
        )
        scraper = RegionalScraper(
            browser=type(
                "FakeBrowser",
                (),
                {"polite_delay": lambda self: __import__("asyncio").sleep(0)},
            )(),
            config=ScraperConfig(max_vendors=5),
        )
        scraper.fetch_manager = FakeFetchManager(f"<html><body>{links}</body></html>")
        emitted = []

        async def on_dealer(dealer):
            emitted.append(dealer["url"])

        dealers = await scraper.collect_dealer_entries(on_dealer=on_dealer)
        return scraper.last_discovered_count, dealers, emitted

    discovered_count, dealers, emitted = asyncio.run(run())

    assert discovered_count == 32
    assert len(dealers) == 5
    assert len(emitted) == 32


def test_consecutive_empty_pages_stops_pagination():
    async def run():
        scraper = RegionalScraper(
            browser=type(
                "FakeBrowser",
                (),
                {"polite_delay": lambda self: __import__("asyncio").sleep(0)},
            )(),
            config=ScraperConfig(max_pages_per_state=10),
        )

        call_count = 0

        async def mock_fetch(self, url, validator=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                html = f'<html><body><a href="https://home.mobile.de/DEALER{call_count}"><strong>D</strong><span>S</span></a></body></html>'
            else:
                html = "<html><body></body></html>"
            return FetchResult(
                url=url, html=html, status_code=200, strategy="curl_cffi"
            )

        scraper.fetch_manager = type("FakeFM", (), {"fetch": mock_fetch})()
        dealers = await scraper.collect_dealer_entries()
        return call_count, dealers

    call_count, dealers = asyncio.run(run())
    assert call_count == 5
    assert len(dealers) == 2


def test_consecutive_empty_pages_resets_on_success():
    async def run():
        scraper = RegionalScraper(
            browser=type(
                "FakeBrowser",
                (),
                {"polite_delay": lambda self: __import__("asyncio").sleep(0)},
            )(),
            config=ScraperConfig(max_pages_per_state=10),
        )

        call_count = 0

        async def mock_fetch(self, url, validator=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1 or call_count == 4:
                html = f'<html><body><a href="https://home.mobile.de/DEALER{call_count}"><strong>D</strong><span>S</span></a></body></html>'
            else:
                html = "<html><body></body></html>"
            return FetchResult(
                url=url, html=html, status_code=200, strategy="curl_cffi"
            )

        scraper.fetch_manager = type("FakeFM", (), {"fetch": mock_fetch})()
        dealers = await scraper.collect_dealer_entries()
        return call_count, dealers

    call_count, dealers = asyncio.run(run())
    assert call_count == 7
    assert len(dealers) == 2


def test_max_pages_honored():
    async def run():
        scraper = RegionalScraper(
            browser=type(
                "FakeBrowser",
                (),
                {"polite_delay": lambda self: __import__("asyncio").sleep(0)},
            )(),
            config=ScraperConfig(max_pages_per_state=2),
        )
        call_count = 0

        async def mock_fetch(self, url, validator=None):
            nonlocal call_count
            call_count += 1
            html = f'<html><body><a href="https://home.mobile.de/D{call_count}"><strong>D</strong><span>S</span></a></body></html>'
            return FetchResult(
                url=url, html=html, status_code=200, strategy="curl_cffi"
            )

        scraper.fetch_manager = type("FakeFM", (), {"fetch": mock_fetch})()
        dealers = await scraper.collect_dealer_entries()
        return call_count, dealers

    call_count, dealers = asyncio.run(run())
    assert call_count == 2
    assert len(dealers) == 2


def test_consecutive_fallback_failures_stops_pagination():
    async def run():
        scraper = RegionalScraper(
            browser=type(
                "FakeBrowser",
                (),
                {"polite_delay": lambda self: __import__("asyncio").sleep(0)},
            )(),
            config=ScraperConfig(max_pages_per_state=10),
        )

        call_count = 0

        async def mock_fetch(self, url, validator=None):
            nonlocal call_count
            call_count += 1
            html = f'<html><body><a href="https://home.mobile.de/D{call_count}"><strong>D</strong><span>S</span></a></body></html>'
            return FetchResult(
                url=url, html=html, status_code=200, strategy="playwright"
            )

        scraper.fetch_manager = type("FakeFM", (), {"fetch": mock_fetch})()
        scraper.browser.page = type(
            "FakePage",
            (),
            {
                "wait_for_load_state": lambda *args, **kwargs: __import__(
                    "asyncio"
                ).sleep(0)
            },
        )()

        async def mock_get_html():
            return f'<html><body><a href="https://home.mobile.de/D{call_count}"><strong>D</strong><span>S</span></a></body></html>'

        scraper.browser.get_page_html = mock_get_html

        dealers = await scraper.collect_dealer_entries()
        return call_count, dealers

    call_count, dealers = asyncio.run(run())
    assert call_count == 3
    assert len(dealers) == 2
