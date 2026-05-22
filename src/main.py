"""Main entry point for the mobile.de scraping and reporting pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import ScraperConfig, parse_args
from src.models import VEHICLE_COLUMNS, VENDOR_COLUMNS
from src.output.excel_writer import generate_excel
from src.output.word_report import generate_word_report
from src.processing.classification import classify_dataframe
from src.processing.cleaning import clean_dataframes
from src.processing.dashboard import prepare_dashboard
from src.scraper.browser import BrowserManager
from src.scraper.parsers import normalize_dealer_url
from src.scraper.regional_scraper import RegionalScraper
from src.scraper.vehicle_scraper import VehicleScraper
from src.scraper.vendor_scraper import VendorScraper
from src.utils.checkpoints import CheckpointManager
from src.utils.logging_utils import get_logger, setup_logging

logger: logging.Logger = logging.getLogger("mobile_de.main")

BUNDESLAND_MAP = {
    "baden-wuerttemberg": "Baden-Württemberg",
    "bayern": "Bayern",
    "berlin": "Berlin",
    "brandenburg": "Brandenburg",
    "bremen": "Bremen",
    "hamburg": "Hamburg",
    "hessen": "Hessen",
    "mecklenburg-vorpommern": "Mecklenburg-Vorpommern",
    "niedersachsen": "Niedersachsen",
    "nordrhein-westfalen": "Nordrhein-Westfalen",
    "rheinland-pfalz": "Rheinland-Pfalz",
    "saarland": "Saarland",
    "sachsen": "Sachsen",
    "sachsen-anhalt": "Sachsen-Anhalt",
    "schleswig-holstein": "Schleswig-Holstein",
    "thueringen": "Thüringen",
}


async def run_pipeline(config: ScraperConfig) -> None:
    """Execute scraping, preprocessing, dashboard generation, and reporting."""
    global logger
    logger = get_logger("main")

    config.ensure_dirs()
    checkpoint = CheckpointManager(config.checkpoint_dir)
    if config.clear_checkpoints:
        checkpoint.clear_all()

    bundesland = BUNDESLAND_MAP.get(config.state, config.state.replace("-", " ").title())
    errors: list[dict[str, Any]] = []
    dealers_data: list[dict[str, str]] = []
    vendors: list[dict[str, Any]] = []
    all_cars: list[dict[str, Any]] = []

    browser = BrowserManager(config)

    try:
        await browser.start()
        logger.info("=" * 60)
        logger.info("TASK 1: DATA EXTRACTION")
        logger.info("State: %s (%s)", config.state, bundesland)
        logger.info("Start URL: %s", config.state_page_url.format(page=0))
        logger.info("=" * 60)

        dealers_data = await _load_or_collect_dealers(config, checkpoint, browser, errors)
        if not dealers_data and _should_retry_headed(config, browser):
            errors.append(
                {
                    "type": "headless_blocked",
                    "url": config.state_page_url.format(page=0),
                    "error": browser.last_error
                    or "Headless browser was blocked by mobile.de site protection.",
                }
            )
            logger.warning(
                "Headless mode was blocked by mobile.de site protection. "
                "Restarting once in headed mode to collect deliverable data."
            )
            await browser.close()
            config.headless = False
            browser = BrowserManager(config)
            await browser.start()
            dealers_data = await _load_or_collect_dealers(config, checkpoint, browser, errors)

        dealers_data = _prepare_dealers(dealers_data, config.max_vendors)

        if not dealers_data:
            errors.append(
                {
                    "type": "regional",
                    "url": config.state_page_url.format(page=0),
                    "error": browser.last_error
                    or "No vendors discovered from the regional state directory.",
                }
            )
            logger.error("No dealers found. Continuing with empty deliverables.")
        else:
            vendors = await _scrape_vendors(
                config,
                checkpoint,
                browser,
                dealers_data,
                bundesland,
                errors,
            )
            _save_records(vendors, config.raw_dir / "vendors_raw", VENDOR_COLUMNS)

            all_cars = await _scrape_vehicles(config, checkpoint, browser, vendors, errors)
            _save_records(all_cars, config.raw_dir / "cars_raw", VEHICLE_COLUMNS)

    except Exception as exc:
        logger.exception("Pipeline scraping phase failed: %s", exc)
        errors.append({"type": "pipeline", "url": "", "error": str(exc)})
    finally:
        await browser.close()

    # Always write raw files, even after a blocked or empty run.
    _save_records(vendors, config.raw_dir / "vendors_raw", VENDOR_COLUMNS)
    _save_records(all_cars, config.raw_dir / "cars_raw", VEHICLE_COLUMNS)

    logger.info("=" * 60)
    logger.info("TASK 2: DATA PREPROCESSING")
    logger.info("=" * 60)

    df_vendors_raw = _records_to_df(vendors, VENDOR_COLUMNS)
    df_cars_raw = _records_to_df(all_cars, VEHICLE_COLUMNS)
    df_vendors_clean, df_cars_clean = clean_dataframes(df_vendors_raw, df_cars_raw)
    df_cars_classified = classify_dataframe(df_cars_clean)

    config.processed_dir.mkdir(parents=True, exist_ok=True)
    processed_csv = config.processed_dir / "cars_processed.csv"
    processed_json = config.processed_dir / "cars_processed.json"
    df_cars_classified.to_csv(processed_csv, index=False, encoding="utf-8-sig")
    df_cars_classified.to_json(processed_json, orient="records", force_ascii=False, indent=2)
    logger.info("Processed vehicle data saved: %s", processed_csv)

    logger.info("=" * 60)
    logger.info("TASK 3: DASHBOARD GENERATION")
    logger.info("=" * 60)

    dashboard = prepare_dashboard(df_vendors_clean, df_cars_classified)
    generate_excel(config.excel_path, df_vendors_clean, df_cars_raw, df_cars_classified, dashboard)
    generate_word_report(config.word_path, df_vendors_clean, df_cars_classified, dashboard, config.state, errors)
    _save_errors(errors, config.output_dir)

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("  Vendors scraped: %d", len(df_vendors_clean))
    logger.info("  Vehicles scraped: %d", len(df_cars_raw))
    logger.info("  Errors: %d", len(errors))
    logger.info("  Excel: %s", config.excel_path)
    logger.info("  Word:  %s", config.word_path)
    logger.info("=" * 60)


async def _load_or_collect_dealers(
    config: ScraperConfig,
    checkpoint: CheckpointManager,
    browser: BrowserManager,
    errors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if config.resume and checkpoint.exists("dealers"):
        loaded = checkpoint.load("dealers") or []
        if loaded:
            logger.info("Resumed %d dealers from checkpoint.", len(loaded))
            return loaded
        logger.info("Ignoring empty dealer checkpoint and recollecting dealers.")

    regional = RegionalScraper(browser, config)
    try:
        dealers = await regional.collect_dealer_entries()
    except Exception as exc:
        logger.exception("Regional scraper failed: %s", exc)
        errors.append({"type": "regional", "url": config.state_page_url.format(page=0), "error": str(exc)})
        return []
    if dealers:
        checkpoint.save("dealers", dealers)
    return dealers


def _prepare_dealers(dealers: list[dict[str, str]], max_vendors: int) -> list[dict[str, str]]:
    by_url: dict[str, dict[str, str]] = {}
    for dealer in dealers:
        url = normalize_dealer_url(dealer.get("url", ""))
        if not url:
            continue
        clean_dealer = {**dealer, "url": url}
        by_url[url] = clean_dealer

    prepared = sorted(by_url.values(), key=lambda item: item["url"].lower())
    if max_vendors > 0:
        prepared = prepared[:max_vendors]
    logger.info("Prepared %d unique dealers for scraping.", len(prepared))
    return prepared


def _should_retry_headed(config: ScraperConfig, browser: BrowserManager) -> bool:
    if not config.headless or not config.fallback_to_headed_on_block:
        return False
    last_error = (browser.last_error or "").lower()
    return browser.last_status == 403 or "access denied" in last_error or "site protection" in last_error


async def _scrape_vendors(
    config: ScraperConfig,
    checkpoint: CheckpointManager,
    browser: BrowserManager,
    dealers_data: list[dict[str, str]],
    bundesland: str,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    vendors: list[dict[str, Any]] = []
    target_urls = {dealer["url"] for dealer in dealers_data}
    id_by_url = {dealer["url"]: f"C{idx + 1:07d}" for idx, dealer in enumerate(dealers_data)}

    if config.resume and checkpoint.exists("vendors"):
        loaded = checkpoint.load("vendors") or []
        vendors = []
        for vendor in loaded:
            url = normalize_dealer_url(vendor.get("Mobile.de_Links", ""))
            if url not in target_urls:
                continue
            vendor["Mobile.de_Links"] = url
            vendor["Händler ID"] = id_by_url.get(url, vendor.get("Händler ID", ""))
            vendors.append(vendor)
        vendors = _dedupe_vendors(vendors)
        logger.info("Resumed %d vendors from checkpoint for current target set.", len(vendors))

    completed_urls = {normalize_dealer_url(v.get("Mobile.de_Links", "")) for v in vendors}
    vendor_scraper = VendorScraper(browser, config)

    for index, dealer in enumerate(dealers_data, start=1):
        url = dealer["url"]
        if url in completed_urls:
            continue
        haendler_id = id_by_url[url]
        try:
            vendor_data = await vendor_scraper.scrape_vendor(dealer, bundesland)
            vendor_data["Händler ID"] = haendler_id
            vendor_data["Mobile.de_Links"] = normalize_dealer_url(vendor_data.get("Mobile.de_Links", url)) or url
            normalized_vendor_url = normalize_dealer_url(vendor_data["Mobile.de_Links"])
            vendor_data["Mobile.de_Links"] = normalized_vendor_url
            vendors.append(vendor_data)
            vendors = _dedupe_vendors(vendors)
            completed_urls.add(normalized_vendor_url)
            checkpoint.save("vendors", vendors)
            _save_records(vendors, config.raw_dir / "vendors_raw", VENDOR_COLUMNS)
            logger.info(
                "[%d/%d] Vendor %s scraped: %s",
                index,
                len(dealers_data),
                haendler_id,
                vendor_data.get("Händlername", ""),
            )
        except Exception as exc:
            logger.exception("Error scraping vendor %s: %s", url, exc)
            errors.append({"type": "vendor", "url": url, "error": str(exc)})
        await browser.polite_delay()

    return sorted(vendors, key=lambda item: item.get("Händler ID", ""))


def _dedupe_vendors(vendors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate vendors by canonical dealer URL, keeping the most complete row."""
    by_url: dict[str, dict[str, Any]] = {}
    for vendor in vendors:
        url = normalize_dealer_url(vendor.get("Mobile.de_Links", ""))
        if not url:
            continue
        vendor["Mobile.de_Links"] = url
        existing = by_url.get(url)
        if existing is None or _record_score(vendor) > _record_score(existing):
            by_url[url] = vendor
    return sorted(by_url.values(), key=lambda item: item.get("Händler ID", ""))


def _record_score(record: dict[str, Any]) -> int:
    return sum(1 for value in record.values() if str(value).strip() not in {"", "None", "nan"})


async def _scrape_vehicles(
    config: ScraperConfig,
    checkpoint: CheckpointManager,
    browser: BrowserManager,
    vendors: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    all_cars: list[dict[str, Any]] = []
    if config.resume and checkpoint.exists("vehicles"):
        all_cars = checkpoint.load("vehicles") or []
        logger.info("Resumed %d vehicles from checkpoint.", len(all_cars))

    completed_vehicle_urls = {car.get("Vehicle_URL", "") for car in all_cars}
    completed_vendor_vehicles = checkpoint.get_completed_set("vendor_vehicles_done")
    vehicle_scraper = VehicleScraper(browser, config)
    detail_pages_disabled = config.skip_vehicle_details
    detail_failure_count = 0
    detail_disable_recorded = False

    for vendor in vendors:
        vendor_url = normalize_dealer_url(vendor.get("Mobile.de_Links", ""))
        haendler_id = vendor.get("Händler ID", "")
        if not vendor_url:
            continue
        if vendor_url in completed_vendor_vehicles:
            continue

        logger.info("Collecting vehicles for %s (%s).", vendor.get("Händlername", ""), haendler_id)
        if not await browser.safe_goto(vendor_url):
            errors.append({"type": "vendor_vehicles", "url": vendor_url, "error": browser.last_error})
            logger.warning("Cannot load vendor page for vehicles: %s", vendor_url)
            continue

        try:
            vehicle_entries = await vehicle_scraper.collect_vehicle_entries(vendor_url)
            vendor_info = {
                "Händler ID": haendler_id,
                "Händlername": vendor.get("Händlername", ""),
                "PLZ": vendor.get("PLZ", ""),
            }

            for vehicle_entry in vehicle_entries:
                vehicle_url = vehicle_entry.get("Vehicle_URL", "")
                if vehicle_url in completed_vehicle_urls:
                    continue
                try:
                    fallback = vehicle_scraper.listing_summaries.get(vehicle_url, vehicle_entry)
                    if detail_pages_disabled or not _is_real_vehicle_detail_url(vehicle_url):
                        car_data = _vehicle_from_fallback(vendor_info, vehicle_url, fallback)
                    else:
                        car_data = await vehicle_scraper.scrape_vehicle(vehicle_url, vendor_info, fallback)
                        if _detail_request_failed(browser):
                            detail_failure_count += 1
                            if (
                                config.max_detail_failures > 0
                                and detail_failure_count >= config.max_detail_failures
                            ):
                                detail_pages_disabled = True
                                if not detail_disable_recorded:
                                    errors.append(
                                        {
                                            "type": "vehicle_details_disabled",
                                            "url": vehicle_url,
                                            "error": (
                                                "Vehicle detail pages returned repeated "
                                                f"{browser.last_error or browser.last_status}; "
                                                "continuing with structured dealer-listing data."
                                            ),
                                        }
                                    )
                                    detail_disable_recorded = True
                                logger.warning(
                                    "Disabling further vehicle detail requests after %d failures; "
                                    "continuing from structured listing payloads.",
                                    detail_failure_count,
                                )
                    all_cars.append(car_data)
                    completed_vehicle_urls.add(vehicle_url)
                    checkpoint.save("vehicles", all_cars)
                    _save_records(all_cars, config.raw_dir / "cars_raw", VEHICLE_COLUMNS)
                except Exception as exc:
                    logger.exception("Error scraping vehicle %s: %s", vehicle_url, exc)
                    errors.append({"type": "vehicle", "url": vehicle_url, "error": str(exc)})
                await browser.polite_delay()

            checkpoint.add_completed("vendor_vehicles_done", vendor_url)
        except Exception as exc:
            logger.exception("Error processing vendor vehicles %s: %s", vendor_url, exc)
            errors.append({"type": "vendor_vehicles", "url": vendor_url, "error": str(exc)})

    return all_cars


def _is_real_vehicle_detail_url(url: str) -> bool:
    return "/fahrzeuge/details" in url or "/auto-inserat/" in url


def _detail_request_failed(browser: BrowserManager) -> bool:
    if browser.last_status in {403, 429, 500, 502, 503, 504}:
        return True
    last_error = (browser.last_error or "").lower()
    return "access denied" in last_error or "site protection" in last_error


def _vehicle_from_fallback(
    vendor_info: dict[str, str],
    vehicle_url: str,
    fallback: dict[str, str],
) -> dict[str, Any]:
    vehicle = {col: "" for col in VEHICLE_COLUMNS}
    vehicle.update(
        {
            "Händler ID": vendor_info.get("Händler ID", ""),
            "Händlername": vendor_info.get("Händlername", ""),
            "PLZ": vendor_info.get("PLZ", ""),
            "Vehicle_URL": vehicle_url,
        }
    )
    for key, value in fallback.items():
        if value:
            vehicle[key] = value
    return vehicle


def _records_to_df(records: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    remaining = [col for col in df.columns if col not in columns]
    return df[columns + remaining]


def _save_records(records: list[dict[str, Any]], base_path: Path, columns: list[str]) -> None:
    base_path.parent.mkdir(parents=True, exist_ok=True)
    df = _records_to_df(records, columns)
    df.to_csv(base_path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    with open(base_path.with_suffix(".json"), "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    logger.info("Saved %d records to %s.[csv/json]", len(records), base_path)


def _save_errors(errors: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    errors_path = output_dir / "errors.json"
    csv_path = output_dir / "errors.csv"
    with open(errors_path, "w", encoding="utf-8") as handle:
        json.dump(errors, handle, ensure_ascii=False, indent=2)
    pd.DataFrame(errors, columns=["type", "url", "error"]).to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig",
    )
    if errors:
        logger.warning("Errors saved: %s and %s (%d errors)", errors_path, csv_path, len(errors))


def main() -> None:
    """CLI entry point."""
    config = parse_args()
    setup_logging(config.log_dir)
    try:
        asyncio.run(run_pipeline(config))
    except KeyboardInterrupt:
        print("\nInterrupted by user. Progress saved in checkpoints.")
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
