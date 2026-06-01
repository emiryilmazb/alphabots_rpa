"""Main entry point for the mobile.de scraping and reporting pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import ScraperConfig, parse_args
from src.models import (
    CLASSIFICATION_REQUIRED_FIELDS,
    FINANCING_REQUIRED_FIELDS,
    VEHICLE_BASIC_FIELDS,
    VEHICLE_COLUMNS,
    VEHICLE_TECHNICAL_FIELDS,
    VENDOR_COLUMNS,
)
from src.output.excel_writer import generate_excel
from src.output.word_report import generate_word_report
from src.processing.classification import classify_dataframe
from src.processing.cleaning import clean_dataframes
from src.processing.dashboard import prepare_dashboard
from src.scraper.browser import BrowserManager
from src.scraper.detail_policy import is_real_vehicle_detail_url, should_fetch_vehicle_detail
from src.scraper.parsers import normalize_dealer_url
from src.scraper.pipeline import run_concurrent_pipeline
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

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    config.run_id = run_id
    config.ensure_dirs()
    checkpoint = CheckpointManager(config.checkpoint_dir)
    if config.clear_checkpoints:
        checkpoint.clear_all()

    bundesland = BUNDESLAND_MAP.get(config.state, config.state.replace("-", " ").title())
    errors: list[dict[str, Any]] = []
    dealers_data: list[dict[str, str]] = []
    vendors: list[dict[str, Any]] = []
    all_cars: list[dict[str, Any]] = []


    if not config.overwrite and "runs" in str(config.data_dir):
        logger.warning("OVERWRITE GUARD: Existing files >50KB detected. Using run folder: %s", config.data_dir)
    if config.process_existing:
        logger.info("=" * 60)
        logger.info("TASK 1: REPROCESSING EXISTING DATA (Skipping scrape)")
        logger.info("=" * 60)
        v_file = (config.input_dir_override or config.raw_dir) / "vendors_raw.json"
        c_file = (config.input_dir_override or config.raw_dir) / "cars_raw.json"
        if v_file.exists():
            with open(v_file, "r", encoding="utf-8") as f:
                vendors = json.load(f)
        if c_file.exists():
            with open(c_file, "r", encoding="utf-8") as f:
                all_cars = json.load(f)
    elif config.pipeline_mode == "sqlite":
        try:
            logger.info("=" * 60)
            logger.info("TASK 1: DATA EXTRACTION (sqlite producer-consumer pipeline)")
            logger.info("State: %s (%s)", config.state, bundesland)
            logger.info("Start URL: %s", config.state_page_url.format(page=0))
            logger.info(
                "Concurrency: vendors=%d, vehicles=%d",
                config.vendor_concurrency,
                config.vehicle_detail_concurrency,
            )
            logger.info("=" * 60)
            result = await run_concurrent_pipeline(config, run_id=run_id, bundesland=bundesland)
            vendors = result.vendors
            all_cars = result.vehicles
            config.regional_discovered_count = result.discovered_vendor_count
            config.enqueued_vendor_count = result.enqueued_vendor_count
            config.processed_vendor_count = result.processed_vendor_count
            errors.extend(_normalize_pipeline_errors(result.errors))
        except Exception as exc:
            logger.exception("SQLite pipeline scraping phase failed: %s", exc)
            errors.append(_error_record(run_id, "pipeline", "", str(exc), error_type=exc.__class__.__name__))
    else:
        vendors, all_cars = await _run_legacy_scraping(
            config,
            checkpoint,
            bundesland,
            errors,
        )

    for vendor in vendors:
        vendor.setdefault("run_id", run_id)
    for car in all_cars:
        _finalize_vehicle_record(
            car,
            config,
            str(car.get("source_vendor_url", "")),
            str(car.get("Vehicle_URL") or car.get("source_vehicle_url", "")),
        )

    # Write raw files once at the end (not after every record).
    if getattr(config, "process_existing", False) is False:
        _save_records(vendors, config.raw_dir / "vendors_raw", VENDOR_COLUMNS)
        _save_records(all_cars, config.raw_dir / "cars_raw", VEHICLE_COLUMNS)

    logger.info("=" * 60)
    logger.info("TASK 2: DATA PREPROCESSING")
    logger.info("=" * 60)

    df_vendors_raw = _records_to_df(vendors, VENDOR_COLUMNS)
    df_cars_raw = _records_to_df(all_cars, VEHICLE_COLUMNS)
    df_vendors_clean, df_cars_clean = clean_dataframes(df_vendors_raw, df_cars_raw)
    df_cars_classified = classify_dataframe(df_cars_clean)

    # Add Finanzierung alias (task uses German name) while keeping Financing
    if "Financing" in df_cars_classified.columns:
        df_cars_classified["Finanzierung"] = df_cars_classified["Financing"]
    if "Financing" in df_cars_raw.columns:
        df_cars_raw["Finanzierung"] = df_cars_raw["Financing"]

    config.processed_dir.mkdir(parents=True, exist_ok=True)
    processed_csv = config.processed_dir / "cars_processed.csv"
    processed_json = config.processed_dir / "cars_processed.json"
    df_cars_classified.to_csv(processed_csv, index=False, encoding="utf-8-sig")
    df_cars_classified.to_json(processed_json, orient="records", force_ascii=False, indent=2)
    logger.info("Processed vehicle data saved: %s", processed_csv)

    logger.info("=" * 60)
    logger.info("TASK 3: DASHBOARD GENERATION")
    logger.info("=" * 60)

    finished_at = datetime.now(timezone.utc)
    errors = [_normalize_error_record(error, run_id) for error in errors]
    run_summary = _compute_run_summary(
        run_id, started_at, finished_at, config,
        df_vendors_clean, df_cars_raw, df_cars_classified, errors,
    )
    vendor_coverage = _compute_field_coverage(df_vendors_clean, VENDOR_COLUMNS)
    vehicle_coverage = _compute_field_coverage(df_cars_classified, list(df_cars_classified.columns))

    dashboard = prepare_dashboard(df_vendors_clean, df_cars_classified)
    output_guard_key = "_outputs_generated_for_run_id"
    outputs_generated = False
    if getattr(config, output_guard_key, "") == run_id:
        logger.warning("Output generation already completed for run_id=%s; skipping duplicate generation.", run_id)
    else:
        setattr(config, output_guard_key, run_id)
        outputs_generated = True
        generate_excel(
            config.excel_path, df_vendors_clean, df_cars_raw, df_cars_classified,
            dashboard, run_summary=run_summary,
            vendor_coverage=vendor_coverage, vehicle_coverage=vehicle_coverage,
            errors=errors,
        )
        generate_word_report(
            config.word_path, df_vendors_clean, df_cars_classified, dashboard,
            config.state, errors, run_summary=run_summary,
            vendor_coverage=vendor_coverage, vehicle_coverage=vehicle_coverage,
        )
        _save_errors(errors, config.output_dir)

    completion_guard_key = "_completion_logged_for_run_id"
    if outputs_generated and getattr(config, completion_guard_key, "") != run_id:
        setattr(config, completion_guard_key, run_id)
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE (run_id=%s)", run_id)
        logger.info("  Vendors scraped: %d", len(df_vendors_clean))
        logger.info("  Vehicles scraped: %d", len(df_cars_raw))
        logger.info("  Errors: %d", len(errors))
        logger.info("  Excel: %s", config.excel_path)
        logger.info("  Word:  %s", config.word_path)
        logger.info("=" * 60)


async def _run_legacy_scraping(
    config: ScraperConfig,
    checkpoint: CheckpointManager,
    bundesland: str,
    errors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dealers_data: list[dict[str, str]] = []
    vendors: list[dict[str, Any]] = []
    all_cars: list[dict[str, Any]] = []
    browser = BrowserManager(config, role="legacy")
    try:
        await browser.start()
        logger.info("=" * 60)
        logger.info("TASK 1: DATA EXTRACTION (legacy sequential pipeline)")
        logger.info("State: %s (%s)", config.state, bundesland)
        logger.info("Start URL: %s", config.state_page_url.format(page=0))
        logger.info("=" * 60)

        dealers_data = await _load_or_collect_dealers(config, checkpoint, browser, errors)
        if not dealers_data and _should_retry_headed(config, browser):
            errors.append(
                {
                    "type": "headless_blocked",
                    "url": config.state_page_url.format(page=0),
                    **_browser_error_fields(browser),
                }
            )
            if not errors[-1]["error"]:
                errors[-1]["error"] = "Headless browser was blocked by mobile.de site protection."
            logger.warning(
                "Headless mode was blocked by mobile.de site protection. "
                "Restarting once in headed mode to collect deliverable data."
            )
            await browser.close()
            config.browser_mode = "headed"
            config.headless = False
            browser = BrowserManager(config, role="legacy")
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
            all_cars = await _scrape_vehicles(config, checkpoint, browser, vendors, errors)

    except Exception as exc:
        logger.exception("Pipeline scraping phase failed: %s", exc)
        errors.append(_error_record(config.run_id, "pipeline", "", str(exc), error_type=exc.__class__.__name__))
    finally:
        await browser.close()

    return vendors, all_cars


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
        errors.append(_error_record(config.run_id, "regional", config.state_page_url.format(page=0), str(exc), error_type=exc.__class__.__name__))
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
    loaded_vendors: list[dict[str, Any]] = []
    target_urls = {dealer["url"] for dealer in dealers_data}
    id_by_url = {dealer["url"]: f"C{idx + 1:07d}" for idx, dealer in enumerate(dealers_data)}

    if config.resume and checkpoint.exists("vendors"):
        loaded_vendors = checkpoint.load("vendors") or []
        vendors = []
        for vendor in loaded_vendors:
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

    new_since_checkpoint = 0
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
            new_since_checkpoint += 1
            if config.checkpoint_every > 0 and new_since_checkpoint >= config.checkpoint_every:
                checkpoint.save("vendors", _merge_vendor_checkpoint(loaded_vendors, vendors))
                new_since_checkpoint = 0
            logger.info(
                "[%d/%d] Vendor %s scraped: %s",
                index,
                len(dealers_data),
                haendler_id,
                vendor_data.get("Händlername", ""),
            )
        except Exception as exc:
            logger.exception("Error scraping vendor %s: %s", url, exc)
            errors.append(_error_record(config.run_id, "vendor", url, str(exc), error_type=exc.__class__.__name__))
        await browser.polite_delay()

    # Final checkpoint save after all vendors
    if new_since_checkpoint > 0:
        checkpoint.save("vendors", _merge_vendor_checkpoint(loaded_vendors, vendors))

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
    if not vendors:
        return []

    all_cars: list[dict[str, Any]] = []
    loaded_cars: list[dict[str, Any]] = []
    target_vendor_ids = {str(vendor.get("Händler ID", "")) for vendor in vendors if vendor.get("Händler ID")}
    if config.resume and checkpoint.exists("vehicles"):
        loaded_cars = checkpoint.load("vehicles") or []
        all_cars = [
            car for car in loaded_cars
            if not target_vendor_ids or str(car.get("Händler ID", "")) in target_vendor_ids
        ]
        logger.info("Resumed %d vehicles from checkpoint.", len(all_cars))

    completed_vehicle_urls = {car.get("Vehicle_URL", "") for car in all_cars}
    completed_vendor_vehicles = (
        checkpoint.get_completed_set("vendor_vehicles_done") if config.resume else set()
    )
    vehicle_scraper = VehicleScraper(browser, config)
    detail_pages_disabled = config.skip_vehicle_details or config.detail_policy == "never"
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
            errors.append({"type": "vendor_vehicles", "url": vendor_url, **_browser_error_fields(browser)})
            logger.warning("Cannot load vendor page for vehicles: %s", vendor_url)
            continue

        try:
            vehicle_entries = await vehicle_scraper.collect_vehicle_entries(vendor_url)
            vendor_info = {
                "Händler ID": haendler_id,
                "Händlername": vendor.get("Händlername", ""),
                "PLZ": vendor.get("PLZ", ""),
            }

            new_since_checkpoint = 0
            for vehicle_entry in vehicle_entries:
                vehicle_url = vehicle_entry.get("Vehicle_URL", "")
                if vehicle_url in completed_vehicle_urls:
                    continue
                try:
                    fallback = vehicle_scraper.listing_summaries.get(vehicle_url, vehicle_entry)
                    if not should_fetch_vehicle_detail(
                        config,
                        vehicle_url,
                        fallback,
                        temporarily_disabled=detail_pages_disabled,
                    ):
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
                                            "status_code": browser.last_status,
                                            "screenshot_path": browser.last_screenshot_path,
                                            "html_dump_path": browser.last_html_dump_path,
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
                    _finalize_vehicle_record(car_data, config, vendor_url, vehicle_url)
                    all_cars.append(car_data)
                    completed_vehicle_urls.add(vehicle_url)
                    new_since_checkpoint += 1
                    if config.checkpoint_every > 0 and new_since_checkpoint >= config.checkpoint_every:
                        checkpoint.save("vehicles", _merge_vehicle_checkpoint(loaded_cars, all_cars))
                        logger.info(
                            "Checkpoint: %d vehicles saved (batch every %d).",
                            len(all_cars),
                            config.checkpoint_every,
                        )
                        new_since_checkpoint = 0
                except Exception as exc:
                    logger.exception("Error scraping vehicle %s: %s", vehicle_url, exc)
                    errors.append(_error_record(config.run_id, "vehicle", vehicle_url, str(exc), error_type=exc.__class__.__name__))
                await browser.polite_delay()

            checkpoint.add_completed("vendor_vehicles_done", vendor_url)
        except Exception as exc:
            logger.exception("Error processing vendor vehicles %s: %s", vendor_url, exc)
            errors.append(_error_record(config.run_id, "vendor_vehicles", vendor_url, str(exc), error_type=exc.__class__.__name__))

    # Final checkpoint save after all vehicles
    if all_cars:
        checkpoint.save("vehicles", _merge_vehicle_checkpoint(loaded_cars, all_cars))

    await vehicle_scraper.close()
    return all_cars


def _merge_vendor_checkpoint(
    existing: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge current target vendors without dropping unrelated checkpoint rows."""
    by_url: dict[str, dict[str, Any]] = {}
    for vendor in [*existing, *current]:
        url = normalize_dealer_url(vendor.get("Mobile.de_Links", ""))
        if not url:
            continue
        vendor = {**vendor, "Mobile.de_Links": url}
        existing_vendor = by_url.get(url)
        if existing_vendor is None or _record_score(vendor) >= _record_score(existing_vendor):
            by_url[url] = vendor
    return sorted(by_url.values(), key=lambda item: item.get("Händler ID", ""))


def _merge_vehicle_checkpoint(
    existing: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge current target vehicles without dropping unrelated checkpoint rows."""
    merged = list(existing)
    index_by_url = {
        str(car.get("Vehicle_URL", "")): index
        for index, car in enumerate(merged)
        if car.get("Vehicle_URL")
    }
    for car in current:
        vehicle_url = str(car.get("Vehicle_URL", ""))
        if vehicle_url and vehicle_url in index_by_url:
            merged[index_by_url[vehicle_url]] = car
        else:
            if vehicle_url:
                index_by_url[vehicle_url] = len(merged)
            merged.append(car)
    return merged


def _is_real_vehicle_detail_url(url: str) -> bool:
    return is_real_vehicle_detail_url(url)


def _detail_request_failed(browser: BrowserManager) -> bool:
    if browser.last_status in {403, 429, 500, 502, 503, 504}:
        return True
    last_error = (browser.last_error or "").lower()
    return "access denied" in last_error or "site protection" in last_error


def _browser_error_fields(browser: BrowserManager) -> dict[str, Any]:
    return {
        "error": browser.last_error,
        "error_message": browser.last_error,
        "status_code": browser.last_status,
        "fetch_strategy": "playwright",
        "browser": browser.config.browser,
        "screenshot_path": browser.last_screenshot_path,
        "html_dump_path": browser.last_html_dump_path,
    }


def _normalize_pipeline_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for error in errors:
        normalized.append(
            {
                "type": error.get("type") or error.get("stage", ""),
                "url": error.get("url", ""),
                "error": error.get("error") or error.get("error_message", ""),
                **{
                    key: value
                    for key, value in error.items()
                    if key not in {"type", "stage", "url", "error", "error_message"}
                },
            }
        )
    return normalized


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
            "source_vehicle_url": vehicle_url,
            "vehicle_data_source": "listing_payload",
            "fetch_strategy": "listing_payload",
            "fetch_status": "",
            "parse_status": "fallback",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    for key, value in fallback.items():
        if value:
            vehicle[key] = value
    if vehicle.get("Financing") and not vehicle.get("Finanzierung"):
        vehicle["Finanzierung"] = vehicle["Financing"]
    elif vehicle.get("Finanzierung") and not vehicle.get("Financing"):
        vehicle["Financing"] = vehicle["Finanzierung"]
    return vehicle


def _finalize_vehicle_record(
    vehicle: dict[str, Any],
    config: ScraperConfig,
    vendor_url: str,
    vehicle_url: str,
) -> None:
    """Ensure traceability columns exist without overwriting scraped values."""
    vehicle.setdefault("run_id", config.run_id)
    vehicle.setdefault("source_vendor_url", vendor_url)
    vehicle.setdefault("source_vehicle_url", vehicle_url)
    vehicle.setdefault("scraped_at", datetime.now(timezone.utc).isoformat())
    vehicle.setdefault("parse_status", "ok" if _record_score(vehicle) > 4 else "partial")
    vehicle.setdefault("vehicle_data_source", "detail_page" if vehicle.get("fetch_strategy") else "listing_payload")
    vehicle.setdefault("fetch_strategy", vehicle.get("vehicle_data_source", "listing_payload"))
    vehicle.setdefault("fetch_status", "")
    if vehicle.get("Financing") and not vehicle.get("Finanzierung"):
        vehicle["Finanzierung"] = vehicle["Financing"]
    elif vehicle.get("Finanzierung") and not vehicle.get("Financing"):
        vehicle["Financing"] = vehicle["Finanzierung"]


def _error_record(
    run_id: str,
    stage: str,
    url: str,
    message: str,
    *,
    error_type: str = "",
    status_code: Any = None,
    fetch_strategy: str = "",
    browser: str = "",
    attempt: Any = None,
    screenshot_path: str = "",
    html_dump_path: str = "",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": stage,
        "stage": stage,
        "url": url,
        "status_code": status_code,
        "fetch_strategy": fetch_strategy,
        "browser": browser,
        "attempt": attempt,
        "error_type": error_type,
        "error": message,
        "error_message": message,
        "screenshot_path": screenshot_path,
        "html_dump_path": html_dump_path,
    }


def _normalize_error_record(error: dict[str, Any], run_id: str) -> dict[str, Any]:
    stage = error.get("stage") or error.get("type", "")
    message = error.get("error_message") or error.get("error", "")
    normalized = _error_record(
        run_id=str(error.get("run_id") or run_id),
        stage=str(stage),
        url=str(error.get("url", "")),
        message=str(message),
        error_type=str(error.get("error_type", "")),
        status_code=error.get("status_code"),
        fetch_strategy=str(error.get("fetch_strategy", "")),
        browser=str(error.get("browser", "")),
        attempt=error.get("attempt"),
        screenshot_path=str(error.get("screenshot_path", "")),
        html_dump_path=str(error.get("html_dump_path", "")),
    )
    normalized["timestamp"] = error.get("timestamp") or normalized["timestamp"]
    for key, value in error.items():
        normalized.setdefault(key, value)
    return normalized


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


def _compute_field_coverage(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return per-field non-empty coverage for a DataFrame."""
    unique_columns = list(dict.fromkeys(columns))
    total = len(df)
    rows: list[dict[str, Any]] = []
    for column in unique_columns:
        if column in df.columns and not df.empty:
            present = df[column].map(_has_value).sum()
        else:
            present = 0
        rows.append(
            {
                "field": column,
                "non_empty_count": int(present),
                "total_count": int(total),
                "coverage_pct": round((present / total) * 100, 2) if total else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _has_value(value: Any) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip() not in {"", "None", "nan", "NaN", "<NA>"}


def _coverage_counts_for_fields(df: pd.DataFrame, fields: list[str]) -> tuple[int, int]:
    if df is None or df.empty or not fields:
        return 0, 0
    total = len(df) * len(fields)
    present = 0
    for field in fields:
        if field in df.columns:
            present += int(df[field].map(_has_value).sum())
    return present, total


def _coverage_pct_for_fields(df: pd.DataFrame, fields: list[str]) -> float:
    present, total = _coverage_counts_for_fields(df, fields)
    return round((present / total) * 100, 2) if total else 0.0


def _compute_required_coverage_metrics(
    df_vendors: pd.DataFrame,
    df_cars_processed: pd.DataFrame,
) -> dict[str, float]:
    vendor_present, vendor_total = _coverage_counts_for_fields(df_vendors, VENDOR_COLUMNS)
    basic_present, basic_total = _coverage_counts_for_fields(df_cars_processed, VEHICLE_BASIC_FIELDS)
    technical_present, technical_total = _coverage_counts_for_fields(df_cars_processed, VEHICLE_TECHNICAL_FIELDS)
    financing_present, financing_total = _coverage_counts_for_fields(df_cars_processed, FINANCING_REQUIRED_FIELDS)
    classification_present, classification_total = _coverage_counts_for_fields(
        df_cars_processed,
        CLASSIFICATION_REQUIRED_FIELDS,
    )
    final_present = vendor_present + basic_present + technical_present + financing_present + classification_present
    final_total = vendor_total + basic_total + technical_total + financing_total + classification_total
    return {
        "vendor_required_fields_coverage_pct": round((vendor_present / vendor_total) * 100, 2) if vendor_total else 0.0,
        "vehicle_basic_fields_coverage_pct": round((basic_present / basic_total) * 100, 2) if basic_total else 0.0,
        "vehicle_technical_fields_coverage_pct": round((technical_present / technical_total) * 100, 2) if technical_total else 0.0,
        "financing_fields_coverage_pct": round((financing_present / financing_total) * 100, 2) if financing_total else 0.0,
        "classification_fields_coverage_pct": round((classification_present / classification_total) * 100, 2) if classification_total else 0.0,
        "final_required_fields_coverage_pct": round((final_present / final_total) * 100, 2) if final_total else 0.0,
    }


def _state_label(state: str) -> str:
    return BUNDESLAND_MAP.get(state, state.replace("-", " ").title())


def _compute_run_summary(
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    config: ScraperConfig,
    df_vendors: pd.DataFrame,
    df_cars_raw: pd.DataFrame,
    df_cars_processed: pd.DataFrame,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    duration = finished_at - started_at
    vendor_error_count = sum(1 for e in errors if str(e.get("stage") or e.get("type", "")).startswith("vendor"))
    vehicle_error_count = sum(1 for e in errors if str(e.get("stage") or e.get("type", "")).startswith("vehicle"))
    mode_str = "process_existing" if getattr(config, "process_existing", False) else "scrape"
    extracted_count = len(df_cars_processed)
    avg_sec = duration.total_seconds() / extracted_count if extracted_count > 0 else 0
    veh_per_hour = (extracted_count / duration.total_seconds()) * 3600 if duration.total_seconds() > 0 else 0
    est_20k = 20000 / veh_per_hour if veh_per_hour > 0 else 0
    detail_errors = [
        error for error in errors
        if str(error.get("stage") or error.get("type", "")) == "vehicle_detail_fetch_failed"
    ]
    detail_fetch_403_count = sum(
        1
        for error in detail_errors
        if str(error.get("status_code", "")) == "403"
        or "HTTP 403" in str(error.get("error_message") or error.get("error", ""))
    )
    detail_fetch_503_count = sum(
        1
        for error in detail_errors
        if str(error.get("status_code", "")) == "503"
        or "HTTP 503" in str(error.get("error_message") or error.get("error", ""))
    )
    listing_fallback_used_count = 0
    if "vehicle_data_source" in df_cars_processed.columns:
        listing_fallback_used_count = int(
            df_cars_processed["vehicle_data_source"]
            .astype(str)
            .isin({"listing_fallback", "listing_payload"})
            .sum()
        )
    coverage_metrics = _compute_required_coverage_metrics(df_vendors, df_cars_processed)
    detail_site_blocked_or_503_count = int(getattr(config, "detail_site_blocked_or_503_count", 0) or 0)
    if not detail_site_blocked_or_503_count:
        detail_site_blocked_or_503_count = sum(
            1
            for error in detail_errors
            if str(error.get("error_type", "")) == "detail_site_blocked_or_503"
            or str(error.get("status_code", "")) in {"403", "503"}
            or "HTTP 403" in str(error.get("error_message") or error.get("error", ""))
            or "HTTP 503" in str(error.get("error_message") or error.get("error", ""))
        )
    strict_headless_blocked = any(
        str(error.get("type") or error.get("stage", "")) == "headless_blocked"
        for error in errors
    ) or (
        config.browser_mode == "headless"
        and any(
            str(error.get("status_code", "")) == "403"
            and str(error.get("browser") or "").strip() != ""
            for error in errors
        )
    )

    adaptive_wait_used_count = int(getattr(config, "adaptive_wait_used_count", 0) or 0)
    adaptive_wait_total_ms = int(getattr(config, "adaptive_wait_total_ms", 0) or 0)
    adaptive_wait_avg_ms = adaptive_wait_total_ms / adaptive_wait_used_count if adaptive_wait_used_count > 0 else 0.0

    summary_dict = {
        "run_id": run_id,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round(duration.total_seconds(), 2),
        "adaptive_wait_used_count": adaptive_wait_used_count,
        "adaptive_wait_success_count": int(getattr(config, "adaptive_wait_success_count", 0) or 0),
        "adaptive_wait_timeout_count": int(getattr(config, "adaptive_wait_timeout_count", 0) or 0),
        "adaptive_wait_error_count": int(getattr(config, "adaptive_wait_error_count", 0) or 0),
        "adaptive_wait_total_ms": adaptive_wait_total_ms,
        "adaptive_wait_avg_ms": round(adaptive_wait_avg_ms, 2),
        "adaptive_wait_max_ms": int(getattr(config, "adaptive_wait_max_ms", 0) or 0),
        "target_state": _state_label(config.state),
        "target_state_slug": config.state,
        "search_state": _state_label(config.state),
        "mode": mode_str,
        "pipeline_mode": config.pipeline_mode,
        "browser_mode": config.browser_mode,
        "strict_headless_blocked": bool(strict_headless_blocked),
        "fetch_strategy": config.fetch_strategy,
        "detail_policy": config.detail_policy,
        "detail_open_strategy": str(getattr(config, "detail_open_strategy", "")),
        "vendor_concurrency": config.vendor_concurrency,
        "vehicle_detail_concurrency": config.vehicle_detail_concurrency,
        "regional_discovered_count": int(getattr(config, "regional_discovered_count", 0) or len(df_vendors)),
        "discovered_vendor_count": int(getattr(config, "regional_discovered_count", 0) or len(df_vendors)),
        "enqueued_vendor_count": int(getattr(config, "enqueued_vendor_count", 0) or len(df_vendors)),
        "processed_vendor_count": len(df_vendors),
        "extracted_vehicle_count": extracted_count,
        "error_count": len(errors),
        "warning_count": len(detail_errors),
        "detail_fetch_403_count": detail_fetch_403_count,
        "detail_fetch_503_count": detail_fetch_503_count,
        "detail_fetch_failed_count": len(detail_errors),
        "detail_site_blocked_or_503_count": detail_site_blocked_or_503_count,
        "vehicle_detail_jobs_total": int(getattr(config, "vehicle_detail_jobs_total", 0) or 0),
        "detail_needed_count": int(getattr(config, "detail_needed_count", 0) or 0),
        "detail_skipped_count": int(getattr(config, "detail_skipped_count", 0) or 0),
        "detail_attempted_count": int(getattr(config, "detail_attempted_count", 0) or 0),
        "detail_success_count": int(getattr(config, "detail_success_count", 0) or 0),
        "detail_failed_count": int(getattr(config, "detail_failed_count", 0) or len(detail_errors)),
        "listing_fallback_used_count": listing_fallback_used_count,
        "cookie_modal_visible_count": int(getattr(config, "cookie_modal_visible_count", 0) or 0),
        "cookie_consent_click_count": int(getattr(config, "cookie_consent_click_count", 0) or 0),
        "cookie_modal_remaining_count": int(getattr(config, "cookie_modal_remaining_count", 0) or 0),
        "playwright_browser_opened_count": int(getattr(config, "playwright_browser_opened_count", 0) or 0),
        "regional_browser_opened_count": int(getattr(config, "regional_browser_opened_count", 0) or 0),
        "vendor_browser_opened_count": int(getattr(config, "vendor_browser_opened_count", 0) or 0),
        "vehicle_detail_browser_opened_count": int(getattr(config, "vehicle_detail_browser_opened_count", 0) or 0),
        "active_playwright_browser_count": int(getattr(config, "active_playwright_browser_count", 0) or 0),
        "max_active_playwright_browser_count": int(getattr(config, "max_active_playwright_browser_count", 0) or 0),
        "idle_about_blank_count": int(getattr(config, "idle_about_blank_count", 0) or 0),
        "host_chrome_cdp_used_count": int(getattr(config, "host_chrome_cdp_used_count", 0) or 0),
        "host_chrome_cdp_success_count": int(getattr(config, "host_chrome_cdp_success_count", 0) or 0),
        "host_chrome_cdp_failed_count": int(getattr(config, "host_chrome_cdp_failed_count", 0) or 0),
        "host_chrome_cdp_blocked_count": int(getattr(config, "host_chrome_cdp_blocked_count", 0) or 0),
        "avg_seconds_per_vehicle": round(avg_sec, 2),
        "vehicles_per_hour": round(veh_per_hour, 2),
        "estimated_hours_for_20000_vehicles": round(est_20k, 2),
        **coverage_metrics,
    }

    if getattr(config, "benchmark", False):
        bench_file = config.output_dir / "benchmark_summary.json"
        bench_file.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        with open(bench_file, "w", encoding="utf-8") as f:
            _json.dump(summary_dict, f, indent=2)
        import logging
        logging.getLogger("mobile_de.main").info("=== BENCHMARK RESULT ===")
        logging.getLogger("mobile_de.main").info(_json.dumps(summary_dict, indent=2))

    return summary_dict


def _save_errors(errors: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    errors_path = output_dir / "errors.json"
    csv_path = output_dir / "errors.csv"
    with open(errors_path, "w", encoding="utf-8") as handle:
        json.dump(errors, handle, ensure_ascii=False, indent=2)
    columns = [
        "run_id",
        "timestamp",
        "stage",
        "type",
        "url",
        "status_code",
        "fetch_strategy",
        "browser",
        "attempt",
        "error_type",
        "error_message",
        "error",
        "screenshot_path",
        "html_dump_path",
    ]
    df = pd.DataFrame(errors)
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    remaining = [column for column in df.columns if column not in columns]
    df[columns + remaining].to_csv(csv_path, index=False, encoding="utf-8-sig")
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
