"""Tests for the SQLite producer-consumer pipeline orchestration."""

from __future__ import annotations

import asyncio

import pytest

import src.scraper.pipeline as pipeline
from src.config import ScraperConfig
from src.scraper.browser import TargetClosedError
from src.scraper.state_store import STATUS_DONE, StateStore, VehicleJob


def test_single_writer_persists_records_and_errors(tmp_path):
    async def run():
        store = StateStore(tmp_path / "writer.sqlite3")
        await store.connect()
        await store.start_run("run-1", ScraperConfig(project_root=tmp_path))
        await store.queue_vendor_jobs(
            "run-1",
            [{"url": "https://home.mobile.de/ALPHA", "name": "Alpha"}],
        )
        await store.queue_vehicle_jobs(
            "run-1",
            "https://home.mobile.de/ALPHA",
            "C0000001",
            {"Händler ID": "C0000001"},
            [{"Vehicle_URL": "synthetic://vehicle-1"}],
        )

        queue = asyncio.Queue()
        writer = pipeline.SingleWriter(store, queue, "run-1")
        task = asyncio.create_task(writer.run())
        await queue.put(
            {
                "kind": "vendor_done",
                "url": "https://home.mobile.de/ALPHA",
                "vendor": {"Händler ID": "C0000001", "Händlername": "Alpha"},
            }
        )
        await queue.put(
            {
                "kind": "vehicle_done",
                "url": "synthetic://vehicle-1",
                "vehicle": {"run_id": "run-1", "Händler ID": "C0000001", "Vehicle_URL": "synthetic://vehicle-1"},
            }
        )
        await queue.put({"kind": "error", "stage": "vehicle", "url": "synthetic://bad", "error": "boom"})
        await queue.put(None)
        await queue.join()
        await task

        vendors = await store.export_vendors()
        vehicles = await store.export_vehicles()
        errors = await store.export_errors()
        await store.close()
        return vendors, vehicles, errors

    vendors, vehicles, errors = asyncio.run(run())
    assert vendors[0]["Händlername"] == "Alpha"
    assert vehicles[0]["Vehicle_URL"] == "synthetic://vehicle-1"
    assert errors[0]["error_message"] == "boom"


def test_run_concurrent_pipeline_with_mocked_workers(monkeypatch, tmp_path):
    async def fake_producer_run(self):
        dealers = [
            {"url": "https://home.mobile.de/ALPHA", "name": "Alpha"},
            {"url": "https://home.mobile.de/BETA", "name": "Beta"},
        ]
        jobs = await self.state.queue_vendor_jobs(self.run_id, dealers)
        for job in jobs:
            await self.vendor_queue.put(job)

    async def fake_vendor_worker_run(self):
        while True:
            job = await self.vendor_queue.get()
            try:
                if job is None:
                    return
                await self.state.mark_vendor_processing(job.normalized_vendor_url)
                vendor = {
                    "run_id": self.run_id,
                    "Händler ID": job.haendler_id,
                    "Händlername": job.dealer["name"],
                    "Mobile.de_Links": job.normalized_vendor_url,
                }
                await self.writer_queue.put(
                    {"kind": "vendor_done", "url": job.normalized_vendor_url, "vendor": vendor}
                )
                vehicle_jobs = await self.state.queue_vehicle_jobs(
                    self.run_id,
                    job.normalized_vendor_url,
                    job.haendler_id,
                    {"Händler ID": job.haendler_id, "Händlername": job.dealer["name"]},
                    [{"Vehicle_URL": f"synthetic://{job.haendler_id}", "Markes": "VW"}],
                )
                for vehicle_job in vehicle_jobs:
                    await self.vehicle_queue.put(vehicle_job)
            finally:
                self.vendor_queue.task_done()

    async def fake_vehicle_worker_run(self):
        while True:
            job = await self.vehicle_queue.get()
            try:
                if job is None:
                    return
                await self.state.mark_vehicle_processing(job.vehicle_url)
                await self.writer_queue.put(
                    {
                        "kind": "vehicle_done",
                        "url": job.vehicle_url,
                        "vehicle": {
                            "run_id": self.run_id,
                            "Händler ID": job.haendler_id,
                            "Vehicle_URL": job.vehicle_url,
                            "Markes": job.fallback.get("Markes", ""),
                        },
                    }
                )
            finally:
                self.vehicle_queue.task_done()

    monkeypatch.setattr(pipeline.RegionalDiscoveryProducer, "run", fake_producer_run)
    monkeypatch.setattr(pipeline.VendorWorker, "run", fake_vendor_worker_run)
    monkeypatch.setattr(pipeline.VehicleDetailWorker, "run", fake_vehicle_worker_run)

    config = ScraperConfig(
        project_root=tmp_path,
        pipeline_mode="sqlite",
        vendor_concurrency=2,
        vehicle_detail_concurrency=2,
        max_vendors=2,
        resume=False,
    )
    config.ensure_dirs()

    result = asyncio.run(
        pipeline.run_concurrent_pipeline(
            config,
            run_id="run-1",
            bundesland="Nordrhein-Westfalen",
        )
    )

    assert [vendor["Händler ID"] for vendor in result.vendors] == ["C0000001", "C0000002"]
    assert {vehicle["Vehicle_URL"] for vehicle in result.vehicles} == {
        "synthetic://C0000001",
        "synthetic://C0000002",
    }
    assert result.errors == []

    async def counts():
        store = StateStore(config.sqlite_path)
        await store.connect()
        vendor_status = await store.count_by_status("vendors")
        vehicle_status = await store.count_by_status("vehicle_jobs")
        await store.close()
        return vendor_status, vehicle_status

    vendor_status, vehicle_status = asyncio.run(counts())
    assert vendor_status == {STATUS_DONE: 2}
    assert vehicle_status == {STATUS_DONE: 2}


def test_regional_producer_enqueues_only_limited_dealers(monkeypatch, tmp_path):
    class FakeBrowser:
        def __init__(self, config, **kwargs):
            pass

        async def start(self):
            pass

        async def close(self):
            pass

    class FakeRegionalScraper:
        def __init__(self, browser, config):
            self.last_discovered_count = 32

        async def collect_dealer_entries(self):
            return [
                {"url": f"https://home.mobile.de/DEALER{i:02d}", "name": f"Dealer {i:02d}"}
                for i in range(5)
            ]

    async def run():
        monkeypatch.setattr(pipeline, "BrowserManager", FakeBrowser)
        monkeypatch.setattr(pipeline, "RegionalScraper", FakeRegionalScraper)
        store = StateStore(tmp_path / "producer.sqlite3")
        await store.connect()
        await store.start_run("run-1", ScraperConfig(project_root=tmp_path, max_vendors=5))
        queue = asyncio.Queue()
        producer = pipeline.RegionalDiscoveryProducer(
            ScraperConfig(project_root=tmp_path, max_vendors=5),
            store,
            "run-1",
            queue,
        )
        stats = await producer.run()
        jobs = []
        while not queue.empty():
            jobs.append(await queue.get())
        await store.close()
        return stats, jobs

    stats, jobs = asyncio.run(run())

    assert stats.discovered_vendor_count == 32
    assert stats.enqueued_vendor_count == 5
    assert len(jobs) == 5


def test_state_store_pending_and_exports_are_scoped_to_run_id(tmp_path):
    async def run():
        store = StateStore(tmp_path / "runs.sqlite3")
        await store.connect()
        await store.start_run("old-run", ScraperConfig(project_root=tmp_path))
        old_jobs = await store.queue_vendor_jobs(
            "old-run",
            [{"url": "https://home.mobile.de/OLD", "name": "Old"}],
        )
        await store.save_vendor_done(
            old_jobs[0].normalized_vendor_url,
            {
                "run_id": "old-run",
                "Händler ID": old_jobs[0].haendler_id,
                "Händlername": "Old",
                "Mobile.de_Links": old_jobs[0].normalized_vendor_url,
            },
        )
        await store.start_run("new-run", ScraperConfig(project_root=tmp_path, max_vendors=5))
        pending_before = await store.pending_vendor_jobs("new-run", limit=5)
        new_jobs = await store.queue_vendor_jobs(
            "new-run",
            [
                {"url": f"https://home.mobile.de/NEW{i}", "name": f"New {i}"}
                for i in range(5)
            ],
        )
        pending_after = await store.pending_vendor_jobs("new-run", limit=5)
        old_exports = await store.export_vendors("old-run")
        new_exports = await store.export_vendors("new-run")
        await store.close()
        return pending_before, new_jobs, pending_after, old_exports, new_exports

    pending_before, new_jobs, pending_after, old_exports, new_exports = asyncio.run(run())

    assert pending_before == []
    assert len(new_jobs) == 5
    assert len(pending_after) == 5
    assert len(old_exports) == 1
    assert new_exports == []


def test_vehicle_worker_retries_target_closed_once(monkeypatch):
    if TargetClosedError is None:
        pytest.skip("TargetClosedError is not importable in this Playwright version")

    class FakeBrowser:
        restart_count = 0

        def mark_unhealthy(self, reason=""):
            pass

        async def ensure_started(self):
            self.restart_count += 1

    async def run():
        worker = pipeline.VehicleDetailWorker(
            "vehicle-worker-test",
            ScraperConfig(),
            state=object(),
            run_id="run-1",
            vehicle_queue=asyncio.Queue(),
            writer_queue=asyncio.Queue(),
        )
        calls = 0

        async def fake_process_job(job, browser, vehicle_scraper):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TargetClosedError("Target page, context or browser has been closed")
            await worker.writer_queue.put(
                {"kind": "vehicle_done", "url": job.vehicle_url, "vehicle": {"Vehicle_URL": job.vehicle_url}}
            )

        monkeypatch.setattr(worker, "_process_job", fake_process_job)
        browser = FakeBrowser()
        job = VehicleJob("synthetic://vehicle", "https://home.mobile.de/ALPHA", "C0000001", {}, {})

        await worker._process_job_with_recovery(job, browser, vehicle_scraper=object())

        assert calls == 2
        assert browser.restart_count == 1
        event = await worker.writer_queue.get()
        assert event["kind"] == "vehicle_done"

    asyncio.run(run())


def test_vehicle_worker_records_detail_fetch_failure_and_uses_fallback():
    class FakeState:
        async def mark_vehicle_processing(self, vehicle_url, run_id=""):
            pass

    class FakeBrowser:
        last_status = 503
        last_error = "HTTP 503"
        config = ScraperConfig(browser="chromium")

        async def ensure_started(self):
            return None

    class FakeScraper:
        async def scrape_vehicle(self, vehicle_url, vendor_info, fallback):
            return {
                "Vehicle_URL": vehicle_url,
                "fetch_strategy": "playwright_chromium",
                "fetch_status": 503,
                "fetch_fallback_reason": "HTTP 403",
            }

    async def run():
        writer_queue = asyncio.Queue()
        worker = pipeline.VehicleDetailWorker(
            "vehicle-worker-test",
            ScraperConfig(),
            state=FakeState(),
            run_id="run-1",
            vehicle_queue=asyncio.Queue(),
            writer_queue=writer_queue,
        )
        job = VehicleJob(
            "https://suchen.mobile.de/fahrzeuge/details.html?id=1",
            "https://home.mobile.de/ALPHA",
            "C0000001",
            {"Händler ID": "C0000001"},
            {"Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=1", "Markes": "VW"},
        )
        await worker._process_job(job, FakeBrowser(), FakeScraper())
        events = []
        while not writer_queue.empty():
            events.append(await writer_queue.get())
        return events

    events = asyncio.run(run())

    assert events[0]["kind"] == "error"
    assert events[0]["stage"] == "vehicle_detail_fetch_failed"
    assert events[0]["status_code"] == 503
    assert "HTTP 403" in events[0]["error"]
    assert events[1]["kind"] == "vehicle_done"
    assert events[1]["vehicle"]["vehicle_data_source"] == "listing_fallback"


def test_vehicle_worker_does_not_start_browser_for_listing_fallback_job():
    class FakeState:
        async def mark_vehicle_processing(self, vehicle_url, run_id=""):
            pass

    class FakeBrowser:
        def __init__(self):
            self.started = 0

        async def ensure_started(self):
            self.started += 1

    class FakeScraper:
        async def scrape_vehicle(self, vehicle_url, vendor_info, fallback):
            raise AssertionError("detail scraper should not be called")

    async def run():
        writer_queue = asyncio.Queue()
        worker = pipeline.VehicleDetailWorker(
            "vehicle-worker-test",
            ScraperConfig(detail_policy="missing-required"),
            state=FakeState(),
            run_id="run-1",
            vehicle_queue=asyncio.Queue(),
            writer_queue=writer_queue,
        )
        fallback = {
            "Vehicle_URL": "synthetic://fallback",
            "Markes": "VW",
            "Models": "Golf",
            "Fahrzeugtyp": "PKW",
            "Preis": "1000",
            "Kilometerstand": "1 km",
            "Erstzulassung": "01/2020",
        }
        browser = FakeBrowser()
        job = VehicleJob(
            "synthetic://fallback",
            "https://home.mobile.de/ALPHA",
            "C0000001",
            {"Händler ID": "C0000001"},
            fallback,
        )
        await worker._process_job(job, browser, FakeScraper())
        event = await writer_queue.get()
        return browser.started, event

    started, event = asyncio.run(run())

    assert started == 0
    assert event["kind"] == "vehicle_done"
    assert event["vehicle"]["vehicle_data_source"] == "listing_fallback"
