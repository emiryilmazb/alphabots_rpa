"""Tests for category traversal modes (discovered, all, off)."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

from src.config import ScraperConfig
from src.scraper.vehicle_scraper import VehicleScraper
from src.scraper.parsers import DEFAULT_VEHICLE_CATEGORY_VALUES


class FakeBrowser:
    """Minimal BrowserManager stand-in for category traversal tests."""

    def __init__(self, page_html: str = ""):
        self._page_html = page_html
        self._page = AsyncMock()
        self._page.content = AsyncMock(return_value=page_html)
        self.visited_urls = []

    @property
    def page(self):
        return self._page

    async def safe_goto(self, url: str):
        self.visited_urls.append(url)
        return True

    async def polite_delay(self):
        return None


def _make_scraper(
    mode: str = "discovered", traverse: bool = True, page_html: str = ""
) -> VehicleScraper:
    config = ScraperConfig(
        category_traversal=mode,
        traverse_vehicle_categories=traverse,
    )
    browser = FakeBrowser(page_html)
    return VehicleScraper(browser, config)


# -- Helper: build visible category chips with counts ---------
def _html_with_categories(categories: list[tuple[str, str, int]]) -> str:
    links = "\n".join(
        f'<a href="/AUTOHAUS?vc={value}">{label} ({count})</a>'
        for value, label, count in categories
    )
    return f"<html><body><nav>{links}</nav></body></html>"


# === discovered mode (default) ========================================


def test_discovered_mode_returns_only_discovered_categories():
    html = _html_with_categories(
        [
            ("Car", "Pkw", 12),
            ("Motorbike", "Motorräder", 2),
            ("Bus", "Busse", 0),
        ]
    )
    scraper = _make_scraper("discovered", page_html=html)

    result = asyncio.run(scraper._category_sequence_from_current_page())
    assert result == ["Car", "Motorbike"]
    assert "Bus" not in result
    assert "AgriculturalVehicle" not in result


def test_discovered_mode_returns_none_when_no_categories_found():
    scraper = _make_scraper(
        "discovered", page_html="<html><body>No categories</body></html>"
    )

    result = asyncio.run(scraper._category_sequence_from_current_page())
    assert result == [None]


def test_discovered_mode_does_not_append_hardcoded():
    html = _html_with_categories([("Car", "Pkw", 1)])
    scraper = _make_scraper("discovered", page_html=html)

    result = asyncio.run(scraper._category_sequence_from_current_page())
    assert result == ["Car"]
    # No hardcoded categories should be appended
    for hc in DEFAULT_VEHICLE_CATEGORY_VALUES:
        if hc != "Car":
            assert hc not in result, (
                f"Hardcoded category {hc} should NOT be in discovered-only result"
            )


# === all mode =========================================================


def test_all_mode_includes_hardcoded_categories():
    html = _html_with_categories([("Car", "Pkw", 1)])
    scraper = _make_scraper("all", page_html=html)

    result = asyncio.run(scraper._category_sequence_from_current_page())
    assert result[0] == "Car"
    for hc in DEFAULT_VEHICLE_CATEGORY_VALUES:
        assert hc in result, f"Hardcoded category {hc} should be in 'all' mode result"


def test_all_mode_fallback_when_no_categories_found():
    scraper = _make_scraper("all", page_html="<html><body>empty</body></html>")

    result = asyncio.run(scraper._category_sequence_from_current_page())
    assert result[0] is None
    for hc in DEFAULT_VEHICLE_CATEGORY_VALUES:
        assert hc in result


# === off mode =========================================================


def test_off_mode_returns_none():
    scraper = _make_scraper("off")
    result = asyncio.run(scraper._category_sequence_from_current_page())
    assert result == [None]


def test_legacy_traverse_false_returns_none():
    scraper = _make_scraper("discovered", traverse=False)
    result = asyncio.run(scraper._category_sequence_from_current_page())
    assert result == [None]


def test_only_car_one_discovered_only_car_is_visited():
    html = _html_with_categories(
        [
            ("Car", "Pkw", 1),
            ("Bus", "Busse", 0),
            ("AgriculturalVehicle", "Agrarfahrzeuge", 0),
        ]
    )
    scraper = _make_scraper("discovered", page_html=html)

    result = asyncio.run(scraper._category_sequence_from_current_page())

    assert result == ["Car"]
    assert scraper.category_metadata["Car"]["source_category_count"] == 1


def test_discovered_mode_parses_vehicle_category_sidebar_inputs_not_active_chip():
    html = """
    <html><body>
      <ul data-testid="filter-chips-list">
        <li>Trailer</li>
      </ul>
      <article data-testid="search-column">
        <label>Vehicle category</label>
        <div class="VehicleCategoryFilter-module__maxWidth">
          <label>
            <input type="checkbox" checked value="VanUpTo7500" />
            <div><div class="VehicleCategoryFilter-module__vehicleCategoryChipLabel">Van or truck up to 7.5 t</div><div>(2)</div></div>
          </label>
          <label>
            <input type="checkbox" value="SemiTrailer" />
            <div><div class="VehicleCategoryFilter-module__vehicleCategoryChipLabel">Semi-trailer</div><div>(1)</div></div>
          </label>
          <label>
            <input type="checkbox" value="SemiTrailerTruck" />
            <div><div class="VehicleCategoryFilter-module__vehicleCategoryChipLabel">Semi-trailer truck</div><div>(1)</div></div>
          </label>
          <label>
            <input type="checkbox" value="TruckOver7500" />
            <div><div class="VehicleCategoryFilter-module__vehicleCategoryChipLabel">Truck over 7.5 t</div><div>(1)</div></div>
          </label>
        </div>
      </article>
    </body></html>
    """
    scraper = _make_scraper("discovered", page_html=html)

    result = asyncio.run(scraper._category_sequence_from_current_page())

    assert result == ["VanUpTo7500", "SemiTrailer", "SemiTrailerTruck", "TruckOver7500"]
    assert "Trailer" not in result
    assert scraper.category_metadata["VanUpTo7500"]["source_category_count"] == 2
    assert (
        scraper.category_metadata["SemiTrailer"]["source_category_label"]
        == "Semi-trailer"
    )


def test_collect_entries_logs_remaining_categories_skipped_at_vendor_limit(caplog):
    html = _html_with_categories(
        [
            ("Car", "Pkw", 10),
            ("VanUpTo7500", "Transporter", 3),
            ("Motorbike", "Motorräder", 2),
        ]
    )
    config = ScraperConfig(category_traversal="discovered", max_cars_per_vendor=5)
    browser = FakeBrowser(html)
    scraper = VehicleScraper(browser, config)

    async def fake_collect(dealer_url, category_value, existing_count):
        return [
            {"Vehicle_URL": f"synthetic://{category_value}-{index}", "Markes": "VW"}
            for index in range(5)
        ]

    scraper._collect_entries_from_loaded_inventory = fake_collect
    caplog.set_level(logging.INFO, logger="mobile_de.vehicle")

    entries = asyncio.run(
        scraper.collect_vehicle_entries("https://home.mobile.de/ALPHA")
    )

    assert len(entries) == 5
    assert browser.visited_urls == ["https://home.mobile.de/ALPHA?vc=Car"]
    assert (
        "max-cars-per-vendor reached after Car; skipping remaining categories: VanUpTo7500, Motorbike"
        in caplog.text
    )


def test_collect_entries_without_vendor_limit_visits_all_discovered_categories():
    html = _html_with_categories(
        [
            ("Car", "Pkw", 10),
            ("VanUpTo7500", "Transporter", 3),
            ("Motorbike", "Motorräder", 2),
        ]
    )
    config = ScraperConfig(category_traversal="discovered", max_cars_per_vendor=0)
    browser = FakeBrowser(html)
    scraper = VehicleScraper(browser, config)

    async def fake_collect(dealer_url, category_value, existing_count):
        return [{"Vehicle_URL": f"synthetic://{category_value}", "Markes": "VW"}]

    scraper._collect_entries_from_loaded_inventory = fake_collect

    entries = asyncio.run(
        scraper.collect_vehicle_entries("https://home.mobile.de/ALPHA")
    )

    assert len(entries) == 3
    assert browser.visited_urls == [
        "https://home.mobile.de/ALPHA?vc=Car",
        "https://home.mobile.de/ALPHA?vc=VanUpTo7500",
        "https://home.mobile.de/ALPHA?vc=Motorbike",
    ]
    assert [report["category"] for report in scraper.last_category_report] == [
        "Car",
        "VanUpTo7500",
        "Motorbike",
    ]
    assert all(report["visited"] for report in scraper.last_category_report)
