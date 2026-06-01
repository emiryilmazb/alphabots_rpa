import asyncio
import json
from pathlib import Path

from src.scraper.fetchers import FetchResult
from tools.enrich_vehicle_details import DetailEnricher, merge_non_empty_fields


def test_merge_non_empty_fields_only_fills_blanks():
    vehicle = {
        "Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=123",
        "Preis": "10.000 EUR",
        "Baureihe": "",
        "Ausstattungslinie": "",
        "Finanzierung": "",
        "Financing": "",
    }

    filled = merge_non_empty_fields(
        vehicle,
        {
            "Preis": "11.000 EUR",
            "Baureihe": "F30",
            "Ausstattungslinie": "Sport Line",
            "Financing": "monatliche Rate 199 EUR",
        },
        source="cache",
    )

    assert filled == ["Baureihe", "Ausstattungslinie", "Financing", "Finanzierung"]
    assert vehicle["Preis"] == "10.000 EUR"
    assert vehicle["Baureihe"] == "F30"
    assert vehicle["Finanzierung"] == "monatliche Rate 199 EUR"
    assert "Preis" in vehicle["detail_enrichment_conflicts_json"]


def test_enricher_uses_cached_parsed_fields(tmp_path):
    cache_dir = tmp_path / "cache"
    parsed_dir = cache_dir / "parsed"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "123.json").write_text(
        json.dumps(
            {
                "vehicle_id": "123",
                "parsed_fields": {
                    "Baureihe": "F30",
                    "CO₂-Emissionen": "110 g/km",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    records = [
        {
            "Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=123",
            "Baureihe": "",
            "CO₂-Emissionen": "",
        }
    ]
    enricher = DetailEnricher(
        cache_dir=cache_dir,
        methods=["cache", "listing"],
        chrome_cdp_url="http://127.0.0.1:9222",
        sleep_seconds=0,
        stop_after_blocks=0,
    )

    summary = asyncio.run(enricher.enrich_records(records, max_vehicles=1))

    assert records[0]["Baureihe"] == "F30"
    assert records[0]["CO₂-Emissionen"] == "110 g/km"
    assert records[0]["vehicle_data_source"] == "detail_page_cache"
    assert summary["cache_hit_count"] == 1
    assert summary["successful_vehicle_count"] == 1


def test_enricher_parses_manual_html_sample(tmp_path):
    cache_dir = tmp_path / "cache"
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    fixture = Path("tests/fixtures/html/vehicle_detail_complete.html").read_text(
        encoding="utf-8"
    )
    (manual_dir / "123.html").write_text(fixture, encoding="utf-8")
    records = [
        {
            "Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=123",
            "Baureihe": "",
            "CO₂-Emissionen": "",
        }
    ]
    enricher = DetailEnricher(
        cache_dir=cache_dir,
        methods=["manual-html"],
        chrome_cdp_url="http://127.0.0.1:9222",
        sleep_seconds=0,
        stop_after_blocks=0,
        manual_html_dir=manual_dir,
    )

    summary = asyncio.run(enricher.enrich_records(records, max_vehicles=1))

    assert records[0]["Baureihe"] == "F30"
    assert records[0]["CO₂-Emissionen"] == "110 g/km"
    assert records[0]["vehicle_data_source"] == "detail_page_manual_html"
    assert summary["manual_html_success_count"] == 1
    assert (cache_dir / "parsed" / "123.json").exists()


class FakeBlockedHostFetcher:
    def __init__(self, config):
        self.config = config

    async def fetch(self, url: str, *, attempt: int = 1) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status_code=403,
            html="<html><title>Access Denied</title></html>",
            strategy="host-chrome-cdp",
            browser="host_chrome",
            attempt=attempt,
            error_type="host_chrome_cdp_blocked_or_challenge",
            error_message="HTTP 403 access denied",
            classification="error_page",
            detail_status="error_page",
            failure_reason="access denied",
        )


def test_enricher_records_host_chrome_block_and_disables(tmp_path):
    records = [
        {"Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=123"},
        {"Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=456"},
    ]
    enricher = DetailEnricher(
        cache_dir=tmp_path / "cache",
        methods=["host-chrome-cdp"],
        chrome_cdp_url="http://127.0.0.1:9222",
        sleep_seconds=0,
        stop_after_blocks=1,
        host_fetcher_factory=FakeBlockedHostFetcher,
    )

    summary = asyncio.run(enricher.enrich_records(records, max_vehicles=2))

    assert summary["host_chrome_cdp_attempt_count"] == 1
    assert summary["host_chrome_cdp_blocked_count"] == 1
    assert summary["host_chrome_disabled"] is True
    assert summary["new_failed_detail_ids_count"] == 1
    assert (tmp_path / "cache" / "failed_detail_ids.json").exists()


def test_enricher_forces_cache_before_live_methods(tmp_path):
    cache_dir = tmp_path / "cache"
    parsed_dir = cache_dir / "parsed"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "123.json").write_text(
        json.dumps({"parsed_fields": {"Baureihe": "F30"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    records = [
        {
            "Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=123",
            "Baureihe": "",
        }
    ]
    enricher = DetailEnricher(
        cache_dir=cache_dir,
        methods=["host-chrome-cdp"],
        chrome_cdp_url="http://127.0.0.1:9222",
        sleep_seconds=0,
        stop_after_blocks=1,
        host_fetcher_factory=FakeBlockedHostFetcher,
    )

    summary = asyncio.run(enricher.enrich_records(records, max_vehicles=1))

    assert records[0]["Baureihe"] == "F30"
    assert summary["cache_hit"] == 1
    assert "host_chrome_cdp_attempt_count" not in summary


def test_retry_only_missing_skips_records_with_detail_targets(tmp_path):
    records = [
        {
            "Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=123",
            "CO₂-Emissionen": "110 g/km",
            "Baureihe": "F30",
            "Ausstattungslinie": "Sport Line",
            "Anzahl der Fahrzeughalter": "1",
            "Hubraum": "1.995 cm³",
            "Anzahl der Türen": "4/5",
            "Schadstoffklasse": "Euro 6",
            "Farbe": "Schwarz",
            "Anzahl Sitzplätze": "5",
            "Finanzierung": "",
        }
    ]
    enricher = DetailEnricher(
        cache_dir=tmp_path / "cache",
        methods=["host-chrome-cdp"],
        chrome_cdp_url="http://127.0.0.1:9222",
        sleep_seconds=0,
        stop_after_blocks=1,
        retry_only_missing=True,
        host_fetcher_factory=FakeBlockedHostFetcher,
    )

    summary = asyncio.run(enricher.enrich_records(records, max_vehicles=1))

    assert summary["processed_vehicle_count"] == 0
    assert summary["skipped_not_missing_retry_fields_count"] == 1
    assert "host_chrome_cdp_attempt_count" not in summary


def test_max_block_rate_disables_host_chrome(tmp_path):
    records = [
        {"Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=123"},
        {"Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=456"},
    ]
    enricher = DetailEnricher(
        cache_dir=tmp_path / "cache",
        methods=["host-chrome-cdp"],
        chrome_cdp_url="http://127.0.0.1:9222",
        sleep_seconds=0,
        max_block_rate=0.4,
        host_fetcher_factory=FakeBlockedHostFetcher,
    )

    summary = asyncio.run(enricher.enrich_records(records, max_vehicles=2))

    assert summary["host_chrome_cdp_attempt_count"] == 1
    assert summary["host_chrome_cdp_blocked_count"] == 1
    assert summary["host_chrome_disabled"] is True
    assert summary["host_chrome_cdp_disabled_by_block_rate_count"] == 1
