"""Tests for SQLite durable scraper state."""

from __future__ import annotations

import sqlite3

from src.config import ScraperConfig
from src.scraper.state_store import (
    STATUS_DONE,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    StateStore,
)


async def _new_store(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    await store.connect()
    return store


def test_vendor_id_determinism_and_export(tmp_path):
    async def run():
        store = await _new_store(tmp_path)
        config = ScraperConfig(project_root=tmp_path)
        await store.start_run("run-1", config)
        dealers = [
            {"url": "https://home.mobile.de/BETA", "name": "Beta"},
            {"url": "https://home.mobile.de/ALPHA", "name": "Alpha"},
        ]
        jobs = await store.queue_vendor_jobs("run-1", dealers)
        assert {job.normalized_vendor_url: job.haendler_id for job in jobs} == {
            "https://home.mobile.de/ALPHA": "C0000001",
            "https://home.mobile.de/BETA": "C0000002",
        }

        # Requeueing the same URLs in another order keeps the stored IDs.
        jobs_again = await store.queue_vendor_jobs("run-1", list(reversed(dealers)))
        assert {job.normalized_vendor_url: job.haendler_id for job in jobs_again} == {
            "https://home.mobile.de/ALPHA": "C0000001",
            "https://home.mobile.de/BETA": "C0000002",
        }

        await store.save_vendor_done(
            "https://home.mobile.de/ALPHA",
            {"Händler ID": "C0000001", "Händlername": "Alpha", "Mobile.de_Links": "https://home.mobile.de/ALPHA"},
        )
        vendors = await store.export_vendors()
        await store.close()
        return vendors

    import asyncio

    vendors = asyncio.run(run())
    assert vendors == [
        {"Händler ID": "C0000001", "Händlername": "Alpha", "Mobile.de_Links": "https://home.mobile.de/ALPHA"}
    ]


def test_vendor_id_incremental_queue_is_stable(tmp_path):
    async def run():
        store = await _new_store(tmp_path)
        config = ScraperConfig(project_root=tmp_path)
        await store.start_run("run-1", config)
        [first] = await store.queue_vendor_jobs(
            "run-1",
            [{"url": "https://home.mobile.de/ALPHA", "name": "Alpha"}],
        )
        [second] = await store.queue_vendor_jobs(
            "run-1",
            [{"url": "https://home.mobile.de/BETA", "name": "Beta"}],
        )
        [first_again] = await store.queue_vendor_jobs(
            "run-1",
            [{"url": "https://home.mobile.de/ALPHA", "name": "Alpha"}],
        )
        await store.close()
        return first.haendler_id, second.haendler_id, first_again.haendler_id

    import asyncio

    assert asyncio.run(run()) == ("C0000001", "C0000002", "C0000001")


def test_requeue_processing_jobs_for_resume(tmp_path):
    async def run():
        store = await _new_store(tmp_path)
        await store.start_run("run-1", ScraperConfig(project_root=tmp_path))
        [vendor_job] = await store.queue_vendor_jobs(
            "run-1",
            [{"url": "https://home.mobile.de/ALPHA", "name": "Alpha"}],
        )
        await store.mark_vendor_processing(vendor_job.normalized_vendor_url)
        await store.queue_vehicle_jobs(
            "run-1",
            vendor_job.normalized_vendor_url,
            vendor_job.haendler_id,
            {"Händler ID": vendor_job.haendler_id},
            [{"Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=12345678"}],
        )
        [vehicle_job] = await store.pending_vehicle_jobs()
        await store.mark_vehicle_processing(vehicle_job.vehicle_url)

        assert await store.count_by_status("vendors") == {STATUS_PROCESSING: 1}
        assert await store.count_by_status("vehicle_jobs") == {STATUS_PROCESSING: 1}

        await store.requeue_processing_jobs()
        vendor_status = await store.count_by_status("vendors")
        vehicle_status = await store.count_by_status("vehicle_jobs")
        await store.close()
        return vendor_status, vehicle_status

    import asyncio

    vendor_status, vehicle_status = asyncio.run(run())
    assert vendor_status == {STATUS_QUEUED: 1}
    assert vehicle_status == {STATUS_QUEUED: 1}


def test_vehicle_done_and_error_export(tmp_path):
    async def run():
        store = await _new_store(tmp_path)
        await store.start_run("run-1", ScraperConfig(project_root=tmp_path))
        await store.queue_vehicle_jobs(
            "run-1",
            "https://home.mobile.de/ALPHA",
            "C0000001",
            {"Händler ID": "C0000001"},
            [{"Vehicle_URL": "synthetic://vehicle-1", "Markes": "VW"}],
        )
        await store.save_vehicle_done(
            "synthetic://vehicle-1",
            {"run_id": "run-1", "Händler ID": "C0000001", "Vehicle_URL": "synthetic://vehicle-1"},
        )
        await store.record_error(
            {
                "run_id": "run-1",
                "stage": "vehicle",
                "url": "synthetic://vehicle-2",
                "error_message": "boom",
            }
        )
        vehicles = await store.export_vehicles()
        errors = await store.export_errors()
        status = await store.count_by_status("vehicle_jobs")
        await store.close()
        return vehicles, errors, status

    import asyncio

    vehicles, errors, status = asyncio.run(run())
    assert vehicles[0]["Vehicle_URL"] == "synthetic://vehicle-1"
    assert errors[0]["stage"] == "vehicle"
    assert errors[0]["error_message"] == "boom"
    assert status == {STATUS_DONE: 1}


def test_state_store_uses_wal_mode(tmp_path):
    async def run():
        store = await _new_store(tmp_path)
        path = store.path
        await store.close()
        return path

    import asyncio

    path = asyncio.run(run())
    with sqlite3.connect(path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
