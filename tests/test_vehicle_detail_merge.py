import asyncio
from pathlib import Path

from src.config import ScraperConfig
from src.scraper.fetchers import FetchResult
from src.scraper.vehicle_scraper import VehicleScraper


def test_detail_merge_only_fills_missing_listing_fields():
    config = ScraperConfig()
    scraper = VehicleScraper(browser=None, config=config)  # type: ignore[arg-type]
    vehicle = {
        "Preis": "10.000 €",
        "Baureihe": "",
        "Ausstattungslinie": "",
        "Anzahl der Fahrzeughalter": "1",
    }

    filled = scraper._merge_detail_fields(
        vehicle,
        {
            "Preis": "11.000 €",
            "Baureihe": "8",
            "Ausstattungslinie": "Life",
            "Anzahl der Fahrzeughalter": "2",
        },
        "uc-popup",
    )

    assert filled == ["Baureihe", "Ausstattungslinie"]
    assert vehicle["Preis"] == "10.000 €"
    assert vehicle["Anzahl der Fahrzeughalter"] == "1"
    assert vehicle["Baureihe"] == "8"
    assert vehicle["Ausstattungslinie"] == "Life"
    assert vehicle["Baureihe_source"] == "uc-popup"
    assert "Preis" in vehicle["detail_conflicts_json"]
    assert config.fields_added_by_uc_popup_count == 2


class FakeHostChromeCdpFetcher:
    def __init__(self, html: str):
        self.html = html
        self.calls = 0

    async def fetch(self, url: str, *, attempt: int = 1) -> FetchResult:
        self.calls += 1
        return FetchResult(
            url=url,
            final_url=url,
            html=self.html,
            strategy="host-chrome-cdp",
            browser="host_chrome",
            attempt=attempt,
            detail_status="real_detail_page",
        )


def test_host_chrome_strategy_parses_fake_cdp_html():
    html = Path("tests/fixtures/html/vehicle_detail_complete.html").read_text(encoding="utf-8")
    config = ScraperConfig(detail_open_strategy="host-chrome-cdp")
    scraper = VehicleScraper(browser=None, config=config)  # type: ignore[arg-type]
    fake_fetcher = FakeHostChromeCdpFetcher(html)
    scraper.host_chrome_cdp_fetcher = fake_fetcher  # type: ignore[assignment]

    vehicle = asyncio.run(
        scraper.scrape_vehicle(
            "https://suchen.mobile.de/fahrzeuge/details.html?id=123",
            {"Händler ID": "C0000001", "Händlername": "Demo", "PLZ": "50667"},
            fallback={},
        )
    )

    assert fake_fetcher.calls == 1
    assert vehicle["detail_strategy_used"] == "host-chrome-cdp"
    assert vehicle["vehicle_data_source"] == "detail_page_host_chrome_cdp"
    assert vehicle["Baureihe"] == "F30"
    assert vehicle["CO₂-Emissionen"] == "110 g/km"
