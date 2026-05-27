"""Tiny-sample source audit and detail navigation strategy matrix."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Response, async_playwright

from src.config import ScraperConfig
from src.scraper.browser import DEFAULT_USER_AGENT
from src.scraper.parsers import (
    clean_text,
    extract_next_payloads,
    normalize_vehicle_url,
    parse_regional_page,
    parse_vehicle_category_options,
    parse_vehicle_listing_summaries,
    parse_vehicle_listing_urls,
    parse_vehicle_specs,
    walk_json,
)

logger = logging.getLogger("mobile_de.source_audit")

TARGET_FIELDS = [
    "CO₂-Emissionen",
    "Baureihe",
    "Ausstattungslinie",
    "Anzahl der Fahrzeughalter",
]

TARGET_KEYWORDS = {
    "CO₂-Emissionen": [
        "co2",
        "co₂",
        "emission",
        "emissions",
        "verbrauch",
        "energieverbrauch",
        "umwelt",
        "environmental",
        "envkv",
        "combinedco2",
        "wltp",
        "nedc",
    ],
    "Baureihe": [
        "series",
        "modelseries",
        "baureihe",
        "modelrange",
        "variantgroup",
        "model line",
    ],
    "Ausstattungslinie": [
        "trim",
        "trimline",
        "equipmentline",
        "ausstattungslinie",
        "line",
        "variant",
        "edition",
    ],
    "Anzahl der Fahrzeughalter": [
        "owner",
        "owners",
        "numberofowners",
        "pvo",
        "previousowners",
        "fahrzeughalter",
        "halter",
        "previouskeepers",
        "vorbesitzer",
    ],
}

DETAIL_STRATEGIES = [
    "direct_url_fresh_context",
    "direct_url_persistent_context",
    "same_context_from_vendor",
    "same_page_navigation_from_category",
    "click_from_listing",
    "modifier_click_new_tab",
    "delayed_click_from_listing",
    "detail_after_warmup",
    "browser_channel_chromium",
    "browser_channel_chrome",
    "browser_channel_firefox",
]

VENDOR_HINTS = [
    "https://home.mobile.de/2PSRL",
    "https://home.mobile.de/AH-BARNOWSKI",
    "https://home.mobile.de/ATWGMBH",
]


@dataclass
class VehicleSample:
    url: str
    vendor_url: str
    category_url: str
    title: str = ""


class NetworkRecorder:
    """Collect bounded request/response metadata and small textual bodies."""

    def __init__(self, audit_dir: Path, prefix: str):
        self.audit_dir = audit_dir
        self.prefix = prefix
        self.response_body_dir = audit_dir / "network_bodies" / prefix
        self.response_body_dir.mkdir(parents=True, exist_ok=True)
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.api_endpoints: list[dict[str, Any]] = []
        self._tasks: list[asyncio.Task] = []

    def attach(self, page: Page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _on_request(self, request) -> None:
        self.requests.append(
            {
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
            }
        )

    def _on_response(self, response: Response) -> None:
        self._tasks.append(asyncio.create_task(self._record_response(response)))

    async def _record_response(self, response: Response) -> None:
        request = response.request
        headers = response.headers
        content_type = headers.get("content-type", "")
        entry: dict[str, Any] = {
            "url": response.url,
            "status": response.status,
            "method": request.method,
            "resource_type": request.resource_type,
            "content_type": content_type,
            "headers": _small_headers(headers),
        }
        if _should_capture_response_body(response.url, content_type, request.resource_type):
            try:
                text = await asyncio.wait_for(response.text(), timeout=5)
                if text and len(text) <= 2_000_000:
                    body_path = self.response_body_dir / f"{_digest(response.url)}{_body_suffix(content_type)}"
                    body_path.write_text(text, encoding="utf-8", errors="ignore")
                    entry["body_path"] = str(body_path)
                    entry["body_excerpt"] = clean_text(text[:500])
            except Exception as exc:
                entry["body_error"] = str(exc)

        self.responses.append(entry)
        if _looks_api_endpoint(entry):
            self.api_endpoints.append(entry)

    async def flush(self) -> dict[str, Any]:
        if self._tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self._tasks, return_exceptions=True), timeout=20)
            except asyncio.TimeoutError:
                for task in self._tasks:
                    if not task.done():
                        task.cancel()
        request_response_log = {
            "requests": self.requests,
            "responses": self.responses,
        }
        return {
            "network_response_index": self.responses,
            "playwright_request_response_log": request_response_log,
            "discovered_api_endpoints": self.api_endpoints,
        }


async def run_source_audit(
    config: ScraperConfig,
    *,
    run_id: str,
    bundesland: str,
) -> dict[str, Any]:
    """Save bounded source snapshots and run the targeted detail strategy matrix."""
    audit_dir = config.source_audit_dir
    audit_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    logger.info("Starting source audit run_id=%s dir=%s", run_id, audit_dir)

    samples: list[VehicleSample] = []
    vendor_results: list[dict[str, Any]] = []
    network_payload: dict[str, Any] = {
        "network_response_index": [],
        "playwright_request_response_log": {"requests": [], "responses": []},
        "discovered_api_endpoints": [],
    }

    async with async_playwright() as pw:
        browser, context = await _open_browser_context(pw, config, config.browser)
        try:
            page = await context.new_page()
            recorder = NetworkRecorder(audit_dir, "source_pages")
            recorder.attach(page)
            vendor_urls = await _discover_vendor_urls(page, config)
            per_vendor_sample_cap = max(
                1,
                (config.source_audit_max_vehicles + config.source_audit_max_vendors - 1)
                // config.source_audit_max_vendors,
            )
            for index, vendor_url in enumerate(vendor_urls[: config.source_audit_max_vendors], start=1):
                vendor_result, vendor_samples = await _audit_vendor(
                    page,
                    audit_dir / f"vendor_{index}_{_safe_name(vendor_url)}",
                    vendor_url,
                    config,
                )
                vendor_results.append(vendor_result)
                added_for_vendor = 0
                for sample in vendor_samples:
                    if (
                        len(samples) >= config.source_audit_max_vehicles
                        or added_for_vendor >= per_vendor_sample_cap
                    ):
                        break
                    if sample.url not in {item.url for item in samples}:
                        samples.append(sample)
                        added_for_vendor += 1
            network_payload = await recorder.flush()
        finally:
            await _close_context_and_browser(context, browser)

    _write_json(audit_dir / "network_response_index.json", network_payload["network_response_index"])
    _write_json(audit_dir / "playwright_request_response_log.json", network_payload["playwright_request_response_log"])
    _write_json(audit_dir / "discovered_api_endpoints.json", network_payload["discovered_api_endpoints"])

    matrix = await run_detail_strategy_matrix(config, samples, audit_dir)
    _write_json(audit_dir / "detail_strategy_matrix.json", matrix)

    search_results = _search_audit_artifacts(audit_dir)
    _write_json(audit_dir / "target_field_search_results.json", search_results)
    target_fields_found = _target_fields_found(search_results, matrix)
    _merge_listing_payload_values(target_fields_found, vendor_results)

    recommendation = _recommend_detail_strategy(matrix)
    summary = {
        "run_id": run_id,
        "state": config.state,
        "state_label": bundesland,
        "audit_dir": str(audit_dir),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "vendors_audited": len(vendor_results),
        "vehicles_audited": len(samples),
        "vendors": vendor_results,
        "vehicle_samples": [sample.__dict__ for sample in samples],
        "target_fields_found": target_fields_found,
        "strategies_tested": [row["strategy"] for row in matrix],
        "detail_strategy_status": "completed",
        "detail_strategy_matrix_path": str(audit_dir / "detail_strategy_matrix.json"),
        "recommendation": recommendation,
    }
    summary_path = audit_dir / "source_audit_summary.json"
    summary["summary_path"] = str(summary_path)
    _write_json(summary_path, summary)
    logger.info("Source audit complete: %s", summary_path)
    return summary


async def _discover_vendor_urls(page: Page, config: ScraperConfig) -> list[str]:
    discovered: list[str] = []
    try:
        await page.goto(config.state_page_url.format(page=0), wait_until="domcontentloaded", timeout=45_000)
        await _accept_cookies(page)
        html = await page.content()
        discovered = [dealer["url"] for dealer in parse_regional_page(html) if dealer.get("url")]
    except Exception as exc:
        logger.warning("Source audit regional discovery failed: %s", exc)

    urls = []
    for url in [*VENDOR_HINTS, *discovered]:
        if url and url not in urls:
            urls.append(url)
    return urls


async def _audit_vendor(
    page: Page,
    vendor_dir: Path,
    vendor_url: str,
    config: ScraperConfig,
) -> tuple[dict[str, Any], list[VehicleSample]]:
    vendor_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "vendor_url": vendor_url,
        "category_url": "",
        "listing_count": 0,
        "real_detail_url_count": 0,
        "target_key_hits_in_listing_payload": [],
    }
    samples: list[VehicleSample] = []

    response = await page.goto(vendor_url, wait_until="domcontentloaded", timeout=45_000)
    await _accept_cookies(page)
    await _settle_page(page)
    vendor_html = await page.content()
    _write_text(vendor_dir / "vendor_base.html", vendor_html)
    _write_json(vendor_dir / "vendor_base_next_data.json", extract_next_payloads(vendor_html))

    category_url = _choose_category_url(vendor_url, vendor_html)
    result["category_url"] = category_url
    response = await page.goto(category_url, wait_until="domcontentloaded", timeout=45_000)
    await _accept_cookies(page)
    await _settle_page(page)
    category_html = await page.content()
    _write_text(vendor_dir / "category_page.html", category_html)
    _write_json(vendor_dir / "category_page_next_data.json", extract_next_payloads(category_html))

    raw_listings = _raw_search_result_listings(category_html)
    summaries = parse_vehicle_listing_summaries(category_html)
    page_urls = [normalize_vehicle_url(url) for url in parse_vehicle_listing_urls(category_html)]
    dom_cards = await _dom_listing_cards(page)
    card_text = "\n\n---CARD---\n\n".join(card.get("text", "") for card in dom_cards)

    _write_json(
        vendor_dir / "listing_cards.json",
        {
            "structured_summaries": summaries,
            "raw_search_result_listings": raw_listings,
            "dom_cards": dom_cards,
            "page_urls": page_urls,
        },
    )
    _write_json(vendor_dir / "vehicle_card_raw.json", raw_listings[0] if raw_listings else {})
    _write_text(vendor_dir / "vehicle_card_text.txt", card_text)
    _write_json(vendor_dir / "listing_payload_key_hits.json", _recursive_keyword_hits(raw_listings))

    detail_urls = []
    for url in [*summaries.keys(), *page_urls, *(card.get("url", "") for card in dom_cards)]:
        normalized = normalize_vehicle_url(url)
        if normalized and "details.html" in normalized and normalized not in detail_urls:
            detail_urls.append(normalized)

    result["listing_count"] = max(len(summaries), len(raw_listings), len(dom_cards))
    result["real_detail_url_count"] = len(detail_urls)
    result["target_key_hits_in_listing_payload"] = _recursive_keyword_hits(raw_listings)[:100]

    for url in detail_urls[: config.source_audit_max_vehicles]:
        title = summaries.get(url, {}).get("Models", "") or next(
            (card.get("title", "") for card in dom_cards if normalize_vehicle_url(card.get("url", "")) == url),
            "",
        )
        samples.append(VehicleSample(url=url, vendor_url=vendor_url, category_url=category_url, title=title))

    return result, samples


async def run_detail_strategy_matrix(
    config: ScraperConfig,
    samples: list[VehicleSample],
    audit_dir: Path,
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    if not samples:
        return matrix

    for strategy in DETAIL_STRATEGIES:
        sample_subset = samples[: config.source_audit_max_vehicles]
        started = time.perf_counter()
        result = {
            "strategy": strategy,
            "attempted_vehicles": len(sample_subset),
            "detail_success_count": 0,
            "detail_failed_count": 0,
            "http_403_count": 0,
            "http_503_edgesuite_count": 0,
            "timeout_count": 0,
            "fields_extracted_count": 0,
            "extracted_fields_list": [],
            "missing_target_fields_list": [],
            "browser_left_open": False,
            "screenshot_saved": False,
            "response_headers_saved": False,
            "avg_seconds_per_detail": 0.0,
            "example_url": sample_subset[0].url if sample_subset else "",
            "recommendation": "",
            "attempts": [],
        }
        try:
            attempts = await _run_strategy(config, strategy, sample_subset, audit_dir / "detail_strategies" / strategy)
            result["attempts"] = attempts
        except Exception as exc:
            result["error"] = str(exc)
            attempts = []
            result["detail_failed_count"] = len(sample_subset)

        fields_seen: set[str] = set()
        missing: set[str] = set(TARGET_FIELDS)
        for attempt in attempts:
            status = attempt.get("status_code")
            if status == 403:
                result["http_403_count"] += 1
            if status == 503 or attempt.get("edge_error_yes"):
                result["http_503_edgesuite_count"] += 1
            if attempt.get("timeout"):
                result["timeout_count"] += 1
            if attempt.get("detail_page_loaded_yes") and attempt.get("extracted_fields"):
                result["detail_success_count"] += 1
            else:
                result["detail_failed_count"] += 1
            if attempt.get("screenshot_path"):
                result["screenshot_saved"] = True
            if attempt.get("response_headers_path"):
                result["response_headers_saved"] = True
            for field, value in attempt.get("extracted_fields", {}).items():
                if value:
                    fields_seen.add(field)
                    missing.discard(field)

        result["fields_extracted_count"] = len(fields_seen)
        result["extracted_fields_list"] = sorted(fields_seen)
        result["missing_target_fields_list"] = sorted(missing)
        elapsed = time.perf_counter() - started
        result["avg_seconds_per_detail"] = round(elapsed / max(1, len(sample_subset)), 2)
        result["recommendation"] = (
            "candidate" if result["fields_extracted_count"] else "no_target_field_gain"
        )
        matrix.append(result)
    return matrix


async def _run_strategy(
    config: ScraperConfig,
    strategy: str,
    samples: list[VehicleSample],
    strategy_dir: Path,
) -> list[dict[str, Any]]:
    strategy_dir.mkdir(parents=True, exist_ok=True)
    browser_name = _browser_for_strategy(strategy, config.browser)
    persistent = strategy == "direct_url_persistent_context"
    attempts: list[dict[str, Any]] = []
    async with async_playwright() as pw:
        browser, context = await _open_browser_context(
            pw,
            config,
            browser_name,
            persistent_dir=strategy_dir / "_profile" if persistent else None,
        )
        try:
            for index, sample in enumerate(samples, start=1):
                attempt_dir = strategy_dir / f"vehicle_{index}_{_safe_name(sample.url)}"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                recorder = NetworkRecorder(attempt_dir, "detail")
                page = await context.new_page()
                recorder.attach(page)
                try:
                    attempt = await _attempt_strategy_page(strategy, page, sample, attempt_dir)
                finally:
                    payload = await recorder.flush()
                    _write_json(attempt_dir / "network_response_index.json", payload["network_response_index"])
                    _write_json(attempt_dir / "playwright_request_response_log.json", payload["playwright_request_response_log"])
                    _write_json(attempt_dir / "discovered_api_endpoints.json", payload["discovered_api_endpoints"])
                    try:
                        await page.close()
                    except Exception:
                        pass
                attempts.append(attempt)
        finally:
            await _close_context_and_browser(context, browser)
    return attempts


async def _attempt_strategy_page(
    strategy: str,
    page: Page,
    sample: VehicleSample,
    attempt_dir: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    response: Response | None = None
    timeout = False
    error = ""
    detail_page = page
    try:
        if strategy in {"direct_url_fresh_context", "direct_url_persistent_context"} or strategy.startswith("browser_channel_"):
            response = await page.goto(sample.url, wait_until="domcontentloaded", timeout=25_000)
        elif strategy == "same_context_from_vendor":
            await page.goto(sample.vendor_url, wait_until="domcontentloaded", timeout=35_000)
            await _accept_cookies(page)
            await _settle_page(page)
            response = await page.goto(sample.url, wait_until="domcontentloaded", timeout=25_000)
        elif strategy == "same_page_navigation_from_category":
            await page.goto(sample.category_url, wait_until="domcontentloaded", timeout=35_000)
            await _accept_cookies(page)
            await _settle_page(page)
            response = await page.goto(sample.url, wait_until="domcontentloaded", timeout=25_000)
        elif strategy == "click_from_listing":
            response = await _click_listing(page, sample, delayed=False, modifier=False)
        elif strategy == "modifier_click_new_tab":
            popup, response = await _click_listing_popup(page, sample)
            if popup is not None:
                detail_page = popup
        elif strategy == "delayed_click_from_listing":
            response = await _click_listing(page, sample, delayed=True, modifier=False)
        elif strategy == "detail_after_warmup":
            await page.goto("https://home.mobile.de/regional/nordrhein-westfalen/0.html", wait_until="domcontentloaded", timeout=35_000)
            await _accept_cookies(page)
            await _settle_page(page)
            await page.goto(sample.vendor_url, wait_until="domcontentloaded", timeout=35_000)
            await _settle_page(page)
            await page.goto(sample.category_url, wait_until="domcontentloaded", timeout=35_000)
            await _settle_page(page)
            response = await _click_listing(page, sample, delayed=True, modifier=False)
        else:
            response = await page.goto(sample.url, wait_until="domcontentloaded", timeout=25_000)
    except Exception as exc:
        error = str(exc)
        timeout = "timeout" in error.lower()

    await _settle_page(detail_page, short=True)
    html = ""
    body_text = ""
    try:
        html = await detail_page.content()
        body_text = clean_text(await detail_page.locator("body").inner_text(timeout=5000))
    except Exception as exc:
        error = error or str(exc)

    html_path = attempt_dir / "detail_attempt_result.html"
    screenshot_path = attempt_dir / "detail_attempt_screenshot.png"
    headers_path = attempt_dir / "detail_attempt_response_headers.json"
    _write_text(html_path, html)
    screenshot_saved = False
    try:
        await detail_page.screenshot(path=str(screenshot_path), full_page=True)
        screenshot_saved = True
    except Exception:
        screenshot_path = Path("")
    headers = _small_headers(response.headers) if response else {}
    _write_json(headers_path, headers)

    status_code = response.status if response else None
    edge_error = _looks_edgesuite(html, body_text)
    blocked = _looks_blocked(html, body_text)
    extracted = _extract_target_fields(html)
    is_detail_url = _looks_like_detail_url(detail_page.url)
    attempt = {
        "strategy": strategy,
        "url": sample.url,
        "final_url": detail_page.url,
        "status_code": status_code,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "timeout": timeout,
        "error": error,
        "detail_page_loaded_yes": bool(
            html
            and is_detail_url
            and not edge_error
            and not blocked
            and status_code not in {403, 503}
        ),
        "target_fields_present_no": not any(extracted.values()),
        "edge_error_yes": edge_error,
        "blocked_yes": blocked,
        "edgesuite_reference": _extract_edgesuite_reference(body_text or html),
        "extracted_fields": {key: value for key, value in extracted.items() if value},
        "missing_target_fields": [field for field in TARGET_FIELDS if not extracted.get(field)],
        "html_path": str(html_path),
        "screenshot_path": str(screenshot_path) if screenshot_saved else "",
        "response_headers_path": str(headers_path),
        "body_text_excerpt": body_text[:1000],
    }
    if strategy == "direct_url_fresh_context":
        audit_root = attempt_dir.parents[2]
        _write_text(audit_root / "detail_attempt_result.html", html)
        if screenshot_saved:
            try:
                _copy_binary(screenshot_path, audit_root / "detail_attempt_screenshot.png")
            except Exception:
                pass
        _write_json(audit_root / "detail_attempt_response_headers.json", headers)
    _write_json(attempt_dir / "detail_attempt_summary.json", attempt)
    return attempt


async def _click_listing(page: Page, sample: VehicleSample, *, delayed: bool, modifier: bool) -> Response | None:
    await page.goto(sample.category_url, wait_until="domcontentloaded", timeout=35_000)
    await _accept_cookies(page)
    await _settle_page(page)
    locator = await _listing_locator(page, sample.url)
    if delayed:
        await locator.scroll_into_view_if_needed(timeout=8000)
        await locator.hover(timeout=8000)
        await page.wait_for_timeout(1500)
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=18_000) as nav:
            await locator.click(timeout=8000, modifiers=["Control"] if modifier else None)
        return await nav.value
    except Exception:
        await locator.click(timeout=8000, modifiers=["Control"] if modifier else None)
        await page.wait_for_load_state("domcontentloaded", timeout=18_000)
        return None


async def _click_listing_popup(page: Page, sample: VehicleSample) -> tuple[Page | None, Response | None]:
    await page.goto(sample.category_url, wait_until="domcontentloaded", timeout=35_000)
    await _accept_cookies(page)
    await _settle_page(page)
    locator = await _listing_locator(page, sample.url)
    try:
        async with page.expect_popup(timeout=7_000) as popup_info:
            await locator.click(timeout=8000, modifiers=["Control"])
        popup = await popup_info.value
        response = await popup.wait_for_load_state("domcontentloaded", timeout=18_000)
        return popup, None if response is None else response
    except Exception:
        response = await _click_listing(page, sample, delayed=False, modifier=True)
        return page, response


async def _listing_locator(page: Page, url: str):
    parsed = urlparse(url)
    listing_id = dict(parse_qsl(parsed.query)).get("id", "")
    selectors = []
    if listing_id:
        selectors.extend([f'a[href*="{listing_id}"]', f'[href*="{listing_id}"]'])
    selectors.extend(['a[href*="/fahrzeuge/details"]', 'a[href*="/auto-inserat/"]'])
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await page.locator(selector).count() > 0:
                return locator
        except Exception:
            continue
    return page.locator("a").first


async def _open_browser_context(
    pw: Playwright,
    config: ScraperConfig,
    browser_name: str,
    persistent_dir: Path | None = None,
) -> tuple[Browser | None, BrowserContext]:
    headless = config.browser_mode == "headless" or config.headless
    browser_type = pw.firefox if browser_name == "firefox" else pw.chromium
    launch_kwargs: dict[str, Any] = {"headless": headless, "slow_mo": config.slow_mo}
    if browser_name == "chrome":
        launch_kwargs["channel"] = "chrome"
    if browser_name in {"chromium", "chrome"}:
        launch_kwargs["args"] = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1920,1080",
        ]
    context_kwargs = {
        "viewport": {"width": 1920, "height": 1080},
        "screen": {"width": 1920, "height": 1080},
        "locale": "de-DE",
        "timezone_id": "Europe/Berlin",
        "user_agent": DEFAULT_USER_AGENT,
        "extra_http_headers": {"Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"},
        "java_script_enabled": True,
    }
    if persistent_dir is not None:
        persistent_dir.mkdir(parents=True, exist_ok=True)
        context = await browser_type.launch_persistent_context(
            str(persistent_dir),
            **launch_kwargs,
            **context_kwargs,
        )
        return context.browser, context
    browser = await browser_type.launch(**launch_kwargs)
    context = await browser.new_context(**context_kwargs)
    return browser, context


async def _close_context_and_browser(context: BrowserContext, browser: Browser | None) -> None:
    try:
        await context.close()
    except Exception:
        pass
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass


async def _accept_cookies(page: Page) -> None:
    selectors = [
        "button.mde-consent-accept-btn",
        "button:has-text('Einverstanden')",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=1200):
                await locator.click(timeout=3000)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def _settle_page(page: Page, *, short: bool = False) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    try:
        await page.wait_for_timeout(500 if short else 1000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500 if short else 1000)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


async def _dom_listing_cards(page: Page) -> list[dict[str, str]]:
    try:
        return await page.evaluate(
            """
            () => Array.from(document.querySelectorAll('article, [data-testid*="listing"]'))
              .map((el) => {
                const link = el.querySelector('a[href*="/fahrzeuge/details"], a[href*="/auto-inserat/"]');
                const title = el.querySelector('[data-testid$="-title"], h2, h3');
                return {
                  url: link ? link.href : '',
                  title: title ? title.innerText : '',
                  text: el.innerText || ''
                };
              })
              .filter((row) => row.url || row.text)
              .slice(0, 20)
            """
        )
    except Exception:
        return []


def _choose_category_url(vendor_url: str, html: str) -> str:
    options = parse_vehicle_category_options(html, require_positive_count=True)
    values = [str(option.get("value") or "") for option in options]
    category = "Car" if "Car" in values else next((value for value in values if value), "")
    if not category:
        return vendor_url
    parsed = urlparse(vendor_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("page", None)
    query.pop("pageNumber", None)
    query["vc"] = category
    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc or "home.mobile.de",
            parsed.path.rstrip("/") or "/",
            "",
            urlencode(query),
            "",
        )
    )


def _raw_search_result_listings(html: str) -> list[dict[str, Any]]:
    listings: list[dict[str, Any]] = []
    for payload in extract_next_payloads(html):
        for item in walk_json(payload):
            if not isinstance(item, dict):
                continue
            search_results = item.get("searchResults")
            if isinstance(search_results, dict) and isinstance(search_results.get("listings"), list):
                for listing in search_results["listings"]:
                    if isinstance(listing, dict):
                        listings.append(listing)
    return listings


def _extract_target_fields(html: str) -> dict[str, str]:
    specs = parse_vehicle_specs(html)
    extracted = {field: specs.get(field, "") for field in TARGET_FIELDS}
    if "CO2-Emissionen" in specs and not extracted["CO₂-Emissionen"]:
        extracted["CO₂-Emissionen"] = specs["CO2-Emissionen"]
    return {
        field: clean_text(value)
        for field, value in extracted.items()
        if _valid_target_value(field, clean_text(value))
    }


def _valid_target_value(field: str, value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in ["single_select", "{label}", "bis zu", "filter", "suchkriterien"]):
        return False
    if len(value) > 120:
        return False
    if field == "CO₂-Emissionen":
        return bool(re.search(r"\d+\s*g/km", value, re.I))
    if field == "Anzahl der Fahrzeughalter":
        return bool(re.search(r"\b\d+\b", value)) and "bis zu" not in lowered
    return True


def _recursive_keyword_hits(value: Any) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key)
                lowered_key = key_text.lower()
                for field, keywords in TARGET_KEYWORDS.items():
                    if any(term.lower() in lowered_key for term in keywords):
                        hits.append(
                            {
                                "field": field,
                                "path": f"{path}.{key_text}" if path else key_text,
                                "value_excerpt": clean_text(str(child))[:300],
                            }
                        )
                visit(child, f"{path}.{key_text}" if path else key_text)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return hits


def _search_audit_artifacts(audit_dir: Path) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    suffixes = {".html", ".json", ".txt", ".js"}
    for path in audit_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lowered = text.lower()
        for field, keywords in TARGET_KEYWORDS.items():
            for keyword in keywords:
                idx = lowered.find(keyword.lower())
                if idx == -1:
                    continue
                start = max(0, idx - 160)
                end = min(len(text), idx + 300)
                results.append(
                    {
                        "field": field,
                        "keyword": keyword,
                        "path": str(path),
                        "excerpt": clean_text(text[start:end]),
                    }
                )
    return results[:1000]


def _target_fields_found(search_results: list[dict[str, str]], matrix: list[dict[str, Any]]) -> dict[str, Any]:
    found = {
        field: {
            "keyword_hits_in_returned_sources": 0,
            "parsed_from_listing_payload": False,
            "parsed_from_detail_strategy": False,
            "values": [],
        }
        for field in TARGET_FIELDS
    }
    for row in search_results:
        field = row.get("field", "")
        if field in found:
            found[field]["keyword_hits_in_returned_sources"] += 1
    for strategy in matrix:
        for attempt in strategy.get("attempts", []):
            extracted = attempt.get("extracted_fields", {})
            for field, value in extracted.items():
                if field in found and value:
                    found[field]["parsed_from_detail_strategy"] = True
                    if value not in found[field]["values"]:
                        found[field]["values"].append(value)
    return found


def _merge_listing_payload_values(found: dict[str, Any], vendor_results: list[dict[str, Any]]) -> None:
    for vendor in vendor_results:
        for hit in vendor.get("target_key_hits_in_listing_payload", []):
            field = hit.get("field")
            value = clean_text(hit.get("value_excerpt", ""))
            if field not in found or not _valid_target_value(field, value):
                continue
            found[field]["parsed_from_listing_payload"] = True
            if value not in found[field]["values"]:
                found[field]["values"].append(value)


def _recommend_detail_strategy(matrix: list[dict[str, Any]]) -> str:
    candidates = [
        row for row in matrix
        if int(row.get("fields_extracted_count", 0) or 0) > 0
    ]
    if not candidates:
        return "No tested detail strategy extracted target fields; keep listing fallback with source_audit evidence."
    candidates.sort(
        key=lambda row: (
            -int(row.get("fields_extracted_count", 0) or 0),
            float(row.get("avg_seconds_per_detail", 9999) or 9999),
        )
    )
    return f"Use {candidates[0]['strategy']} for missing target fields."


def _browser_for_strategy(strategy: str, default_browser: str) -> str:
    if strategy == "browser_channel_chrome":
        return "chrome"
    if strategy == "browser_channel_firefox":
        return "firefox"
    if strategy == "browser_channel_chromium":
        return "chromium"
    return default_browser


def _looks_edgesuite(html: str, body_text: str) -> bool:
    lowered = f"{html}\n{body_text}".lower()
    return "errors.edgesuite.net" in lowered or "edgesuite" in lowered or "an error occurred while processing your request" in lowered


def _looks_like_detail_url(url: str) -> bool:
    lowered = url.lower()
    return "/fahrzeuge/details" in lowered or "/auto-inserat/" in lowered


def _looks_blocked(html: str, body_text: str) -> bool:
    lowered = f"{html}\n{body_text}".lower()
    return any(
        marker in lowered
        for marker in [
            "zugriff verweigert",
            "access denied",
            "captcha",
            "aus sicherheitsgründen",
            "error reference",
        ]
    )


def _extract_edgesuite_reference(text: str) -> str:
    match = re.search(r"Reference\s*#?([A-Za-z0-9_.-]+)", text, re.I)
    return match.group(1) if match else ""


def _small_headers(headers: dict[str, str]) -> dict[str, str]:
    keep = {
        "content-type",
        "server",
        "date",
        "x-cache",
        "x-akamai",
        "akamai-grn",
        "cache-control",
        "location",
    }
    return {key: value for key, value in headers.items() if key.lower() in keep}


def _should_capture_response_body(url: str, content_type: str, resource_type: str) -> bool:
    parsed = urlparse(url)
    if not parsed.netloc.endswith("mobile.de"):
        return False
    lowered = content_type.lower()
    return "json" in lowered or resource_type in {"xhr", "fetch"}


def _looks_api_endpoint(entry: dict[str, Any]) -> bool:
    url = str(entry.get("url", ""))
    resource_type = str(entry.get("resource_type", ""))
    content_type = str(entry.get("content_type", ""))
    return (
        resource_type in {"xhr", "fetch"}
        or "json" in content_type.lower()
        or "/api/" in url
        or "/svc/" in url
    )


def _body_suffix(content_type: str) -> str:
    lowered = content_type.lower()
    if "json" in lowered:
        return ".json"
    if "html" in lowered:
        return ".html"
    if "javascript" in lowered:
        return ".js"
    return ".txt"


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _safe_name(value: str) -> str:
    parsed = urlparse(value)
    raw = parsed.path.strip("/") or parsed.netloc or value
    if parsed.query:
        raw = f"{raw}_{parsed.query}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-")[:80] or _digest(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value or "", encoding="utf-8", errors="ignore")


def _copy_binary(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
