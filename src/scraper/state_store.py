"""SQLite-backed durable state for the producer-consumer scraper pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import ScraperConfig
from src.scraper.parsers import normalize_dealer_url

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED_DUPLICATE = "skipped_duplicate"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def config_hash(config: ScraperConfig) -> str:
    """Hash stable run-affecting config values for state traceability."""
    payload = {
        "state": config.state,
        "max_vendors": config.max_vendors,
        "max_cars_per_vendor": config.max_cars_per_vendor,
        "max_pages_per_state": config.max_pages_per_state,
        "skip_vehicle_details": config.skip_vehicle_details,
        "traverse_vehicle_categories": config.traverse_vehicle_categories,
        "category_traversal": config.category_traversal,
        "fetch_strategy": config.fetch_strategy,
        "pipeline_mode": config.pipeline_mode,
        "detail_policy": config.detail_policy,
        "browser": config.browser,
        "browser_mode": config.browser_mode,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class VendorJob:
    normalized_vendor_url: str
    haendler_id: str
    dealer: dict[str, Any]


@dataclass
class VehicleJob:
    vehicle_url: str
    normalized_vendor_url: str
    haendler_id: str
    vendor_info: dict[str, Any]
    fallback: dict[str, Any]


class StateStore:
    """Durable SQLite state store with async-safe serialized access."""

    def __init__(self, path: Path):
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        async with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._create_schema()
            self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            async with self._lock:
                self._conn.close()
                self._conn = None

    async def clear(self) -> None:
        await self.close()
        if self.path.exists():
            self.path.unlink()
        wal = self.path.with_suffix(self.path.suffix + "-wal")
        shm = self.path.with_suffix(self.path.suffix + "-shm")
        if wal.exists():
            wal.unlink()
        if shm.exists():
            shm.unlink()

    async def start_run(self, run_id: str, config: ScraperConfig) -> None:
        async with self._lock:
            conn = self._require_conn()
            now = utc_now()
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                    (run_id, state, started_at, finished_at, status, config_hash)
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (run_id, config.state, now, STATUS_PROCESSING, config_hash(config)),
            )
            conn.commit()

    async def latest_config_hash(self, state: str) -> str | None:
        async with self._lock:
            row = self._require_conn().execute(
                """
                SELECT config_hash
                FROM runs
                WHERE state = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (state,),
            ).fetchone()
        return row["config_hash"] if row else None

    async def finish_run(self, run_id: str, status: str = STATUS_DONE) -> None:
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
                (utc_now(), status, run_id),
            )
            conn.commit()

    async def requeue_processing_jobs(self, run_id: str = "") -> None:
        """Move interrupted processing jobs back to queued for safe resume."""
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                "UPDATE vendors SET status = ? WHERE status = ? AND (? = '' OR run_id = ?)",
                (STATUS_QUEUED, STATUS_PROCESSING, run_id, run_id),
            )
            conn.execute(
                "UPDATE vehicle_jobs SET status = ? WHERE status = ? AND (? = '' OR run_id = ?)",
                (STATUS_QUEUED, STATUS_PROCESSING, run_id, run_id),
            )
            conn.commit()

    async def queue_vendor_jobs(self, run_id: str, dealers: list[dict[str, Any]]) -> list[VendorJob]:
        """Persist vendor jobs and return jobs still needing work."""
        jobs: list[VendorJob] = []
        prepared: list[dict[str, Any]] = []
        for dealer in dealers:
            url = normalize_dealer_url(dealer.get("url", ""))
            if url:
                prepared.append({**dealer, "url": url})
        prepared = sorted(prepared, key=lambda item: item["url"].lower())

        async with self._lock:
            conn = self._require_conn()
            now = utc_now()
            existing_ids = [
                int(str(row["haendler_id"])[1:])
                for row in conn.execute("SELECT haendler_id FROM vendors").fetchall()
                if str(row["haendler_id"]).startswith("C") and str(row["haendler_id"])[1:].isdigit()
            ]
            next_id = max(existing_ids, default=0) + 1
            for index, dealer in enumerate(prepared, start=1):
                url = dealer["url"]
                existing = conn.execute(
                    "SELECT haendler_id, status, run_id FROM vendors WHERE normalized_vendor_url = ?",
                    (url,),
                ).fetchone()
                haendler_id = existing["haendler_id"] if existing else f"C{dealer.get('global_index', next_id):07d}"
                if not existing:
                    next_id += 1
                status = existing["status"] if existing else STATUS_QUEUED
                same_run = bool(existing and existing["run_id"] == run_id)
                if same_run and status == STATUS_DONE:
                    continue
                conn.execute(
                    """
                    INSERT INTO vendors
                        (normalized_vendor_url, run_id, haendler_id, dealer_json, vendor_json, status, updated_at)
                    VALUES (?, ?, ?, ?, NULL, ?, ?)
                    ON CONFLICT(normalized_vendor_url) DO UPDATE SET
                        run_id = excluded.run_id,
                        haendler_id = vendors.haendler_id,
                        dealer_json = excluded.dealer_json,
                        vendor_json = CASE
                            WHEN vendors.run_id = excluded.run_id THEN vendors.vendor_json
                            ELSE NULL
                        END,
                        status = CASE
                            WHEN vendors.run_id = excluded.run_id AND vendors.status = 'done' THEN vendors.status
                            ELSE excluded.status
                        END,
                        last_error = NULL,
                        updated_at = excluded.updated_at
                    """,
                    (
                        url,
                        run_id,
                        haendler_id,
                        _json_dumps({**dealer, "url": url}),
                        STATUS_QUEUED,
                        now,
                    ),
                )
                if not same_run or status != STATUS_DONE:
                    jobs.append(VendorJob(url, haendler_id, {**dealer, "url": url}))
            conn.commit()
        return jobs

    async def pending_vendor_jobs(self, run_id: str = "", limit: int = 0) -> list[VendorJob]:
        query = """
            SELECT normalized_vendor_url, haendler_id, dealer_json
            FROM vendors
            WHERE (? = '' OR run_id = ?) AND status IN (?, ?)
            ORDER BY haendler_id
        """
        params: list[Any] = [run_id, run_id, STATUS_QUEUED, STATUS_FAILED]
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        async with self._lock:
            rows = self._require_conn().execute(query, params).fetchall()
        return [
            VendorJob(row["normalized_vendor_url"], row["haendler_id"], _json_loads(row["dealer_json"]))
            for row in rows
        ]

    async def mark_vendor_processing(self, normalized_vendor_url: str, run_id: str = "") -> None:
        await self._set_status("vendors", "normalized_vendor_url", normalized_vendor_url, STATUS_PROCESSING, run_id)

    async def save_vendor_done(self, normalized_vendor_url: str, vendor: dict[str, Any]) -> None:
        async with self._lock:
            conn = self._require_conn()
            run_id = str(vendor.get("run_id", ""))
            conn.execute(
                """
                UPDATE vendors
                SET vendor_json = ?, status = ?, updated_at = ?
                WHERE normalized_vendor_url = ? AND (? = '' OR run_id = ?)
                """,
                (_json_dumps(vendor), STATUS_DONE, utc_now(), normalized_vendor_url, run_id, run_id),
            )
            conn.commit()

    async def mark_vendor_failed(self, normalized_vendor_url: str, error: str, run_id: str = "") -> None:
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                """
                UPDATE vendors
                SET status = ?, last_error = ?, updated_at = ?
                WHERE normalized_vendor_url = ? AND (? = '' OR run_id = ?)
                """,
                (STATUS_FAILED, error, utc_now(), normalized_vendor_url, run_id, run_id),
            )
            conn.commit()

    async def queue_vehicle_jobs(
        self,
        run_id: str,
        normalized_vendor_url: str,
        haendler_id: str,
        vendor_info: dict[str, Any],
        entries: list[dict[str, Any]],
    ) -> list[VehicleJob]:
        jobs: list[VehicleJob] = []
        async with self._lock:
            conn = self._require_conn()
            now = utc_now()
            for entry in entries:
                vehicle_url = str(entry.get("Vehicle_URL", ""))
                if not vehicle_url:
                    continue
                existing = conn.execute(
                    "SELECT status, run_id FROM vehicle_jobs WHERE vehicle_url = ?",
                    (vehicle_url,),
                ).fetchone()
                same_run = bool(existing and existing["run_id"] == run_id)
                if same_run and existing["status"] == STATUS_DONE:
                    continue
                conn.execute(
                    """
                    INSERT INTO vehicle_jobs
                        (vehicle_url, run_id, normalized_vendor_url, haendler_id,
                         vendor_info_json, fallback_json, status, attempts, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(vehicle_url) DO UPDATE SET
                        run_id = excluded.run_id,
                        normalized_vendor_url = excluded.normalized_vendor_url,
                        haendler_id = excluded.haendler_id,
                        vendor_info_json = excluded.vendor_info_json,
                        fallback_json = excluded.fallback_json,
                        status = CASE
                            WHEN vehicle_jobs.run_id = excluded.run_id AND vehicle_jobs.status = 'done' THEN vehicle_jobs.status
                            ELSE excluded.status
                        END,
                        attempts = CASE
                            WHEN vehicle_jobs.run_id = excluded.run_id THEN vehicle_jobs.attempts
                            ELSE 0
                        END,
                        last_error = NULL,
                        updated_at = excluded.updated_at
                    """,
                    (
                        vehicle_url,
                        run_id,
                        normalized_vendor_url,
                        haendler_id,
                        _json_dumps(vendor_info),
                        _json_dumps(entry),
                        STATUS_QUEUED,
                        now,
                    ),
                )
                if not same_run or existing["status"] != STATUS_DONE:
                    jobs.append(VehicleJob(vehicle_url, normalized_vendor_url, haendler_id, vendor_info, entry))
            conn.commit()
        return jobs

    async def pending_vehicle_jobs(self, run_id: str = "", limit: int = 0) -> list[VehicleJob]:
        query = """
            SELECT vehicle_url, normalized_vendor_url, haendler_id, vendor_info_json, fallback_json
            FROM vehicle_jobs
            WHERE (? = '' OR run_id = ?) AND status IN (?, ?)
            ORDER BY rowid
        """
        params: list[Any] = [run_id, run_id, STATUS_QUEUED, STATUS_FAILED]
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        async with self._lock:
            rows = self._require_conn().execute(query, params).fetchall()
        return [
            VehicleJob(
                row["vehicle_url"],
                row["normalized_vendor_url"],
                row["haendler_id"],
                _json_loads(row["vendor_info_json"]),
                _json_loads(row["fallback_json"]),
            )
            for row in rows
        ]

    async def mark_vehicle_processing(self, vehicle_url: str, run_id: str = "") -> None:
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                """
                UPDATE vehicle_jobs
                SET status = ?, attempts = attempts + 1, updated_at = ?
                WHERE vehicle_url = ? AND (? = '' OR run_id = ?)
                """,
                (STATUS_PROCESSING, utc_now(), vehicle_url, run_id, run_id),
            )
            conn.commit()

    async def save_vehicle_done(self, vehicle_url: str, vehicle: dict[str, Any]) -> None:
        async with self._lock:
            conn = self._require_conn()
            now = utc_now()
            conn.execute(
                """
                INSERT INTO vehicles (vehicle_url, run_id, haendler_id, data_json, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(vehicle_url) DO UPDATE SET
                    run_id = excluded.run_id,
                    haendler_id = excluded.haendler_id,
                    data_json = excluded.data_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    vehicle_url,
                    vehicle.get("run_id", ""),
                    vehicle.get("Händler ID", ""),
                    _json_dumps(vehicle),
                    STATUS_DONE,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE vehicle_jobs
                SET status = ?, updated_at = ?
                WHERE vehicle_url = ? AND (? = '' OR run_id = ?)
                """,
                (STATUS_DONE, now, vehicle_url, vehicle.get("run_id", ""), vehicle.get("run_id", "")),
            )
            conn.commit()

    async def mark_vehicle_failed(self, vehicle_url: str, error: str, run_id: str = "") -> None:
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                """
                UPDATE vehicle_jobs
                SET status = ?, last_error = ?, updated_at = ?
                WHERE vehicle_url = ? AND (? = '' OR run_id = ?)
                """,
                (STATUS_FAILED, error, utc_now(), vehicle_url, run_id, run_id),
            )
            conn.commit()

    async def record_error(self, error: dict[str, Any]) -> None:
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                """
                INSERT INTO errors
                    (run_id, timestamp, stage, url, status_code, fetch_strategy,
                     browser, attempt, error_type, error_message, screenshot_path, html_dump_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    error.get("run_id", ""),
                    error.get("timestamp", utc_now()),
                    error.get("stage") or error.get("type", ""),
                    error.get("url", ""),
                    error.get("status_code"),
                    error.get("fetch_strategy", ""),
                    error.get("browser", ""),
                    error.get("attempt"),
                    error.get("error_type", ""),
                    error.get("error_message") or error.get("error", ""),
                    error.get("screenshot_path", ""),
                    error.get("html_dump_path", ""),
                ),
            )
            conn.commit()

    async def export_vendors(self, run_id: str = "") -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._require_conn().execute(
                """
                SELECT vendor_json, haendler_id, normalized_vendor_url
                FROM vendors
                WHERE status = ? AND vendor_json IS NOT NULL AND (? = '' OR run_id = ?)
                ORDER BY haendler_id
                """,
                (STATUS_DONE, run_id, run_id),
            ).fetchall()
        vendors = []
        for row in rows:
            vendor = _json_loads(row["vendor_json"])
            vendor.setdefault("Händler ID", row["haendler_id"])
            vendor.setdefault("Mobile.de_Links", row["normalized_vendor_url"])
            vendors.append(vendor)
        return vendors

    async def export_vehicles(self, run_id: str = "") -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._require_conn().execute(
                """
                SELECT data_json
                FROM vehicles
                WHERE status = ? AND (? = '' OR run_id = ?)
                ORDER BY haendler_id, vehicle_url
                """,
                (STATUS_DONE, run_id, run_id),
            ).fetchall()
        return [_json_loads(row["data_json"]) for row in rows]

    async def export_errors(self, run_id: str = "") -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._require_conn().execute(
                """
                SELECT run_id, timestamp, stage, url, status_code, fetch_strategy,
                       browser, attempt, error_type, error_message, screenshot_path, html_dump_path
                FROM errors
                WHERE ? = '' OR run_id = ?
                ORDER BY id
                """,
                (run_id, run_id),
            ).fetchall()
        return [dict(row) for row in rows]

    async def count_by_status(self, table: str, run_id: str = "") -> dict[str, int]:
        if table not in {"vendors", "vehicle_jobs"}:
            raise ValueError(f"Unsupported status table: {table}")
        async with self._lock:
            rows = self._require_conn().execute(
                f"SELECT status, COUNT(*) AS count FROM {table} WHERE ? = '' OR run_id = ? GROUP BY status",
                (run_id, run_id),
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    async def _set_status(self, table: str, key: str, value: str, status: str, run_id: str = "") -> None:
        if table not in {"vendors", "vehicle_jobs"}:
            raise ValueError(f"Unsupported status table: {table}")
        if key not in {"normalized_vendor_url", "vehicle_url"}:
            raise ValueError(f"Unsupported status key: {key}")
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                f"UPDATE {table} SET status = ?, updated_at = ? WHERE {key} = ? AND (? = '' OR run_id = ?)",
                (status, utc_now(), value, run_id, run_id),
            )
            conn.commit()

    def _create_schema(self) -> None:
        conn = self._require_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                config_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vendors (
                normalized_vendor_url TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                haendler_id TEXT NOT NULL UNIQUE,
                dealer_json TEXT NOT NULL,
                vendor_json TEXT,
                status TEXT NOT NULL,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vehicle_jobs (
                vehicle_url TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                normalized_vendor_url TEXT NOT NULL,
                haendler_id TEXT NOT NULL,
                vendor_info_json TEXT NOT NULL,
                fallback_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vehicles (
                vehicle_url TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                haendler_id TEXT NOT NULL,
                data_json TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                timestamp TEXT NOT NULL,
                stage TEXT,
                url TEXT,
                status_code INTEGER,
                fetch_strategy TEXT,
                browser TEXT,
                attempt INTEGER,
                error_type TEXT,
                error_message TEXT,
                screenshot_path TEXT,
                html_dump_path TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_vendors_status ON vendors(status);
            CREATE INDEX IF NOT EXISTS idx_vehicle_jobs_status ON vehicle_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_vehicle_jobs_vendor ON vehicle_jobs(normalized_vendor_url);
            """
        )

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore is not connected.")
        return self._conn


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    data = json.loads(value)
    return data if isinstance(data, dict) else {}
