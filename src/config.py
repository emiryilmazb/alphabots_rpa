"""
Configuration module for mobile.de scraper.

All settings can be overridden via CLI arguments or environment variables.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScraperConfig:
    """Central configuration for the mobile.de scraper pipeline."""

    # ── Target ────────────────────────────────────────────────────────────
    state: str = "nordrhein-westfalen"
    base_url: str = "https://home.mobile.de"
    regional_url: str = "https://home.mobile.de/regional"

    # ── Limits (0 = unlimited) ────────────────────────────────────────────
    max_vendors: int = 0
    max_cars_per_vendor: int = 0
    max_pages_per_state: int = 0
    skip_vehicle_details: bool = False
    traverse_vehicle_categories: bool = True
    max_detail_failures: int = 2

    # ── Browser ───────────────────────────────────────────────────────────
    headless: bool = False
    slow_mo: int = 0  # ms between Playwright actions
    fallback_to_headed_on_block: bool = True

    # ── Rate limiting ─────────────────────────────────────────────────────
    min_delay: float = 2.0
    max_delay: float = 5.0

    # ── Retry ─────────────────────────────────────────────────────────────
    max_retries: int = 3
    retry_delay: float = 5.0

    # ── Resume / checkpoint ───────────────────────────────────────────────
    resume: bool = True
    clear_checkpoints: bool = False

    # ── Paths ─────────────────────────────────────────────────────────────
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def checkpoint_dir(self) -> Path:
        return self.data_dir / "checkpoints"

    @property
    def log_dir(self) -> Path:
        return self.project_root / "logs"

    @property
    def state_page_url(self) -> str:
        return f"{self.regional_url}/{self.state}/{{page}}.html"

    @property
    def excel_path(self) -> Path:
        if self.state == "nordrhein-westfalen":
            return self.output_dir / "mobile_de_nrw_dashboard.xlsx"
        return self.output_dir / f"mobile_de_{self.state.replace('-', '_')}_dashboard.xlsx"

    @property
    def word_path(self) -> Path:
        if self.state == "nordrhein-westfalen":
            return self.output_dir / "mobile_de_nrw_report.docx"
        return self.output_dir / f"mobile_de_{self.state.replace('-', '_')}_report.docx"

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        for d in [self.raw_dir, self.processed_dir, self.output_dir,
                  self.checkpoint_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)


def parse_args() -> ScraperConfig:
    """Parse CLI arguments and return a ScraperConfig instance."""
    parser = argparse.ArgumentParser(
        description="mobile.de Vendor & Vehicle Scraper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--state", default=os.getenv("STATE", "nordrhein-westfalen"),
                        help="German state slug to scrape")
    parser.add_argument("--max-vendors", type=int, default=int(os.getenv("MAX_VENDORS", "0")),
                        help="Max vendors to scrape (0 = all)")
    parser.add_argument("--max-cars-per-vendor", type=int, default=int(os.getenv("MAX_CARS_PER_VENDOR", "0")),
                        help="Max cars per vendor (0 = all)")
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("MAX_PAGES_PER_STATE", "0")),
                        help="Max regional pages per state (0 = all)")
    parser.add_argument("--skip-vehicle-details", type=str, default=os.getenv("SKIP_VEHICLE_DETAILS", "false"),
                        choices=["true", "false"],
                        help="Use dealer listing-card data only and skip detail pages")
    parser.add_argument("--traverse-vehicle-categories", type=str, default=os.getenv("TRAVERSE_VEHICLE_CATEGORIES", "true"),
                        choices=["true", "false"],
                        help="Visit all known mobile.de vehicle categories for each vendor")
    parser.add_argument("--max-detail-failures", type=int, default=int(os.getenv("MAX_DETAIL_FAILURES", "2")),
                        help="Disable detail-page requests after this many blocked/5xx detail failures")
    parser.add_argument("--headless", type=str, default=os.getenv("HEADLESS", "false"),
                        choices=["true", "false"],
                        help="Run browser in headless mode")
    parser.add_argument("--fallback-to-headed-on-block", type=str,
                        default=os.getenv("FALLBACK_TO_HEADED_ON_BLOCK", "true"),
                        choices=["true", "false"],
                        help="If headless receives access-denied site protection, restart once in headed mode")
    parser.add_argument("--resume", type=str, default=os.getenv("RESUME", "true"),
                        choices=["true", "false"],
                        help="Resume from checkpoint")
    parser.add_argument("--clear-checkpoints", type=str, default=os.getenv("CLEAR_CHECKPOINTS", "false"),
                        choices=["true", "false"],
                        help="Delete prior checkpoints before scraping")
    parser.add_argument("--min-delay", type=float, default=float(os.getenv("MIN_DELAY", "2.0")),
                        help="Min delay between requests (seconds)")
    parser.add_argument("--max-delay", type=float, default=float(os.getenv("MAX_DELAY", "5.0")),
                        help="Max delay between requests (seconds)")

    args = parser.parse_args()

    return ScraperConfig(
        state=args.state,
        max_vendors=args.max_vendors,
        max_cars_per_vendor=args.max_cars_per_vendor,
        max_pages_per_state=args.max_pages,
        skip_vehicle_details=args.skip_vehicle_details.lower() == "true",
        traverse_vehicle_categories=args.traverse_vehicle_categories.lower() == "true",
        max_detail_failures=args.max_detail_failures,
        headless=args.headless.lower() == "true",
        fallback_to_headed_on_block=args.fallback_to_headed_on_block.lower() == "true",
        resume=args.resume.lower() == "true",
        clear_checkpoints=args.clear_checkpoints.lower() == "true",
        min_delay=args.min_delay,
        max_delay=args.max_delay,
    )
