"""Tests for the SQLite producer-consumer pipeline orchestration."""

from __future__ import annotations

import asyncio

import src.scraper.pipeline as pipeline
from src.config import ScraperConfig
from src.scraper.state_store import STATUS_DONE, StateStore


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
