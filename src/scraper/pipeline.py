"""Bounded producer-consumer pipeline backed by SQLite state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from src.config import ScraperConfig
from src.models import VEHICLE_COLUMNS
from src.scraper.browser import BrowserManager
from src.scraper.detail_policy import is_real_vehicle_detail_url, should_fetch_vehicle_detail
from src.scraper.parsers import normalize_dealer_url
from src.scraper.regional_scraper import RegionalScraper
from src.scraper.state_store import (
    STATUS_DONE,
    StateStore,
    VehicleJob,
    VendorJob,
    config_hash,
    utc_now,
)
from src.scraper.vehicle_scraper import VehicleScraper
from src.scraper.vendor_scraper import VendorScraper

logger = logging.getLogger("mobile_de.pipeline")


@dataclass
class PipelineResult:
    vendors: list[dict[str, Any]]
    vehicles: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class SingleWriter:
    """Single SQLite writer for completed records and structured errors."""

    def __init__(self, state: StateStore, queue: asyncio.Queue, run_id: str):
        self.state = state
        self.queue = queue
        self.run_id = run_id

    async def run(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                if event is None:
                    return
                kind = event.get("kind")
                if kind == "vendor_done":
                    await self.state.save_vendor_done(event["url"], event["vendor"])
                elif kind == "vendor_failed":
                    await self.state.mark_vendor_failed(event["url"], event.get("error", ""))
                    await self._record_error("vendor", event)
                elif kind == "vehicle_done":
                    await self.state.save_vehicle_done(event["url"], event["vehicle"])
                elif kind == "vehicle_failed":
                    await self.state.mark_vehicle_failed(event["url"], event.get("error", ""))
                    await self._record_error("vehicle", event)
                elif kind == "error":
                    await self._record_error(event.get("stage", "pipeline"), event)
            finally:
                self.queue.task_done()

    async def _record_error(self, stage: str, event: dict[str, Any]) -> None:
        error = {
            "run_id": self.run_id,
            "timestamp": utc_now(),
            "stage": stage,
            "url": event.get("url", ""),
            "status_code": event.get("status_code"),
            "fetch_strategy": event.get("fetch_strategy", ""),
            "browser": event.get("browser", ""),
            "attempt": event.get("attempt"),
            "error_type": event.get("error_type", ""),
            "error_message": event.get("error_message") or event.get("error", ""),
            "screenshot_path": event.get("screenshot_path", ""),
            "html_dump_path": event.get("html_dump_path", ""),
        }
        await self.state.record_error(error)


class RegionalDiscoveryProducer:
    """Collect regional vendor URLs and enqueue durable vendor jobs."""

    def __init__(
        self,
        config: ScraperConfig,
        state: StateStore,
        run_id: str,
        vendor_queue: asyncio.Queue,
    ):
        self.config = config
        self.state = state
        self.run_id = run_id
        self.vendor_queue = vendor_queue

    async def run(self) -> None:
        browser = BrowserManager(self.config)
        try:
            await browser.start()
            regional = RegionalScraper(browser, self.config)
            enqueued = 0

            async def enqueue_dealer(dealer: dict[str, str]) -> None:
                nonlocal enqueued
                jobs = await self.state.queue_vendor_jobs(self.run_id, [dealer])
                for job in jobs:
                    await self.vendor_queue.put(job)
                    enqueued += 1

            await regional.collect_dealer_entries(on_dealer=enqueue_dealer)
            logger.info("Regional producer enqueued %d vendor jobs.", enqueued)
        finally:
            await browser.close()


class VendorWorker:
    """Scrape vendors and enqueue vehicle jobs. Owns one browser/page."""

    def __init__(
        self,
        name: str,
        config: ScraperConfig,
        state: StateStore,
        run_id: str,
        bundesland: str,
        vendor_queue: asyncio.Queue,
        vehicle_queue: asyncio.Queue,
        writer_queue: asyncio.Queue,
    ):
        self.name = name
        self.config = config
        self.state = state
        self.run_id = run_id
        self.bundesland = bundesland
        self.vendor_queue = vendor_queue
        self.vehicle_queue = vehicle_queue
        self.writer_queue = writer_queue

    async def run(self) -> None:
        browser = BrowserManager(self.config)
        try:
            await browser.start()
            vendor_scraper = VendorScraper(browser, self.config)
            vehicle_scraper = VehicleScraper(browser, self.config)

            while True:
                job = await self.vendor_queue.get()
                try:
                    if job is None:
                        return
                    await self._process_job(job, browser, vendor_scraper, vehicle_scraper)
                finally:
                    self.vendor_queue.task_done()
        finally:
            await browser.close()

    async def _process_job(
        self,
        job: VendorJob,
        browser: BrowserManager,
        vendor_scraper: VendorScraper,
        vehicle_scraper: VehicleScraper,
    ) -> None:
        await self.state.mark_vendor_processing(job.normalized_vendor_url)
        try:
            vendor = await vendor_scraper.scrape_vendor(job.dealer, self.bundesland)
            vendor["Händler ID"] = job.haendler_id
            vendor["Mobile.de_Links"] = normalize_dealer_url(
                vendor.get("Mobile.de_Links", job.normalized_vendor_url)
            ) or job.normalized_vendor_url
            vendor["run_id"] = self.run_id
            await self.writer_queue.put(
                {"kind": "vendor_done", "url": job.normalized_vendor_url, "vendor": vendor}
            )

            vendor_url = normalize_dealer_url(vendor.get("Mobile.de_Links", job.normalized_vendor_url))
            vendor_info = {
                "Händler ID": job.haendler_id,
                "Händlername": vendor.get("Händlername", ""),
                "PLZ": vendor.get("PLZ", ""),
            }

            if not await browser.safe_goto(vendor_url):
                await self.writer_queue.put(
                    {
                        "kind": "error",
                        "stage": "vendor_vehicles",
                        "url": vendor_url,
                        **_browser_error_fields(browser),
                    }
                )
                return

            entries = await vehicle_scraper.collect_vehicle_entries(vendor_url)
            vehicle_jobs = await self.state.queue_vehicle_jobs(
                self.run_id,
                job.normalized_vendor_url,
                job.haendler_id,
                vendor_info,
                entries,
            )
            for vehicle_job in vehicle_jobs:
                await self.vehicle_queue.put(vehicle_job)
            logger.info(
                "%s enqueued %d vehicle jobs for %s.",
                self.name,
                len(vehicle_jobs),
                job.haendler_id,
            )
        except Exception as exc:
            logger.exception("%s failed vendor %s: %s", self.name, job.normalized_vendor_url, exc)
            await self.writer_queue.put(
                {
                    "kind": "vendor_failed",
                    "url": job.normalized_vendor_url,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                }
            )


class VehicleDetailWorker:
    """Scrape vehicle detail jobs. Owns one browser/page."""

    def __init__(
        self,
        name: str,
        config: ScraperConfig,
        state: StateStore,
        run_id: str,
        vehicle_queue: asyncio.Queue,
        writer_queue: asyncio.Queue,
    ):
        self.name = name
        self.config = config
        self.state = state
        self.run_id = run_id
        self.vehicle_queue = vehicle_queue
        self.writer_queue = writer_queue

    async def run(self) -> None:
        browser = BrowserManager(self.config)
        try:
            await browser.start()
            vehicle_scraper = VehicleScraper(browser, self.config)
            while True:
                job = await self.vehicle_queue.get()
                try:
                    if job is None:
                        return
                    await self._process_job(job, browser, vehicle_scraper)
                finally:
                    self.vehicle_queue.task_done()
        finally:
            await browser.close()

    async def _process_job(
        self,
        job: VehicleJob,
        browser: BrowserManager,
        vehicle_scraper: VehicleScraper,
    ) -> None:
        await self.state.mark_vehicle_processing(job.vehicle_url)
        try:
            if not should_fetch_vehicle_detail(self.config, job.vehicle_url, job.fallback):
                vehicle = _vehicle_from_fallback(job.vendor_info, job.vehicle_url, job.fallback)
            else:
                vehicle = await vehicle_scraper.scrape_vehicle(
                    job.vehicle_url,
                    job.vendor_info,
                    job.fallback,
                )
                if _detail_request_failed(browser):
                    vehicle = _vehicle_from_fallback(job.vendor_info, job.vehicle_url, job.fallback)
            vehicle["run_id"] = self.run_id
            vehicle.setdefault("source_vendor_url", job.normalized_vendor_url)
            vehicle.setdefault("source_vehicle_url", job.vehicle_url)
            vehicle.setdefault("parse_status", "ok")
            await self.writer_queue.put(
                {"kind": "vehicle_done", "url": job.vehicle_url, "vehicle": vehicle}
            )
        except Exception as exc:
            logger.exception("%s failed vehicle %s: %s", self.name, job.vehicle_url, exc)
            await self.writer_queue.put(
                {
                    "kind": "vehicle_failed",
                    "url": job.vehicle_url,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                }
            )


async def run_concurrent_pipeline(
    config: ScraperConfig,
    *,
    run_id: str,
    bundesland: str,
) -> PipelineResult:
    """Run the SQLite-backed bounded producer-consumer pipeline."""
    state = StateStore(config.sqlite_path)
    if config.clear_state or not config.resume:
        await state.clear()
    await state.connect()
    if config.resume:
        previous_hash = await state.latest_config_hash(config.state)
        current_hash = config_hash(config)
        if previous_hash and previous_hash != current_hash and not config.force_resume:
            await state.close()
            raise RuntimeError(
                "SQLite resume config hash mismatch. Re-run with --force-resume true "
                "or --clean-run true to start from a clean state."
            )
    await state.start_run(run_id, config)
    await state.requeue_processing_jobs()

    vendor_queue: asyncio.Queue = asyncio.Queue(maxsize=config.vendor_concurrency * 2)
    vehicle_queue: asyncio.Queue = asyncio.Queue(maxsize=config.vehicle_detail_concurrency * 4)
    writer_queue: asyncio.Queue = asyncio.Queue()
    writer = SingleWriter(state, writer_queue, run_id)
    writer_task = asyncio.create_task(writer.run(), name="single-writer")

    vendor_workers = [
        asyncio.create_task(
            VendorWorker(
                f"vendor-worker-{idx + 1}",
                config,
                state,
                run_id,
                bundesland,
                vendor_queue,
                vehicle_queue,
                writer_queue,
            ).run(),
            name=f"vendor-worker-{idx + 1}",
        )
        for idx in range(config.vendor_concurrency)
    ]
    vehicle_workers = [
        asyncio.create_task(
            VehicleDetailWorker(
                f"vehicle-worker-{idx + 1}",
                config,
                state,
                run_id,
                vehicle_queue,
                writer_queue,
            ).run(),
            name=f"vehicle-worker-{idx + 1}",
        )
        for idx in range(config.vehicle_detail_concurrency)
    ]

    try:
        pending_vehicles = await state.pending_vehicle_jobs()
        for job in pending_vehicles:
            await vehicle_queue.put(job)
        if pending_vehicles:
            logger.info("Requeued %d pending vehicle jobs.", len(pending_vehicles))

        pending_vendors = await state.pending_vendor_jobs(limit=config.max_vendors)
        if pending_vendors:
            for job in pending_vendors:
                await vendor_queue.put(job)
            logger.info("Requeued %d pending vendor jobs.", len(pending_vendors))
        else:
            await RegionalDiscoveryProducer(config, state, run_id, vendor_queue).run()

        for _ in vendor_workers:
            await vendor_queue.put(None)
        await vendor_queue.join()
        await asyncio.gather(*vendor_workers)

        await vehicle_queue.join()
        for _ in vehicle_workers:
            await vehicle_queue.put(None)
        await asyncio.gather(*vehicle_workers)

        await writer_queue.put(None)
        await writer_queue.join()
        await writer_task

        await state.finish_run(run_id, STATUS_DONE)
        vendors = await state.export_vendors()
        vehicles = await state.export_vehicles()
        errors = await state.export_errors()
        return PipelineResult(vendors=vendors, vehicles=vehicles, errors=errors)
    except Exception:
        for task in [*vendor_workers, *vehicle_workers, writer_task]:
            task.cancel()
        await state.finish_run(run_id, "failed")
        raise
    finally:
        await state.close()


def _prepare_dealers(dealers: list[dict[str, str]], max_vendors: int) -> list[dict[str, str]]:
    by_url: dict[str, dict[str, str]] = {}
    for dealer in dealers:
        url = normalize_dealer_url(dealer.get("url", ""))
        if not url:
            continue
        by_url[url] = {**dealer, "url": url}
    prepared = sorted(by_url.values(), key=lambda item: item["url"].lower())
    return prepared[:max_vendors] if max_vendors > 0 else prepared


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
        "status_code": browser.last_status,
        "screenshot_path": browser.last_screenshot_path,
        "html_dump_path": browser.last_html_dump_path,
    }


def _vehicle_from_fallback(
    vendor_info: dict[str, Any],
    vehicle_url: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    vehicle = {col: "" for col in VEHICLE_COLUMNS}
    vehicle.update(
        {
            "Händler ID": vendor_info.get("Händler ID", ""),
            "Händlername": vendor_info.get("Händlername", ""),
            "PLZ": vendor_info.get("PLZ", ""),
            "Vehicle_URL": vehicle_url,
            "source_vehicle_url": vehicle_url,
            "vehicle_data_source": "listing_fallback",
            "fetch_strategy": "listing_payload",
            "parse_status": "fallback",
        }
    )
    for key, value in fallback.items():
        if value:
            vehicle[key] = value
    return vehicle
