"""
Configuration module for mobile.de scraper.

All settings can be overridden via CLI arguments or environment variables.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

VALID_BROWSERS = {"chromium", "chrome", "firefox"}
VALID_BROWSER_MODES = {"headless", "headed", "xvfb"}
VALID_FETCH_STRATEGIES = {"auto", "curl", "playwright"}
VALID_PIPELINE_MODES = {"legacy", "sqlite"}
VALID_DETAIL_POLICIES = {"always", "missing-required", "financing-only", "never"}


@dataclass
class ScraperConfig:
    """Central configuration for the mobile.de scraper pipeline."""

    # ── Target ────────────────────────────────────────────────────────────
    uc_wait_profile: str = "safe"
    uc_block_resources: str = "false"
    state: str = "nordrhein-westfalen"
    base_url: str = "https://home.mobile.de"
    regional_url: str = "https://home.mobile.de/regional"
    start_url: str | None = None

    # ── Limits (0 = unlimited) ────────────────────────────────────────────
    max_vendors: int = 0
    max_cars_per_vendor: int = 0
    max_pages_per_state: int = 0
    discover_only: bool = False
    max_regional_pages: int = 0
    skip_vehicle_details: bool = False
    traverse_vehicle_categories: bool = True
    category_traversal: str = "discovered"
    use_storage_state: bool = True
    max_detail_failures: int = 2

    # ── Browser ───────────────────────────────────────────────────────────
    browser: str = "chromium"
    browser_mode: str | None = None
    headless: bool = False
    slow_mo: int = 0  # ms between Playwright actions
    fallback_to_headed_on_block: bool = True
    debug: bool = False
    save_debug_artifacts: bool = False
    fetch_strategy: str = "auto"
    curl_concurrency: int = 4
    playwright_concurrency: int = 3
    user_data_dir: Path | None = None
    storage_state: Path | None = None
    run_id: str = ""
    process_existing: bool = False
    benchmark: bool = False
    overwrite: bool = False
    regional_discovered_count: int = 0
    enqueued_vendor_count: int = 0
    processed_vendor_count: int = 0
    cookie_modal_visible_count: int = 0
    cookie_consent_click_count: int = 0
    cookie_modal_remaining_count: int = 0
    vehicle_detail_jobs_total: int = 0
    detail_needed_count: int = 0
    detail_skipped_count: int = 0
    detail_attempted_count: int = 0
    detail_success_count: int = 0
    detail_failed_count: int = 0
    detail_fetch_403_count: int = 0
    detail_fetch_503_count: int = 0
    detail_fetch_failed_count: int = 0
    listing_fallback_used_count: int = 0
    detail_site_blocked_or_503_count: int = 0
    detail_error_page_detected_count: int = 0
    detail_browser_closed_after_failure_count: int = 0
    regional_browser_opened_count: int = 0
    vendor_browser_opened_count: int = 0
    vehicle_detail_browser_opened_count: int = 0
    active_playwright_browser_count: int = 0
    max_active_playwright_browser_count: int = 0
    idle_about_blank_count: int = 0
    host_chrome_cdp_used_count: int = 0
    host_chrome_cdp_success_count: int = 0
    host_chrome_cdp_failed_count: int = 0
    host_chrome_cdp_blocked_count: int = 0

    # ── Pipeline ──────────────────────────────────────────────────────────
    pipeline_mode: str = "sqlite"
    regional_concurrency: int = 1
    vendor_concurrency: int = 1
    vehicle_listing_concurrency: int = 1
    vehicle_detail_concurrency: int = 1
    detail_policy: str = "missing-required"
    detail_open_strategy: str = "auto"
    chrome_cdp_url: str = "http://127.0.0.1:9222"
    idle_browser_timeout_seconds: float = 15.0
    flush_every: int = 100

    # ── Rate limiting ─────────────────────────────────────────────────────
    min_delay: float = 2.0
    max_delay: float = 5.0

    # ── Retry ─────────────────────────────────────────────────────────────
    max_retries: int = 3
    detail_max_retries: int = 1
    retry_delay: float = 5.0

    # ── Resume / checkpoint ───────────────────────────────────────────────
    resume: bool = True
    clean_run: bool = False
    force_resume: bool = False
    clear_checkpoints: bool = False
    clear_state: bool = False
    checkpoint_every: int = 50

    # ── Paths ─────────────────────────────────────────────────────────────
    project_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent.parent
    )
    output_dir_override: Path | None = None
    input_dir_override: Path | None = None

    def __post_init__(self) -> None:
        self.browser = self.browser.lower()
        if self.browser not in VALID_BROWSERS:
            raise ValueError(f"Unsupported browser: {self.browser}")

        if self.browser_mode is None:
            self.browser_mode = "headless" if self.headless else "headed"
        self.browser_mode = self.browser_mode.lower()
        if self.browser_mode not in VALID_BROWSER_MODES:
            raise ValueError(f"Unsupported browser mode: {self.browser_mode}")
        self.headless = self.browser_mode == "headless"
        self.fetch_strategy = self.fetch_strategy.lower()
        if self.fetch_strategy not in VALID_FETCH_STRATEGIES:
            raise ValueError(f"Unsupported fetch strategy: {self.fetch_strategy}")
        self.curl_concurrency = max(1, int(self.curl_concurrency))
        self.playwright_concurrency = max(1, int(self.playwright_concurrency))
        self.pipeline_mode = self.pipeline_mode.lower()
        if self.pipeline_mode not in VALID_PIPELINE_MODES:
            raise ValueError(f"Unsupported pipeline mode: {self.pipeline_mode}")
        self.regional_concurrency = max(1, int(self.regional_concurrency))
        self.vendor_concurrency = max(1, int(self.vendor_concurrency))
        self.vehicle_listing_concurrency = max(1, int(self.vehicle_listing_concurrency))
        self.vehicle_detail_concurrency = max(1, int(self.vehicle_detail_concurrency))
        self.detail_policy = self.detail_policy.lower()
        if self.detail_policy not in VALID_DETAIL_POLICIES:
            raise ValueError(f"Unsupported detail policy: {self.detail_policy}")
        self.detail_open_strategy = self.detail_open_strategy.lower()
        self.chrome_cdp_url = str(self.chrome_cdp_url or "http://127.0.0.1:9222")
        self.flush_every = max(1, int(self.flush_every))
        if self.clean_run:
            self.resume = False
            self.clear_checkpoints = True
            self.clear_state = True
        if self.user_data_dir is not None:
            self.user_data_dir = Path(self.user_data_dir)
        if self.storage_state is not None:
            self.storage_state = Path(self.storage_state)
        if self.output_dir_override is not None:
            self.output_dir_override = Path(self.output_dir_override)

    @property
    def data_dir(self) -> Path:
        base = self.project_root / "data"
        if not self.overwrite and self.run_id:
            raw_cars = base / "raw" / "cars_raw.json"
            db_file = (
                base / "state" / f"mobile_de_{self.state.replace('-', '_')}.sqlite3"
            )
            raw_exists = raw_cars.exists() and raw_cars.stat().st_size > 50000
            db_exists = db_file.exists() and db_file.stat().st_size > 50000
            if raw_exists or db_exists:
                return base / "runs" / self.run_id
        return base

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def output_dir(self) -> Path:
        if self.output_dir_override is not None:
            return self.output_dir_override
        return self.data_dir / "output"

    @property
    def checkpoint_dir(self) -> Path:
        return self.data_dir / "checkpoints"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def sqlite_path(self) -> Path:
        return self.state_dir / f"mobile_de_{self.state.replace('-', '_')}.sqlite3"

    @property
    def debug_dir(self) -> Path:
        return self.data_dir / "debug"

    @property
    def log_dir(self) -> Path:
        return self.project_root / "logs"

    @property
    def state_page_url(self) -> str:
        if self.start_url:
            return self.start_url if "{page}" in self.start_url else self.start_url
        return f"{self.regional_url}/{self.state}/{{page}}.html"

    @property
    def excel_path(self) -> Path:
        if self.state == "nordrhein-westfalen":
            return self.output_dir / "mobile_de_nrw_dashboard.xlsx"
        return (
            self.output_dir / f"mobile_de_{self.state.replace('-', '_')}_dashboard.xlsx"
        )

    @property
    def word_path(self) -> Path:
        if self.state == "nordrhein-westfalen":
            return self.output_dir / "mobile_de_nrw_report.docx"
        return self.output_dir / f"mobile_de_{self.state.replace('-', '_')}_report.docx"

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        for d in [
            self.raw_dir,
            self.processed_dir,
            self.output_dir,
            self.checkpoint_dir,
            self.state_dir,
            self.debug_dir,
            self.log_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
        if self.user_data_dir is not None:
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
        if self.storage_state is not None:
            self.storage_state.parent.mkdir(parents=True, exist_ok=True)


def parse_args() -> ScraperConfig:
    """Parse CLI arguments and return a ScraperConfig instance."""
    parser = argparse.ArgumentParser(
        description="mobile.de Vendor & Vehicle Scraper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--state",
        default=os.getenv("STATE", "nordrhein-westfalen"),
        help="German state slug to scrape",
    )
    parser.add_argument(
        "--start-url",
        default=os.getenv("START_URL"),
        help="Optional regional start URL/template. Use {page} for paginated templates.",
    )
    parser.add_argument(
        "--max-vendors",
        type=int,
        default=int(os.getenv("MAX_VENDORS", "0")),
        help="Max vendors to scrape (0 = all)",
    )
    parser.add_argument(
        "--max-cars-per-vendor",
        type=int,
        default=int(os.getenv("MAX_CARS_PER_VENDOR", "0")),
        help="Max cars per vendor (0 = all)",
    )
    parser.add_argument(
        "--max-vehicles-per-vendor",
        type=int,
        default=None,
        help="Alias for --max-cars-per-vendor",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=int(os.getenv("MAX_PAGES_PER_STATE", "0")),
        help="Max regional pages per state (0 = all)",
    )
    parser.add_argument(
        "--skip-vehicle-details",
        type=str,
        default=os.getenv("SKIP_VEHICLE_DETAILS", "false"),
        choices=["true", "false"],
        help="Use dealer listing-card data only and skip detail pages",
    )
    parser.add_argument(
        "--traverse-vehicle-categories",
        type=str,
        default=os.getenv("TRAVERSE_VEHICLE_CATEGORIES", "true"),
        choices=["true", "false"],
        help="Legacy boolean",
    )
    parser.add_argument(
        "--category-traversal",
        type=str,
        default=os.getenv("CATEGORY_TRAVERSAL", "discovered"),
        choices=["discovered", "all", "off"],
        help="Category traversal mode",
    )
    parser.add_argument(
        "--use-storage-state",
        type=str,
        default=os.getenv("USE_STORAGE_STATE", "true"),
        choices=["true", "false"],
    )
    parser.add_argument(
        "--max-detail-failures",
        type=int,
        default=int(os.getenv("MAX_DETAIL_FAILURES", "2")),
        help="Disable detail-page requests after this many blocked/5xx detail failures",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=int(os.getenv("MAX_RETRIES", "3")),
        help="Maximum navigation/fetch retries per URL",
    )
    parser.add_argument(
        "--detail-max-retries",
        type=int,
        default=int(os.getenv("DETAIL_MAX_RETRIES", "1")),
        help="Maximum Playwright navigation retries for vehicle detail pages",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=float(os.getenv("RETRY_DELAY", "5.0")),
        help="Base retry delay in seconds",
    )
    parser.add_argument(
        "--browser",
        default=os.getenv("BROWSER", "chromium"),
        choices=sorted(VALID_BROWSERS),
        help="Playwright browser engine/channel",
    )
    parser.add_argument(
        "--browser-mode",
        default=os.getenv("BROWSER_MODE"),
        choices=sorted(VALID_BROWSER_MODES),
        help="Browser display mode. xvfb expects an entrypoint such as xvfb-run.",
    )
    parser.add_argument(
        "--headless",
        type=str,
        default=os.getenv("HEADLESS"),
        choices=["true", "false"],
        help="Backward-compatible shortcut for --browser-mode=headless",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=int(os.getenv("SLOW_MO", "0")),
        help="Milliseconds to slow Playwright actions",
    )
    parser.add_argument(
        "--fallback-to-headed-on-block",
        type=str,
        default=os.getenv("FALLBACK_TO_HEADED_ON_BLOCK", "true"),
        choices=["true", "false"],
        help="If headless receives access-denied site protection, restart once in headed mode",
    )
    parser.add_argument(
        "--debug",
        type=str,
        default=os.getenv("DEBUG", "false"),
        choices=["true", "false"],
        help="Enable verbose debug behavior",
    )
    parser.add_argument(
        "--save-debug-artifacts",
        type=str,
        default=os.getenv("SAVE_DEBUG_ARTIFACTS", "false"),
        choices=["true", "false"],
        help="Save HTML and screenshot artifacts when page navigation fails",
    )
    parser.add_argument(
        "--fetch-strategy",
        default=os.getenv("FETCH_STRATEGY", "auto"),
        choices=sorted(VALID_FETCH_STRATEGIES),
        help="Page fetch strategy. auto tries curl for static HTML and falls back to Playwright.",
    )
    parser.add_argument(
        "--curl-concurrency",
        type=int,
        default=int(os.getenv("CURL_CONCURRENCY", "4")),
        help="Maximum concurrent curl_cffi fetches",
    )
    parser.add_argument(
        "--playwright-concurrency",
        type=int,
        default=int(os.getenv("PLAYWRIGHT_CONCURRENCY", "3")),
        help="Maximum concurrent Playwright-backed fetches in newer pipeline modes",
    )
    parser.add_argument(
        "--user-data-dir",
        default=os.getenv("USER_DATA_DIR"),
        help="Optional persistent Playwright profile directory",
    )
    parser.add_argument(
        "--storage-state",
        default=os.getenv("STORAGE_STATE"),
        help="Optional Playwright storage_state JSON path to load/save cookies/session state",
    )
    parser.add_argument(
        "--pipeline-mode",
        default=os.getenv("PIPELINE_MODE", "sqlite"),
        choices=sorted(VALID_PIPELINE_MODES),
        help="Execution engine. legacy keeps the existing sequential scraper; sqlite enables the durable queue pipeline.",
    )
    parser.add_argument(
        "--regional-concurrency",
        type=int,
        default=int(os.getenv("REGIONAL_CONCURRENCY", "1")),
        help="Regional discovery concurrency placeholder; current regional discovery is intentionally single-producer",
    )
    parser.add_argument(
        "--vendor-concurrency",
        type=int,
        default=int(os.getenv("VENDOR_CONCURRENCY", "1")),
        help="Concurrent vendor workers for sqlite pipeline",
    )
    parser.add_argument(
        "--vehicle-listing-concurrency",
        type=int,
        default=int(os.getenv("VEHICLE_LISTING_CONCURRENCY", "1")),
        help="Concurrent listing workers placeholder; vendor workers own listing traversal",
    )
    parser.add_argument(
        "--vehicle-detail-concurrency",
        type=int,
        default=int(os.getenv("VEHICLE_DETAIL_CONCURRENCY", "1")),
        help="Concurrent vehicle detail workers for sqlite pipeline",
    )
    parser.add_argument(
        "--detail-open-strategy",
        type=str,
        default=os.getenv("DETAIL_OPEN_STRATEGY", "auto"),
    )
    parser.add_argument(
        "--chrome-cdp-url",
        type=str,
        default=os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222"),
        help="Existing host Chrome remote debugging endpoint for --detail-open-strategy host-chrome-cdp",
    )
    parser.add_argument(
        "--detail-policy",
        default=os.getenv("DETAIL_POLICY", "missing-required"),
        choices=sorted(VALID_DETAIL_POLICIES),
        help="When vehicle detail pages are fetched after listing/card parsing",
    )
    parser.add_argument(
        "--idle-browser-timeout-seconds",
        type=float,
        default=float(os.getenv("IDLE_BROWSER_TIMEOUT_SECONDS", "15")),
        help="Close reusable worker browsers after this many idle seconds (0 disables idle close)",
    )
    parser.add_argument(
        "--resume",
        type=str,
        default=os.getenv("RESUME", "true"),
        choices=["true", "false"],
        help="Resume from checkpoint",
    )
    parser.add_argument(
        "--clean-run",
        type=str,
        default=os.getenv("CLEAN_RUN", "false"),
        choices=["true", "false"],
        help="Start from a clean checkpoint/state; disables resume",
    )
    parser.add_argument(
        "--force-resume",
        type=str,
        default=os.getenv("FORCE_RESUME", "false"),
        choices=["true", "false"],
        help="Allow resume despite config-hash mismatch where supported",
    )
    parser.add_argument(
        "--clear-checkpoints",
        type=str,
        default=os.getenv("CLEAR_CHECKPOINTS", "false"),
        choices=["true", "false"],
        help="Delete prior checkpoints before scraping",
    )
    parser.add_argument(
        "--clear-state",
        type=str,
        default=os.getenv("CLEAR_STATE", "false"),
        choices=["true", "false"],
        help="Delete SQLite state before running the sqlite pipeline",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=int(os.getenv("CHECKPOINT_EVERY", "50")),
        help="Save JSON checkpoints after this many new records (0 = final save only)",
    )
    parser.add_argument(
        "--flush-every",
        type=int,
        default=int(os.getenv("FLUSH_EVERY", "100")),
        help="Batch flush size for durable writers",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing >50KB files"
    )
    parser.add_argument("--process-existing", "--skip-scrape", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--input-dir")
    parser.add_argument(
        "--output-dir",
        default=os.getenv("OUTPUT_DIR"),
        help="Optional directory for final Excel/Word/errors outputs",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=float(os.getenv("MIN_DELAY", "2.0")),
        help="Min delay between requests (seconds)",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=float(os.getenv("MAX_DELAY", "5.0")),
        help="Max delay between requests (seconds)",
    )
    parser.add_argument(
        "--uc-wait-profile",
        default=os.getenv("UC_WAIT_PROFILE", "safe"),
        choices=["safe", "adaptive"],
        help="Wait profile for undetected-chromedriver",
    )
    parser.add_argument(
        "--uc-block-resources",
        default=os.getenv("UC_BLOCK_RESOURCES", "false"),
        choices=["true", "false"],
        help="Block images/fonts in undetected-chromedriver",
    )

    args = parser.parse_args()
    headless = args.headless.lower() == "true" if args.headless is not None else False
    browser_mode = args.browser_mode or ("headless" if headless else "headed")

    max_cars_per_vendor = (
        args.max_vehicles_per_vendor
        if args.max_vehicles_per_vendor is not None
        else args.max_cars_per_vendor
    )

    return ScraperConfig(
        state=args.state,
        uc_wait_profile=args.uc_wait_profile,
        uc_block_resources=args.uc_block_resources.lower(),
        start_url=args.start_url,
        max_vendors=args.max_vendors,
        max_cars_per_vendor=max_cars_per_vendor,
        max_pages_per_state=args.max_pages,
        skip_vehicle_details=args.skip_vehicle_details.lower() == "true",
        traverse_vehicle_categories=args.traverse_vehicle_categories.lower() == "true",
        category_traversal=args.category_traversal,
        use_storage_state=args.use_storage_state.lower() == "true",
        max_detail_failures=args.max_detail_failures,
        max_retries=args.max_retries,
        detail_max_retries=max(1, args.detail_max_retries),
        retry_delay=args.retry_delay,
        browser=args.browser,
        browser_mode=browser_mode,
        slow_mo=args.slow_mo,
        fallback_to_headed_on_block=args.fallback_to_headed_on_block.lower() == "true",
        debug=args.debug.lower() == "true",
        save_debug_artifacts=args.save_debug_artifacts.lower() == "true",
        fetch_strategy=args.fetch_strategy,
        curl_concurrency=args.curl_concurrency,
        playwright_concurrency=args.playwright_concurrency,
        user_data_dir=Path(args.user_data_dir) if args.user_data_dir else None,
        storage_state=Path(args.storage_state)
        if args.storage_state
        else (
            Path(__file__).resolve().parent.parent
            / "data"
            / "browser_state"
            / "mobile_de_storage_state.json"
        ),
        pipeline_mode=args.pipeline_mode,
        process_existing=args.process_existing,
        benchmark=args.benchmark,
        regional_concurrency=args.regional_concurrency,
        vendor_concurrency=args.vendor_concurrency,
        vehicle_listing_concurrency=args.vehicle_listing_concurrency,
        vehicle_detail_concurrency=args.vehicle_detail_concurrency,
        detail_policy=args.detail_policy,
        detail_open_strategy=getattr(args, "detail_open_strategy", "auto"),
        chrome_cdp_url=args.chrome_cdp_url,
        idle_browser_timeout_seconds=max(0.0, args.idle_browser_timeout_seconds),
        resume=args.resume.lower() == "true",
        clean_run=args.clean_run.lower() == "true",
        force_resume=args.force_resume.lower() == "true",
        clear_checkpoints=args.clear_checkpoints.lower() == "true",
        clear_state=args.clear_state.lower() == "true",
        checkpoint_every=max(0, args.checkpoint_every),
        flush_every=max(1, args.flush_every),
        overwrite=getattr(args, "overwrite", False),
        output_dir_override=Path(args.output_dir) if args.output_dir else None,
        input_dir_override=Path(args.input_dir)
        if getattr(args, "input_dir", None)
        else None,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
    )
