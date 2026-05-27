"""Isolated UC popup detail-fetch smoke test.

This tool intentionally uses live listing anchors only. In pipeline mode it
must match a requested vehicle id; for this lab tool, unmatched first live link
fallback is allowed so the capture path can be tested without stale URLs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ScraperConfig
from src.scraper.detail_page import classify_detail_page
from src.scraper.fetchers.uc_popup_fetcher import UcPopupFetcher
from src.scraper.parsers import DETAIL_TARGET_FIELDS, parse_vehicle_detail_fields

DEFAULT_CATEGORY_URL = "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&isSearchRequest=true&vc=Car"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UC popup detail integration smoke test")
    parser.add_argument("--vendor-url", default="", help="Optional dealer/vendor source URL")
    parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL, help="Live listing/category URL")
    parser.add_argument("--max-vehicles", type=int, default=2)
    parser.add_argument("--output-dir", default="data/runs/detail_lab_uc_popup_pipeline_test")
    parser.add_argument("--browser-mode", default="headed", choices=["headed", "headless", "xvfb"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    config = ScraperConfig(
        browser_mode=args.browser_mode,
        detail_open_strategy="uc-popup",
        save_debug_artifacts=True,
        output_dir_override=out_dir,
    )
    config.run_id = "detail-lab-uc-popup"
    config.ensure_dirs()
    fetcher = UcPopupFetcher(config)

    source_url = args.category_url or args.vendor_url
    fallback = {
        "source_category_url": source_url,
        "source_vendor_url": args.vendor_url,
    }
    attempted = 0
    results: list[dict[str, object]] = []
    live_links_collected = 0
    popup_captured = 0
    real_detail_loaded = 0
    target_fields_extracted = 0
    values: list[dict[str, str]] = []
    discovered_urls: list[str] = []

    for index in range(max(1, args.max_vehicles)):
        requested_url = discovered_urls[index] if index < len(discovered_urls) else f"live-lab://vehicle-{index + 1}"
        result = fetcher.fetch(
            requested_url,
            fallback=fallback,
            output_dir=out_dir,
            allow_unmatched_first=not discovered_urls,
            max_live_links=max(args.max_vehicles, 2),
        )
        attempted += 1
        if result.live_links and not discovered_urls:
            discovered_urls = [link.url for link in result.live_links]
        live_links_collected = max(live_links_collected, len(result.live_links))
        if result.fetch_result.html:
            popup_captured += 1
        html = result.fetch_result.html
        classification = classify_detail_page(html, result.fetch_result.final_url, result.final_title)
        fields = parse_vehicle_detail_fields(html) if html else {}
        extracted_targets = {
            field: fields.get(field, "")
            for field in DETAIL_TARGET_FIELDS
            if fields.get(field)
        }
        if classification.classification == "real_detail_page":
            real_detail_loaded += 1
        if extracted_targets:
            target_fields_extracted += len(extracted_targets)
            values.append(extracted_targets)

        extracted_path = out_dir / f"vehicle_{index + 1}_extracted_fields.json"
        extracted_path.write_text(json.dumps(fields, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(
            {
                "attempt": index + 1,
                "requested_url": result.fetch_result.url,
                "selected_url": result.selected_url,
                "final_url": result.fetch_result.final_url,
                "title": result.final_title,
                "classification": classification.classification,
                "classification_reason": classification.reason,
                "target_fields": extracted_targets,
                "html_path": result.fetch_result.html_dump_path,
                "screenshot_path": result.fetch_result.screenshot_path,
                "visible_text_path": result.fetch_result.visible_text_path,
                "extracted_fields_path": str(extracted_path),
                "error_type": result.fetch_result.error_type,
                "error_message": result.fetch_result.error_message,
            }
        )
        if not result.live_links:
            break

    summary = {
        "attempted_vehicles": attempted,
        "live_links_collected": live_links_collected,
        "popup_captured_count": popup_captured,
        "real_detail_loaded_count": real_detail_loaded,
        "target_fields_extracted_count": target_fields_extracted,
        "values_extracted": values,
        "artifacts_dir": str(out_dir),
        "metrics": {
            "popup_opened_count": config.popup_opened_count,
            "popup_captured_count": config.popup_captured_count,
            "popup_capture_failed_count": config.popup_capture_failed_count,
            "wrong_tab_capture_count": config.wrong_tab_capture_count,
            "detail_home_redirect_count": config.detail_home_redirect_count,
            "detail_error_page_count": config.detail_error_page_count,
            "uc_popup_success_count": config.uc_popup_success_count,
            "uc_popup_failed_count": config.uc_popup_failed_count,
        },
        "results": results,
    }
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if real_detail_loaded > 0 and target_fields_extracted > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
