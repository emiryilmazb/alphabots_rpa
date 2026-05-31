"""Opt-in, retryable vehicle detail enrichment for existing raw vehicle data."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import ScraperConfig
from src.models import FINANCING_REQUIRED_FIELDS, VEHICLE_COLUMNS, VEHICLE_TECHNICAL_FIELDS
from src.scraper.detail_page import classify_detail_page
from src.scraper.fetchers import FetchResult, FetchStrategyManager, HostChromeCdpFetcher, vehicle_id_from_url
from src.scraper.fetchers.base import StaticValidation
from src.scraper.parsers import DETAIL_TARGET_FIELDS, clean_text, parse_vehicle_detail_fields

SUMMARY_FILENAME = "detail_enrichment_summary.json"
FAILED_IDS_FILENAME = "failed_detail_ids.json"

ENRICHMENT_FIELDS = tuple(
    dict.fromkeys(
        [
            *DETAIL_TARGET_FIELDS,
            *VEHICLE_TECHNICAL_FIELDS,
            *FINANCING_REQUIRED_FIELDS,
            "Financing",
        ]
    )
)

RETRY_ONLY_MISSING_FIELDS = tuple(dict.fromkeys(DETAIL_TARGET_FIELDS))

METHOD_ALIASES = {
    "host_chrome_cdp": "host-chrome-cdp",
    "host_cdp": "host-chrome-cdp",
    "manual_html": "manual-html",
    "original_url": "original-url",
    "original": "original-url",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_present(value: Any) -> bool:
    return clean_text(value) not in {"", "None", "nan", "NaN", "<NA>"}


def load_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list at {path}")
    return [item for item in data if isinstance(item, dict)]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def parse_methods(value: str) -> list[str]:
    methods: list[str] = []
    for raw_method in value.split(","):
        method = METHOD_ALIASES.get(raw_method.strip().lower(), raw_method.strip().lower())
        if method and method not in methods:
            methods.append(method)
    return methods


def vehicle_urls(vehicle: dict[str, Any], *, source_only: bool = False) -> list[str]:
    ordered = []
    keys = ["source_vehicle_url"] if source_only else ["Vehicle_URL", "source_vehicle_url"]
    for key in keys:
        url = clean_text(vehicle.get(key, ""))
        if url and url not in ordered:
            ordered.append(url)
    return ordered


def enrichment_missing_fields(vehicle: dict[str, Any]) -> list[str]:
    return [field for field in ENRICHMENT_FIELDS if not is_present(vehicle.get(field, ""))]


def retry_missing_fields(vehicle: dict[str, Any]) -> list[str]:
    return [field for field in RETRY_ONLY_MISSING_FIELDS if not is_present(vehicle.get(field, ""))]


def coverage_pct(records: Sequence[dict[str, Any]], fields: Sequence[str]) -> float:
    if not records or not fields:
        return 0.0
    total = len(records) * len(fields)
    present = sum(1 for record in records for field in fields if is_present(record.get(field, "")))
    return round((present / total) * 100, 2)


def merge_non_empty_fields(
    vehicle: dict[str, Any],
    parsed_fields: dict[str, Any],
    *,
    source: str,
) -> list[str]:
    filled: list[str] = []
    conflicts: dict[str, dict[str, str]] = {}
    for key, value in parsed_fields.items():
        if key not in vehicle:
            continue
        parsed_value = clean_text(value)
        if not parsed_value:
            continue
        if not is_present(vehicle.get(key, "")):
            vehicle[key] = parsed_value
            vehicle[f"{key}_source"] = source
            filled.append(key)
            continue
        existing_value = clean_text(vehicle.get(key, ""))
        if existing_value != parsed_value:
            conflicts[key] = {"existing": existing_value, "detail": parsed_value}

    if vehicle.get("Financing") and not is_present(vehicle.get("Finanzierung", "")):
        vehicle["Finanzierung"] = vehicle["Financing"]
        if "Finanzierung" not in filled:
            filled.append("Finanzierung")

    if filled:
        previous = [
            clean_text(field)
            for field in clean_text(vehicle.get("detail_fields_filled", "")).split(",")
            if clean_text(field)
        ]
        vehicle["detail_fields_filled"] = ", ".join(dict.fromkeys([*previous, *filled]))

    if conflicts:
        vehicle["detail_enrichment_conflicts_json"] = json.dumps(
            conflicts,
            ensure_ascii=False,
            sort_keys=True,
        )
    return filled


class DetailEnricher:
    def __init__(
        self,
        *,
        cache_dir: Path,
        methods: Sequence[str],
        chrome_cdp_url: str,
        sleep_seconds: float,
        sleep_jitter_seconds: float = 0.0,
        stop_after_blocks: int = 0,
        max_block_rate: float = 0.0,
        method_cooldown_blocks: int = 0,
        method_cooldown_seconds: float = 0.0,
        retry_only_missing: bool = False,
        resume: bool = True,
        manual_html_dir: Path | None = None,
        failed_ids_path: Path | None = None,
        host_fetcher_factory: Callable[[ScraperConfig], Any] | None = None,
        existing_fetch_manager: FetchStrategyManager | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.html_cache_dir = cache_dir / "html"
        self.parsed_cache_dir = cache_dir / "parsed"
        self.manual_html_dir = manual_html_dir or cache_dir / "manual_html"
        self.failed_ids_path = failed_ids_path or cache_dir / FAILED_IDS_FILENAME
        self.methods = self._normalize_methods(methods)
        self.sleep_seconds = max(0.0, sleep_seconds)
        self.sleep_jitter_seconds = max(0.0, sleep_jitter_seconds)
        self.stop_after_blocks = max(0, stop_after_blocks)
        self.max_block_rate = max(0.0, max_block_rate)
        self.method_cooldown_blocks = max(0, method_cooldown_blocks)
        self.method_cooldown_seconds = max(0.0, method_cooldown_seconds)
        self.retry_only_missing = retry_only_missing
        self.resume = resume
        self.config = ScraperConfig(
            detail_open_strategy="host-chrome-cdp",
            chrome_cdp_url=chrome_cdp_url,
            fetch_strategy="curl",
        )
        self.host_fetcher_factory = host_fetcher_factory or HostChromeCdpFetcher
        self._host_fetcher: Any | None = None
        self.existing_fetch_manager = existing_fetch_manager or FetchStrategyManager(
            ScraperConfig(fetch_strategy="curl")
        )
        self.host_chrome_disabled = False
        self.existing_disabled = False
        self.host_chrome_consecutive_blocks = 0
        self.existing_consecutive_blocks = 0
        self.run_attempted_ids: set[str] = set()
        self.new_failures: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()

    async def close(self) -> None:
        if self._host_fetcher is not None and hasattr(self._host_fetcher, "close"):
            await self._host_fetcher.close()

    async def enrich_records(
        self,
        records: list[dict[str, Any]],
        *,
        max_vehicles: int = 0,
    ) -> dict[str, Any]:
        self._ensure_dirs()
        self.counts["technical_coverage_before_pct"] = coverage_pct(records, VEHICLE_TECHNICAL_FIELDS)
        self.counts["financing_coverage_before_pct"] = coverage_pct(records, FINANCING_REQUIRED_FIELDS)
        processed = 0
        for index, vehicle in enumerate(records):
            self._ensure_vehicle_shape(vehicle)
            vehicle_id = self._vehicle_id(vehicle, index)
            missing = self._candidate_missing_fields(vehicle)
            if not missing:
                if self.retry_only_missing:
                    self.counts["skipped_not_missing_retry_fields_count"] += 1
                else:
                    self.counts["already_complete_count"] += 1
                continue
            if max_vehicles and processed >= max_vehicles:
                self.counts["skipped_by_limit_count"] += 1
                continue
            if vehicle_id in self.run_attempted_ids:
                self.counts["skipped_duplicate_id_count"] += 1
                continue
            self.run_attempted_ids.add(vehicle_id)
            processed += 1
            self.counts["candidate_vehicle_count"] += 1
            self.counts["missing_field_total_before"] += len(missing)
            result = await self._enrich_one(vehicle, vehicle_id)
            if result:
                self.counts["successful_vehicle_count"] += 1
            remaining_missing = enrichment_missing_fields(vehicle)
            self.counts["missing_field_total_after"] += len(remaining_missing)
            if remaining_missing:
                self.counts["still_missing_vehicle_count"] += 1

        self.counts["processed_vehicle_count"] = processed
        self.counts["technical_coverage_after_pct"] = coverage_pct(records, VEHICLE_TECHNICAL_FIELDS)
        self.counts["financing_coverage_after_pct"] = coverage_pct(records, FINANCING_REQUIRED_FIELDS)
        self._write_failed_ids()
        summary = self.summary()
        write_json(self.cache_dir / SUMMARY_FILENAME, summary)
        return summary

    def summary(self) -> dict[str, Any]:
        return {
            "generated_at_utc": utc_now(),
            "methods": self.methods,
            "cache_dir": str(self.cache_dir),
            "failed_ids_path": str(self.failed_ids_path),
            "summary_path": str(self.cache_dir / SUMMARY_FILENAME),
            **dict(sorted(self.counts.items())),
            "attempted": int(self.counts.get("processed_vehicle_count", 0)),
            "success": int(self.counts.get("successful_vehicle_count", 0)),
            "failed": max(
                0,
                int(self.counts.get("processed_vehicle_count", 0))
                - int(self.counts.get("successful_vehicle_count", 0)),
            ),
            "blocked": int(
                self.counts.get("host_chrome_cdp_blocked_count", 0)
                + self.counts.get("existing_blocked_count", 0)
            ),
            "cache_hit": int(self.counts.get("cache_hit_count", 0)),
            "host_chrome_disabled": self.host_chrome_disabled,
            "existing_disabled": self.existing_disabled,
            "new_failed_detail_ids_count": len(self.new_failures),
        }

    async def _enrich_one(self, vehicle: dict[str, Any], vehicle_id: str) -> bool:
        listing_seen = False
        for method in self.methods:
            if method == "listing":
                listing_seen = True
                self.counts["listing_preserved_count"] += 1
                continue
            if method == "cache":
                parsed = self._load_cached_parsed(vehicle_id)
                if parsed:
                    self.counts["cache_hit_count"] += 1
                    self._apply_parsed_fields(vehicle, parsed, source="cache", detail_status="cached_detail_page")
                    return True
                self.counts["cache_miss_count"] += 1
                continue
            if method == "manual-html":
                parsed = self._load_manual_html(vehicle_id)
                if parsed:
                    self.counts["manual_html_success_count"] += 1
                    self._cache_parsed(vehicle_id, parsed, vehicle, source="manual-html")
                    self._apply_parsed_fields(vehicle, parsed, source="manual-html", detail_status="manual_html")
                    return True
                self.counts["manual_html_missing_count"] += 1
                continue
            if method == "existing":
                if self.existing_disabled:
                    self.counts["existing_skipped_disabled_count"] += 1
                    continue
                if await self._try_existing(vehicle, vehicle_id):
                    return True
                continue
            if method in {"host-chrome-cdp", "original-url"}:
                if self.host_chrome_disabled:
                    self.counts["host_chrome_cdp_skipped_disabled_count"] += 1
                    continue
                source_only = method == "original-url"
                if await self._try_host_chrome(vehicle, vehicle_id, source_only=source_only):
                    return True
                continue
            self.counts[f"unknown_method_{method}_count"] += 1

        if not listing_seen:
            self.counts["listing_not_in_method_chain_count"] += 1
        return False

    async def _try_existing(self, vehicle: dict[str, Any], vehicle_id: str) -> bool:
        urls = vehicle_urls(vehicle)
        if not urls:
            self._record_failure(vehicle, vehicle_id, "existing", "", "missing_vehicle_url")
            return False
        for url in urls:
            self.counts["existing_attempt_count"] += 1
            result = await self.existing_fetch_manager.fetch(
                url,
                validator=self._validate_existing_result,
                allow_curl=True,
                playwright_max_retries=1,
            )
            if result.ok:
                parsed = self._parse_successful_html(result.html, url=result.final_url or url)
                if parsed:
                    self.counts["existing_success_count"] += 1
                    self._cache_html(vehicle_id, result.html)
                    self._cache_parsed(vehicle_id, parsed, vehicle, source="existing")
                    self._apply_parsed_fields(vehicle, parsed, source="existing", detail_status="real_detail_page")
                    return True
            reason = result.error_message or result.fallback_reason or result.error_type or "existing_fetch_failed"
            if self._is_blocked(result, reason):
                self.counts["existing_blocked_count"] += 1
                self.existing_consecutive_blocks += 1
                if await self._handle_block_thresholds("existing"):
                    self.existing_disabled = True
            else:
                self.existing_consecutive_blocks = 0
            self.counts["existing_failed_count"] += 1
            self._record_failure(vehicle, vehicle_id, "existing", url, reason, result=result)
            if self.existing_disabled:
                break
        return False

    async def _try_host_chrome(
        self,
        vehicle: dict[str, Any],
        vehicle_id: str,
        *,
        source_only: bool = False,
    ) -> bool:
        urls = vehicle_urls(vehicle, source_only=source_only)
        if not urls:
            self._record_failure(vehicle, vehicle_id, "host-chrome-cdp", "", "missing_vehicle_url")
            return False
        fetcher = self._get_host_fetcher()
        for url in urls:
            self.counts["host_chrome_cdp_attempt_count"] += 1
            result: FetchResult = await fetcher.fetch(url)
            await self._sleep_after_live_attempt()
            if result.ok:
                self.host_chrome_consecutive_blocks = 0
                parsed = self._parse_successful_html(result.html, url=result.final_url or url)
                if parsed:
                    self.counts["host_chrome_cdp_success_count"] += 1
                    self._cache_html(vehicle_id, result.html)
                    self._cache_parsed(vehicle_id, parsed, vehicle, source="host-chrome-cdp")
                    self._apply_parsed_fields(
                        vehicle,
                        parsed,
                        source="host-chrome-cdp",
                        detail_status=result.detail_status or result.classification or "real_detail_page",
                    )
                    return True

            reason = (
                result.failure_reason
                or result.error_message
                or result.error_type
                or result.detail_status
                or result.classification
                or "host_chrome_cdp_fetch_failed"
            )
            if self._is_blocked(result, reason):
                self.counts["host_chrome_cdp_blocked_count"] += 1
                self.host_chrome_consecutive_blocks += 1
                if await self._handle_block_thresholds("host-chrome-cdp"):
                    self.host_chrome_disabled = True
            else:
                self.host_chrome_consecutive_blocks = 0
            self.counts["host_chrome_cdp_failed_count"] += 1
            self._record_failure(vehicle, vehicle_id, "host-chrome-cdp", url, reason, result=result)
            if self.host_chrome_disabled:
                break
        return False

    def _apply_parsed_fields(
        self,
        vehicle: dict[str, Any],
        parsed_fields: dict[str, Any],
        *,
        source: str,
        detail_status: str,
    ) -> None:
        before_missing = len(enrichment_missing_fields(vehicle))
        filled = merge_non_empty_fields(vehicle, parsed_fields, source=source)
        after_missing = len(enrichment_missing_fields(vehicle))
        improved_count = max(0, before_missing - after_missing)
        target_extracted_count = sum(1 for field in DETAIL_TARGET_FIELDS if is_present(parsed_fields.get(field, "")))

        if target_extracted_count:
            vehicle["detail_target_fields_extracted_count"] = target_extracted_count
        if source:
            vehicle["detail_data_source"] = source
            vehicle["detail_strategy_used"] = source
        if detail_status:
            vehicle["detail_status"] = detail_status
        if source == "host-chrome-cdp":
            vehicle["vehicle_data_source"] = "detail_page_host_chrome_cdp"
        elif source == "manual-html":
            vehicle["vehicle_data_source"] = "detail_page_manual_html"
        elif source == "cache":
            vehicle["vehicle_data_source"] = "detail_page_cache"
        elif source == "existing":
            vehicle["vehicle_data_source"] = "detail_page_existing"
        vehicle["parse_status"] = "ok"

        self.counts["fields_filled_count"] += len(filled)
        if improved_count:
            self.counts["vehicles_improved_count"] += 1
            self.counts["fields_improved_count"] += improved_count
        elif parsed_fields:
            self.counts["successful_without_new_fields_count"] += 1

    def _load_cached_parsed(self, vehicle_id: str) -> dict[str, Any]:
        if not self.resume:
            return {}
        path = self.parsed_cache_dir / f"{vehicle_id}.json"
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
        parsed = data.get("parsed_fields") if isinstance(data, dict) else None
        if isinstance(parsed, dict):
            return parsed
        return data if isinstance(data, dict) else {}

    def _load_manual_html(self, vehicle_id: str) -> dict[str, Any]:
        for suffix in (".html", ".htm"):
            path = self.manual_html_dir / f"{vehicle_id}{suffix}"
            if not path.exists():
                continue
            html = path.read_text(encoding="utf-8")
            parsed = parse_vehicle_detail_fields(html)
            parsed = {key: value for key, value in parsed.items() if is_present(value)}
            if parsed:
                self._cache_html(vehicle_id, html)
                return parsed
        return {}

    def _parse_successful_html(self, html: str, *, url: str) -> dict[str, Any]:
        classification = classify_detail_page(html, url=url)
        if classification.classification not in {"real_detail_page", "unknown"}:
            return {}
        parsed = parse_vehicle_detail_fields(html)
        return {key: value for key, value in parsed.items() if is_present(value)}

    def _cache_html(self, vehicle_id: str, html: str) -> None:
        self.html_cache_dir.mkdir(parents=True, exist_ok=True)
        (self.html_cache_dir / f"{vehicle_id}.html").write_text(html, encoding="utf-8")

    def _cache_parsed(
        self,
        vehicle_id: str,
        parsed_fields: dict[str, Any],
        vehicle: dict[str, Any],
        *,
        source: str,
    ) -> None:
        self.parsed_cache_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            self.parsed_cache_dir / f"{vehicle_id}.json",
            {
                "vehicle_id": vehicle_id,
                "url": clean_text(vehicle.get("Vehicle_URL") or vehicle.get("source_vehicle_url", "")),
                "source": source,
                "cached_at_utc": utc_now(),
                "parsed_fields": parsed_fields,
            },
        )

    def _record_failure(
        self,
        vehicle: dict[str, Any],
        vehicle_id: str,
        method: str,
        url: str,
        reason: str,
        *,
        result: FetchResult | None = None,
    ) -> None:
        vehicle["detail_strategy_used"] = method
        vehicle["detail_status"] = (result.detail_status if result else "") or "detail_enrichment_failed"
        vehicle["detail_failure_reason"] = reason
        vehicle.setdefault("vehicle_data_source", "listing_fallback")
        self.new_failures.append(
            {
                "vehicle_id": vehicle_id,
                "url": url,
                "method": method,
                "reason": reason,
                "status_code": result.status_code if result else None,
                "detail_status": result.detail_status if result else "",
                "classification": result.classification if result else "",
                "recorded_at_utc": utc_now(),
            }
        )

    def _write_failed_ids(self) -> None:
        existing: list[dict[str, Any]] = []
        if self.resume and self.failed_ids_path.exists():
            try:
                with self.failed_ids_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    existing = [item for item in data if isinstance(item, dict)]
            except (OSError, json.JSONDecodeError):
                existing = []
        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in [*existing, *self.new_failures]:
            key = (
                clean_text(item.get("vehicle_id", "")),
                clean_text(item.get("url", "")),
                clean_text(item.get("method", "")),
            )
            unique[key] = item
        write_json(self.failed_ids_path, list(unique.values()))

    def _ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.html_cache_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_cache_dir.mkdir(parents=True, exist_ok=True)
        self.manual_html_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _ensure_vehicle_shape(vehicle: dict[str, Any]) -> None:
        for column in VEHICLE_COLUMNS:
            vehicle.setdefault(column, "")
        if vehicle.get("Vehicle_URL") and not vehicle.get("source_vehicle_url"):
            vehicle["source_vehicle_url"] = vehicle["Vehicle_URL"]

    @staticmethod
    def _vehicle_id(vehicle: dict[str, Any], index: int) -> str:
        for url in vehicle_urls(vehicle):
            vehicle_id = vehicle_id_from_url(url)
            if vehicle_id:
                return vehicle_id
        return f"row-{index + 1}"

    def _get_host_fetcher(self) -> Any:
        if self._host_fetcher is None:
            self._host_fetcher = self.host_fetcher_factory(self.config)
        return self._host_fetcher

    def _candidate_missing_fields(self, vehicle: dict[str, Any]) -> list[str]:
        if self.retry_only_missing:
            return retry_missing_fields(vehicle)
        return enrichment_missing_fields(vehicle)

    async def _sleep_after_live_attempt(self) -> None:
        delay = self.sleep_seconds
        if self.sleep_jitter_seconds:
            delay += random.uniform(0.0, self.sleep_jitter_seconds)
        if delay > 0:
            self.counts["live_sleep_count"] += 1
            self.counts["live_sleep_planned_seconds_total"] += round(delay, 2)
            await asyncio.sleep(delay)

    async def _handle_block_thresholds(self, method: str) -> bool:
        if method == "host-chrome-cdp":
            blocked = int(self.counts.get("host_chrome_cdp_blocked_count", 0))
            attempts = int(self.counts.get("host_chrome_cdp_attempt_count", 0))
            consecutive = self.host_chrome_consecutive_blocks
            disabled_counter = "host_chrome_cdp_disabled_by_threshold_count"
            cooldown_counter = "host_chrome_cdp_cooldown_count"
        else:
            blocked = int(self.counts.get("existing_blocked_count", 0))
            attempts = int(self.counts.get("existing_attempt_count", 0))
            consecutive = self.existing_consecutive_blocks
            disabled_counter = "existing_disabled_by_threshold_count"
            cooldown_counter = "existing_cooldown_count"

        if self.method_cooldown_blocks and consecutive >= self.method_cooldown_blocks:
            if self.method_cooldown_seconds > 0:
                self.counts[cooldown_counter] += 1
                await asyncio.sleep(self.method_cooldown_seconds)
                if method == "host-chrome-cdp":
                    self.host_chrome_consecutive_blocks = 0
                else:
                    self.existing_consecutive_blocks = 0
                return False
            self.counts[disabled_counter] += 1
            return True

        if self.stop_after_blocks and blocked >= self.stop_after_blocks:
            self.counts[disabled_counter] += 1
            return True

        if self.max_block_rate and attempts > 0 and (blocked / attempts) > self.max_block_rate:
            self.counts[f"{method.replace('-', '_')}_disabled_by_block_rate_count"] += 1
            return True
        return False

    @staticmethod
    def _validate_existing_result(result: FetchResult) -> StaticValidation:
        base = FetchStrategyManager.validate_static_html(result)
        if not base.ok:
            return base
        classification = classify_detail_page(result.html, url=result.final_url or result.url)
        if classification.classification != "real_detail_page":
            return StaticValidation(False, classification.reason or classification.classification)
        return StaticValidation(True)

    @staticmethod
    def _is_blocked(result: FetchResult, reason: str) -> bool:
        text = " ".join(
            [
                clean_text(reason).lower(),
                clean_text(result.error_type).lower(),
                clean_text(result.error_message).lower(),
                clean_text(result.failure_reason).lower(),
                clean_text(result.classification).lower(),
                clean_text(result.detail_status).lower(),
                str(result.status_code or ""),
            ]
        )
        blocked_markers = [
            "403",
            "503",
            "blocked",
            "challenge",
            "captcha",
            "access denied",
            "zugriff verweigert",
            "error_page",
        ]
        return any(marker in text for marker in blocked_markers)

    @staticmethod
    def _normalize_methods(methods: Sequence[str]) -> list[str]:
        normalized = list(methods)
        if "cache" in normalized:
            normalized = ["cache", *[method for method in normalized if method != "cache"]]
        else:
            normalized.insert(0, "cache")
        return normalized


async def run(args: argparse.Namespace) -> dict[str, Any]:
    input_cars = Path(args.input_cars)
    output_cars = Path(args.output_cars)
    records = load_json_list(input_cars)
    methods = parse_methods(args.methods)
    enricher = DetailEnricher(
        cache_dir=Path(args.cache_dir),
        methods=methods,
        chrome_cdp_url=args.chrome_cdp_url,
        sleep_seconds=args.sleep_seconds,
        sleep_jitter_seconds=args.sleep_jitter_seconds,
        stop_after_blocks=args.stop_after_blocks,
        max_block_rate=args.max_block_rate,
        method_cooldown_blocks=args.method_cooldown_blocks,
        method_cooldown_seconds=args.method_cooldown_seconds,
        retry_only_missing=args.retry_only_missing.lower() == "true",
        resume=args.resume.lower() == "true",
        manual_html_dir=Path(args.manual_html_dir) if args.manual_html_dir else None,
        failed_ids_path=Path(args.failed_ids_path) if args.failed_ids_path else None,
    )
    try:
        summary = await enricher.enrich_records(records, max_vehicles=args.max_vehicles)
    finally:
        await enricher.close()
    write_json(output_cars, records)
    summary = {
        **summary,
        "input_cars": str(input_cars),
        "output_cars": str(output_cars),
        "input_vehicle_count": len(records),
    }
    write_json(Path(args.cache_dir) / SUMMARY_FILENAME, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-cars", required=True, help="Existing raw cars JSON")
    parser.add_argument("--output-cars", required=True, help="Output enriched cars JSON")
    parser.add_argument("--cache-dir", default="data/detail_cache", help="Cache root for HTML, parsed fields, and failures")
    parser.add_argument(
        "--methods",
        default="cache,listing,host-chrome-cdp,manual-html",
        help="Comma-separated method chain: cache,listing,existing,host-chrome-cdp,original-url,manual-html",
    )
    parser.add_argument("--chrome-cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--max-vehicles", type=int, default=0, help="0 means no limit")
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--sleep-jitter-seconds", type=float, default=0.0)
    parser.add_argument("--stop-after-blocks", type=int, default=0, help="0 disables block threshold")
    parser.add_argument("--max-block-rate", type=float, default=0.0, help="0 disables block-rate stopping")
    parser.add_argument("--method-cooldown-blocks", type=int, default=0, help="0 disables consecutive-block cooldown")
    parser.add_argument("--method-cooldown-seconds", type=float, default=0.0)
    parser.add_argument("--retry-only-missing", choices=["true", "false"], default="false")
    parser.add_argument("--resume", choices=["true", "false"], default="true")
    parser.add_argument("--manual-html-dir", default="")
    parser.add_argument("--failed-ids-path", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = asyncio.run(run(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
