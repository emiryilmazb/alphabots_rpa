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
        return FetchResult(url=url, html=self.html, status_code=200, strategy="curl_cffi")


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
            browser=type("FakeBrowser", (), {"polite_delay": lambda self: __import__("asyncio").sleep(0)})(),
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
    assert emitted == ["https://home.mobile.de/ALPHA", "https://home.mobile.de/BETA", "https://home.mobile.de/GAMMA"]


def test_regional_parses_32_but_emits_only_max_vendors():
    async def run():
        links = "\n".join(
            f'<a href="https://home.mobile.de/DEALER{i:02d}">'
            f"<strong>Dealer {i:02d}</strong><span>Teststr. {i} 50667 Köln</span></a>"
            for i in range(32)
        )
        scraper = RegionalScraper(
            browser=type("FakeBrowser", (), {"polite_delay": lambda self: __import__("asyncio").sleep(0)})(),
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
