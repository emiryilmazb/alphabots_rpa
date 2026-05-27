"""Tests for Phase 2 Docker/browser runtime configuration."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from src.config import ScraperConfig, parse_args
from src.scraper.detail_policy import should_fetch_vehicle_detail
from src.scraper.browser import BrowserManager


def test_browser_mode_drives_legacy_headless_flag():
    assert ScraperConfig(browser_mode="headless").headless is True
    assert ScraperConfig(browser_mode="headed").headless is False
    assert ScraperConfig(browser_mode="xvfb").headless is False
    assert ScraperConfig(headless=True).browser_mode == "headless"


def test_parse_browser_options(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--browser",
            "firefox",
            "--browser-mode",
            "headless",
            "--debug",
            "true",
            "--save-debug-artifacts",
            "true",
            "--pipeline-mode",
            "sqlite",
            "--vendor-concurrency",
            "2",
            "--vehicle-detail-concurrency",
            "3",
            "--detail-policy",
            "financing-only",
            "--detail-open-strategy",
            "uc-popup",
            "--detail-max-retries",
            "1",
            "--output-dir",
            str(Path("custom-output")),
            "--clean-run",
            "true",
            "--user-data-dir",
            str(Path("data/browser_profile")),
            "--storage-state",
            str(Path("data/browser_state/state.json")),
        ],
    )

    config = parse_args()

    assert config.browser == "firefox"
    assert config.browser_mode == "headless"
    assert config.headless is True
    assert config.debug is True
    assert config.save_debug_artifacts is True
    assert config.pipeline_mode == "sqlite"
    assert config.vendor_concurrency == 2
    assert config.vehicle_detail_concurrency == 3
    assert config.detail_policy == "financing-only"
    assert config.detail_open_strategy == "uc-popup"
    assert config.detail_max_retries == 1
    assert config.clean_run is True
    assert config.resume is False
    assert config.output_dir == Path("custom-output")
    assert config.user_data_dir == Path("data/browser_profile")
    assert config.storage_state == Path("data/browser_state/state.json")


def test_chrome_launch_uses_channel():
    manager = BrowserManager(ScraperConfig(browser="chrome", browser_mode="headless"))
    kwargs = manager._launch_kwargs(headless=True)

    assert kwargs["headless"] is True
    assert kwargs["channel"] == "chrome"
    assert "--disable-dev-shm-usage" in kwargs["args"]
    assert "--window-size=1920,1080" in kwargs["args"]


def test_artifact_base_name_is_filesystem_safe():
    name = BrowserManager._artifact_base_name("https://example.test/a?b=1", "HTTP 403: blocked")

    assert re.fullmatch(r"[0-9]+-HTTP-403-blocked-[0-9a-f]{12}", name)


def test_detail_policy_uses_listing_data_before_detail_fetch():
    url = "https://suchen.mobile.de/fahrzeuge/details.html?id=123"
    complete = {
        "Markes": "VW",
        "Models": "Golf",
        "Fahrzeugtyp": "Limousine",
        "Preis": "10.000 €",
        "Kilometerstand": "10.000 km",
        "Erstzulassung": "03/2024",
    }

    assert should_fetch_vehicle_detail(ScraperConfig(detail_policy="missing-required"), url, complete) is False
    assert should_fetch_vehicle_detail(ScraperConfig(detail_policy="always"), url, complete) is True
    assert should_fetch_vehicle_detail(ScraperConfig(detail_policy="never"), url, {}) is False
    assert should_fetch_vehicle_detail(ScraperConfig(detail_policy="financing-only"), url, complete) is True
    assert should_fetch_vehicle_detail(
        ScraperConfig(detail_policy="financing-only"),
        url,
        {**complete, "Finanzierung": "100 € mtl."},
    ) is False


def test_uc_popup_missing_required_policy_checks_detail_target_fields():
    url = "https://suchen.mobile.de/fahrzeuge/details.html?id=123456789"
    basic_complete = {
        "Markes": "VW",
        "Models": "Golf",
        "Fahrzeugtyp": "Limousine",
        "Preis": "10.000 €",
        "Kilometerstand": "10.000 km",
        "Erstzulassung": "03/2024",
    }

    assert should_fetch_vehicle_detail(
        ScraperConfig(detail_policy="missing-required", detail_open_strategy="uc-popup"),
        url,
        basic_complete,
    ) is True
    assert should_fetch_vehicle_detail(
        ScraperConfig(detail_policy="missing-required", detail_open_strategy="uc-popup"),
        url,
        {
            **basic_complete,
            "CO₂-Emissionen": "120 g/km",
            "Baureihe": "8",
            "Ausstattungslinie": "Life",
            "Anzahl der Fahrzeughalter": "1",
        },
    ) is False
    assert should_fetch_vehicle_detail(
        ScraperConfig(detail_policy="missing-required", detail_open_strategy="uc-popup"),
        url,
        {
            "Markes": "",
            "Models": "",
            "Fahrzeugtyp": "",
            "Preis": "",
            "Kilometerstand": "",
            "Erstzulassung": "",
            "CO₂-Emissionen": "120 g/km",
            "Baureihe": "8",
            "Ausstattungslinie": "Life",
            "Anzahl der Fahrzeughalter": "1",
        },
    ) is False


def test_docker_image_version_matches_python_requirement():
    root = Path(__file__).resolve().parents[1]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    requirement_version = re.search(r"^playwright==([0-9.]+)$", requirements, re.M).group(1)
    docker_version = re.search(r"ARG PLAYWRIGHT_VERSION=([0-9.]+)", dockerfile).group(1)

    assert docker_version == requirement_version
    assert f'PLAYWRIGHT_VERSION: "{requirement_version}"' in compose
