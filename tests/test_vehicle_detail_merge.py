from src.config import ScraperConfig
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
