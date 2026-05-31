"""Bounded producer-consumer pipeline backed by SQLite state."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from src.config import ScraperConfig
from src.models import VEHICLE_COLUMNS
from src.scraper.browser import BrowserManager, _is_target_closed_error
from src.scraper.detail_policy import (
    is_real_vehicle_detail_url,
    missing_detail_enrichment_fields,
    should_fetch_vehicle_detail,
)
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
    discovered_vendor_count: int = 0
    enqueued_vendor_count: int = 0
    processed_vendor_count: int = 0


@dataclass
class RegionalDiscoveryStats:
    discovered_vendor_count: int
    enqueued_vendor_count: int


class SingleWriter:
    """Single SQLite writer for completed records and structured errors."""

    def __init__(
        self,
        state: StateStore,
        queue: asyncio.Queue,
        run_id: str,
        flush_every: int = 100,
        expected_vehicles: int = 0,
    ):
        self.state = state
        self.queue = queue
        self.run_id = run_id
        self.flush_every = flush_every
        self.expected_vehicles = max(0, expected_vehicles)
        self.processed_vehicles = 0
        self.start_time = time.time()

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
                    await self.state.mark_vendor_failed(event["url"], event.get("error", ""), self.run_id)
                    await self._record_error("vendor", event)
                elif kind == "vehicle_done":
                    await self.state.save_vehicle_done(event["url"], event["vehicle"])
                    self.processed_vehicles += 1
                    if self.processed_vehicles % self.flush_every == 0:
                        elapsed = time.time() - self.start_time
                        rate = (self.processed_vehicles / elapsed) * 3600 if elapsed > 0 else 0
                        avg_sec = elapsed / self.processed_vehicles if self.processed_vehicles > 0 else 0
                        eta_seconds = 0.0
                        if self.expected_vehicles and rate > 0:
                            remaining = max(0, self.expected_vehicles - self.processed_vehicles)
                            eta_seconds = remaining / (rate / 3600)
                        logger.info(
                            "Processed %d vehicles | vehicles/hour=%.1f | avg_sec_per_vehicle=%.2f | eta_seconds=%.0f",
                            self.processed_vehicles,
                            rate,
                            avg_sec,
                            eta_seconds,
                        )
                elif kind == "vehicle_failed":
                    await self.state.mark_vehicle_failed(event["url"], event.get("error", ""), self.run_id)
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
        browser = BrowserManager(self.config, role="regional")
        try:
            regional = RegionalScraper(browser, self.config)
            dealers = await regional.collect_dealer_entries()
            jobs = await self.state.queue_vendor_jobs(self.run_id, dealers)
            enqueued = 0
            for job in jobs:
                await self.vendor_queue.put(job)
                enqueued += 1
            logger.info(
                "Regional producer discovered %d vendors and enqueued %d vendor jobs.",
                regional.last_discovered_count,
                enqueued,
            )
            return RegionalDiscoveryStats(
                discovered_vendor_count=regional.last_discovered_count,
                enqueued_vendor_count=enqueued,
            )
        finally:
            await browser.close()
            try:
                if 'vehicle_scraper' in locals() and hasattr(vehicle_scraper, 'uc_popup_fetcher'):
                    await vehicle_scraper.close()
            except Exception:
                pass


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
        browser = BrowserManager(self.config, role="vendor")
        started = False
        try:
            vendor_scraper = VendorScraper(browser, self.config)
            vehicle_scraper = VehicleScraper(browser, self.config)

            while True:
                job = await self.vendor_queue.get()
                try:
                    if job is None:
                        return
                    if not started or getattr(browser, '_browser', None) is None or not browser._browser.is_connected():
                        if started:
                            logger.info(f"{self.name}: Browser seems closed/poisoned. Restarting fresh browser.")
                            try:
                                await browser.close()
                            except:
                                pass
                        await browser.start()
                        started = True
                    elif not browser.is_healthy:
                        await browser.ensure_started()
                    await self._process_job_with_recovery(job, browser, vendor_scraper, vehicle_scraper)
                finally:
                    self.vendor_queue.task_done()
        finally:
            await browser.close()
            try:
                if 'vehicle_scraper' in locals() and hasattr(vehicle_scraper, 'uc_popup_fetcher'):
                    await vehicle_scraper.close()
            except Exception:
                pass

    async def _process_job_with_recovery(
        self,
        job: VendorJob,
        browser: BrowserManager,
        vendor_scraper: VendorScraper,
        vehicle_scraper: VehicleScraper,
    ) -> None:
        for attempt in (1, 2):
            try:
                await self._process_job(job, browser, vendor_scraper, vehicle_scraper)
                return
            except Exception as exc:
                if _is_target_closed_error(exc) and attempt == 1:
                    logger.warning(
                        "%s TargetClosedError for vendor %s: %s. Restarting browser and retrying once.",
                        self.name,
                        job.normalized_vendor_url,
                        exc,
                    )
                    browser.mark_unhealthy(str(exc))
                    try:
                        await browser.ensure_started()
                    except Exception as restart_exc:
                        logger.warning(
                            "%s failed to restart browser for vendor %s: %s.",
                            self.name,
                            job.normalized_vendor_url,
                            restart_exc,
                        )
                        await self.writer_queue.put(
                            {
                                "kind": "vendor_failed",
                                "url": job.normalized_vendor_url,
                                "error": str(restart_exc),
                                "error_type": restart_exc.__class__.__name__,
                            }
                        )
                        return
                    continue
                if _is_target_closed_error(exc):
                    logger.warning(
                        "%s TargetClosedError retry failed for vendor %s: %s.",
                        self.name,
                        job.normalized_vendor_url,
                        exc,
                    )
                else:
                    logger.exception("%s failed vendor %s: %s", self.name, job.normalized_vendor_url, exc)
                await self.writer_queue.put(
                    {
                        "kind": "vendor_failed",
                        "url": job.normalized_vendor_url,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )
                return

    async def _process_job(
        self,
        job: VendorJob,
        browser: BrowserManager,
        vendor_scraper: VendorScraper,
        vehicle_scraper: VehicleScraper,
    ) -> None:
        await self.state.mark_vendor_processing(job.normalized_vendor_url, self.run_id)
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
            # TargetClosedError: log but don't poison the worker for subsequent jobs
            if _is_target_closed_error(exc):
                browser.mark_unhealthy(str(exc))
                raise
            else:
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
        browser = BrowserManager(self.config, role="vehicle_detail")
        try:
            vehicle_scraper = VehicleScraper(browser, self.config)
            while True:
                job = await self._get_next_job(browser)
                try:
                    if job is None:
                        return
                    await self._process_job_with_recovery(job, browser, vehicle_scraper)
                finally:
                    self.vehicle_queue.task_done()
        finally:
            await browser.close()
            try:
                if 'vehicle_scraper' in locals() and hasattr(vehicle_scraper, 'uc_popup_fetcher'):
                    await vehicle_scraper.close()
            except Exception:
                pass

    async def _get_next_job(self, browser: BrowserManager) -> VehicleJob | None:
        idle_timeout = float(getattr(self.config, "idle_browser_timeout_seconds", 0) or 0)
        if idle_timeout <= 0:
            return await self.vehicle_queue.get()
        while True:
            try:
                return await asyncio.wait_for(self.vehicle_queue.get(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                if browser.has_open_browser:
                    logger.info(
                        "%s closing idle vehicle-detail browser after %.1fs without a job.",
                        self.name,
                        idle_timeout,
                    )
                    await browser.close()

    async def _process_job_with_recovery(
        self,
        job: VehicleJob,
        browser: BrowserManager,
        vehicle_scraper: VehicleScraper,
    ) -> None:
        for attempt in (1, 2):
            try:
                await self._process_job(job, browser, vehicle_scraper)
                return
            except Exception as exc:
                if _is_target_closed_error(exc) and attempt == 1:
                    logger.warning(
                        "%s TargetClosedError for vehicle %s: %s. Restarting browser and retrying once.",
                        self.name,
                        job.vehicle_url,
                        exc,
                    )
                    browser.mark_unhealthy(str(exc))
                    try:
                        await browser.ensure_started()
                    except Exception as restart_exc:
                        logger.warning(
                            "%s failed to restart browser for vehicle %s: %s.",
                            self.name,
                            job.vehicle_url,
                            restart_exc,
                        )
                        await self.writer_queue.put(
                            {
                                "kind": "vehicle_failed",
                                "url": job.vehicle_url,
                                "error": str(restart_exc),
                                "error_type": restart_exc.__class__.__name__,
                            }
                        )
                        return
                    continue
                if _is_target_closed_error(exc):
                    logger.warning(
                        "%s TargetClosedError retry failed for vehicle %s: %s.",
                        self.name,
                        job.vehicle_url,
                        exc,
                    )
                else:
                    logger.exception("%s failed vehicle %s: %s", self.name, job.vehicle_url, exc)
                await self.writer_queue.put(
                    {
                        "kind": "vehicle_failed",
                        "url": job.vehicle_url,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )
                return

    async def _process_job(
        self,
        job: VehicleJob,
        browser: BrowserManager,
        vehicle_scraper: VehicleScraper,
    ) -> None:
        await self.state.mark_vehicle_processing(job.vehicle_url, self.run_id)
        try:
            _increment_config_counter(self.config, "vehicle_detail_jobs_total")
            detail_needed = should_fetch_vehicle_detail(self.config, job.vehicle_url, job.fallback)
            _record_uc_popup_decision(self.config, job.vehicle_url, job.fallback, detail_needed)
            if not detail_needed:
                _increment_config_counter(self.config, "detail_skipped_count")
                vehicle = _vehicle_from_fallback(job.vendor_info, job.vehicle_url, job.fallback)
            else:
                _increment_config_counter(self.config, "detail_needed_count")
                _increment_config_counter(self.config, "detail_attempted_count")
                if getattr(self.config, "detail_open_strategy", "") == "uc-popup":
                    _increment_config_counter(self.config, "uc_popup_attempted_count")
                fallback = {**job.fallback, "source_vendor_url": job.normalized_vendor_url}
                vehicle = await vehicle_scraper.scrape_vehicle(
                    job.vehicle_url,
                    job.vendor_info,
                    fallback,
                )
                status_code = _detail_status_code(browser, vehicle)
                error_msg = getattr(browser, 'last_error', '')
                is_blocked = (status_code in {403, 503}) or "blocked_or_503" in error_msg or "edgesuite" in error_msg.lower() or _detail_request_failed(browser, vehicle)

                if is_blocked:
                    if (status_code in {403, 503}) or "blocked_or_503" in error_msg or "edgesuite" in error_msg.lower():
                        if status_code == 403:
                            _increment_config_counter(self.config, "detail_fetch_403_count")
                        if status_code == 503:
                            _increment_config_counter(self.config, "detail_fetch_503_count")
                        _increment_config_counter(self.config, "detail_fetch_failed_count")
                        _increment_config_counter(self.config, "listing_fallback_used_count")
                        _increment_config_counter(self.config, "detail_site_blocked_or_503_count")
                        _increment_config_counter(self.config, "detail_browser_closed_after_failure_count")
                        try:
                            await browser.close()
                        except Exception:
                            pass
                    else:
                        _increment_config_counter(self.config, "detail_failed_count")

                    failure_message = _detail_failure_message(browser, vehicle) or error_msg
                    await self.writer_queue.put(
                        {
                            "kind": "error",
                            "stage": "vehicle_detail_fetch_failed",
                            "url": job.vehicle_url,
                            "status_code": status_code,
                            "error": failure_message,
                            "error_message": failure_message,
                            "fetch_strategy": vehicle.get("fetch_strategy", ""),
                            "browser": browser.config.browser,
                            "error_type": "detail_site_blocked_or_503" if "edgesuite" in error_msg.lower() or status_code in {403, 503} else "detail_fetch_failed",
                            "detail_open_strategy": self.config.detail_open_strategy,
                            "detail_status": vehicle.get("detail_status", ""),
                            "detail_failure_reason": vehicle.get("detail_failure_reason", ""),
                            "html_dump_path": vehicle.get("detail_artifact_html_path", ""),
                            "screenshot_path": vehicle.get("detail_artifact_screenshot_path", ""),
                        }
                    )
                    fallback_vehicle = _vehicle_from_fallback(job.vendor_info, job.vehicle_url, job.fallback)
                    _copy_detail_metadata(fallback_vehicle, vehicle)
                    vehicle = fallback_vehicle
                else:
                    _increment_config_counter(self.config, "detail_success_count")
            vehicle["run_id"] = self.run_id
            vehicle.setdefault("source_vendor_url", job.normalized_vendor_url)
            vehicle.setdefault("source_vehicle_url", job.vehicle_url)
            vehicle.setdefault("parse_status", "ok")
            await self.writer_queue.put(
                {"kind": "vehicle_done", "url": job.vehicle_url, "vehicle": vehicle}
            )
        except Exception as exc:
            if _is_target_closed_error(exc):
                browser.mark_unhealthy(str(exc))
                raise
            else:
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
    await state.requeue_processing_jobs(run_id)

    vendor_queue: asyncio.Queue = asyncio.Queue(maxsize=config.vendor_concurrency * 2)
    vehicle_queue: asyncio.Queue = asyncio.Queue(maxsize=config.vehicle_detail_concurrency * 4)
    writer_queue: asyncio.Queue = asyncio.Queue()
    expected_vehicles = (
        config.max_vendors * config.max_cars_per_vendor
        if config.max_vendors > 0 and config.max_cars_per_vendor > 0
        else 0
    )
    writer = SingleWriter(state, writer_queue, run_id, config.flush_every, expected_vehicles)
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
        pending_vehicles = await state.pending_vehicle_jobs(run_id)
        for job in pending_vehicles:
            await vehicle_queue.put(job)
        if pending_vehicles:
            logger.info("Requeued %d pending vehicle jobs.", len(pending_vehicles))

        discovered_vendor_count = 0
        enqueued_vendor_count = 0
        pending_vendors = await state.pending_vendor_jobs(run_id, limit=config.max_vendors)
        if pending_vendors:
            for job in pending_vendors:
                await vendor_queue.put(job)
            enqueued_vendor_count = len(pending_vendors)
            discovered_vendor_count = len(pending_vendors)
            logger.info("Requeued %d pending vendor jobs for run_id=%s.", len(pending_vendors), run_id)
        else:
            stats = await RegionalDiscoveryProducer(config, state, run_id, vendor_queue).run()
            if stats is None:
                enqueued_vendor_count = vendor_queue.qsize()
                discovered_vendor_count = enqueued_vendor_count
            else:
                discovered_vendor_count = stats.discovered_vendor_count
                enqueued_vendor_count = stats.enqueued_vendor_count

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
        vendors = await state.export_vendors(run_id)
        vehicles = await state.export_vehicles(run_id)
        errors = await state.export_errors(run_id)
        return PipelineResult(
            vendors=vendors,
            vehicles=vehicles,
            errors=errors,
            discovered_vendor_count=discovered_vendor_count,
            enqueued_vendor_count=enqueued_vendor_count,
            processed_vendor_count=len(vendors),
        )
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


def _detail_request_failed(browser: BrowserManager, vehicle: dict[str, Any] | None = None) -> bool:
    status_code = _detail_status_code(browser, vehicle or {})
    if status_code in {403, 429, 500, 502, 503, 504}:
        return True
    last_error = (browser.last_error or "").lower()
    vehicle_error = " ".join(
        str((vehicle or {}).get(key, ""))
        for key in ["fetch_fallback_reason", "parse_status", "fetch_status"]
    ).lower()
    combined = f"{last_error} {vehicle_error}"
    if "access denied" in combined or "site protection" in combined:
        return True
    vehicle = vehicle or {}
    if str(vehicle.get("fetch_strategy", "")) == "uc-popup":
        return str(vehicle.get("detail_status", "")) != "real_detail_page"
    failed_statuses = {
        "fetch_failed",
        "stale_or_not_visible",
        "stale_or_home_redirect",
        "home_redirect",
        "home_redirect",
        "error_page",
        "blank_page",
        "wrong_tab_capture",
        "popup_capture_failed",
        "uc_dependency_missing",
    }
    return str(vehicle.get("detail_status", "")) in failed_statuses


def _detail_status_code(browser: BrowserManager, vehicle: dict[str, Any] | None = None) -> int | None:
    status = browser.last_status
    if status:
        return int(status)
    raw_status = (vehicle or {}).get("fetch_status", "")
    try:
        return int(raw_status)
    except (TypeError, ValueError):
        return None


def _browser_error_fields(browser: BrowserManager) -> dict[str, Any]:
    return {
        "error": browser.last_error,
        "status_code": browser.last_status,
        "screenshot_path": browser.last_screenshot_path,
        "html_dump_path": browser.last_html_dump_path,
    }


def _detail_failure_message(browser: BrowserManager, vehicle: dict[str, Any]) -> str:
    parts = ["Vehicle detail fetch failed; continuing with listing fallback."]
    fallback_reason = str(vehicle.get("fetch_fallback_reason", "")).strip()
    if fallback_reason:
        parts.append(f"fallback_reason={fallback_reason}")
    detail_status = str(vehicle.get("detail_status", "")).strip()
    if detail_status:
        parts.append(f"detail_status={detail_status}")
    detail_failure_reason = str(vehicle.get("detail_failure_reason", "")).strip()
    if detail_failure_reason:
        parts.append(f"detail_failure_reason={detail_failure_reason}")
    status_code = _detail_status_code(browser, vehicle)
    if status_code:
        parts.append(f"final_status=HTTP {status_code}")
    if browser.last_error:
        parts.append(f"last_error={browser.last_error}")
    return " ".join(parts)


def _copy_detail_metadata(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in [
        "fetch_strategy",
        "fetch_status",
        "fetch_fallback_reason",
        "detail_data_source",
        "detail_strategy_used",
        "detail_status",
        "detail_failure_reason",
        "detail_artifact_html_path",
        "detail_artifact_screenshot_path",
        "detail_target_fields_extracted_count",
    ]:
        value = source.get(key)
        if value not in (None, ""):
            target[key] = value
    target["vehicle_data_source"] = "listing_fallback"


def _increment_config_counter(config: ScraperConfig, name: str, amount: int = 1) -> None:
    setattr(config, name, int(getattr(config, name, 0) or 0) + amount)


def _record_uc_popup_decision(
    config: ScraperConfig,
    vehicle_url: str,
    fallback: dict[str, Any] | None,
    detail_needed: bool,
) -> None:
    if getattr(config, "detail_open_strategy", "") != "uc-popup":
        return
    if config.skip_vehicle_details or config.detail_policy == "never":
        return
    if not is_real_vehicle_detail_url(vehicle_url):
        return
    if config.detail_policy != "missing-required":
        return

    missing_targets = missing_detail_enrichment_fields(fallback)
    if missing_targets and detail_needed:
        _increment_config_counter(config, "uc_popup_eligible_count")
    elif not missing_targets:
        _increment_config_counter(config, "uc_popup_skipped_not_needed_count")


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
