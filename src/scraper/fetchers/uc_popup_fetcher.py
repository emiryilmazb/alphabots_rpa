"""Undetected-Chromedriver popup/new-tab detail fetcher."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src.config import ScraperConfig
from src.scraper.detail_page import classify_detail_page
from src.scraper.fetchers.base import FetchResult
from src.scraper.parsers import (
    clean_text,
    normalize_vehicle_url,
    parse_vehicle_listing_summaries,
    parse_vehicle_listing_urls,
)

logger = logging.getLogger("mobile_de.fetchers.uc_popup")

UC_DEPENDENCY_MESSAGE = "uc-popup strategy requires undetected_chromedriver and local Chrome."
DETAIL_ID_RE = re.compile(r"(?:[?&]id=|/)(\d{8,})(?:[&#/?]|$)")


@dataclass
class LiveLink:
    url: str
    vehicle_id: str
    text: str = ""


@dataclass
class UcPopupArtifacts:
    html_path: str = ""
    screenshot_path: str = ""
    visible_text_path: str = ""
    extracted_fields_path: str = ""
    result_path: str = ""


@dataclass
class UcPopupResult:
    fetch_result: FetchResult
    selected_url: str = ""
    live_links: list[LiveLink] = field(default_factory=list)
    final_title: str = ""
    artifacts: UcPopupArtifacts = field(default_factory=UcPopupArtifacts)


class UcPopupFetcher:
    """Open a live listing URL from a vendor/category page and capture the popup tab."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._driver = None
        self._listing_url = ""
        self._live_links = []
        self._main_handle = ""

    def close(self):
        if self._driver:
            try:
                self._increment("uc_browser_closed_count")
                self._close_driver(self._driver)
            except Exception:
                pass
            self._driver = None
            self._listing_url = ""
            self._live_links = []
            self._main_handle = ""

    def fetch(
        self,
        vehicle_url: str,
        *,
        fallback: dict[str, Any] | None = None,
        output_dir: Path | None = None,
        allow_unmatched_first: bool = False,
        max_live_links: int = 25,
    ) -> UcPopupResult:
        """Fetch one detail page by matching the job URL against live DOM anchors."""
        fallback = fallback or {}
        started = time.perf_counter()
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            import undetected_chromedriver as uc
        except ModuleNotFoundError as exc:
            return self._failure(
                vehicle_url,
                "uc_dependency_missing",
                UC_DEPENDENCY_MESSAGE,
                started,
                error_type=exc.__class__.__name__,
            )

        output_dir = self._output_dir(output_dir)
        listing_url = self._listing_source_url(fallback)
        if not listing_url:
            return self._failure(
                vehicle_url,
                "missing_listing_source_url",
                "No source_category_url or source_vendor_url was available for live-link matching.",
                started,
            )

        artifacts = UcPopupArtifacts()
        selected_url = ""
        live_links: list[LiveLink] = []
        try:
            reuse_enabled = getattr(self.config, 'uc_reuse_browser', True)
            use_cache = getattr(self.config, 'uc_link_cache', True)
            
            
            
            if reuse_enabled and self._driver:
                if listing_url != self._listing_url:
                    self._increment("uc_browser_restarted_on_listing_change_count")
                    self.close()
            
            if not self._driver:
                self._driver = self._start_driver(uc)
                self._increment("uc_browser_started_count")
                logger.info("UC popup navigating to listing source: %s", listing_url)
                self._driver.get(listing_url)
                self._listing_url = listing_url
                self._main_handle = self._driver.current_window_handle
                
                try:
                    WebDriverWait(self._driver, 10).until(lambda d: d.execute_script("return document.readyState") in ["interactive", "complete"])
                except Exception:
                    pass
                time.sleep(0.5)
                self._accept_cookies(self._driver)
                self._settle_listing_page(self._driver)
                self._live_links = self._collect_live_links(self._driver, By, max_live_links=max_live_links)
            else:
                self._increment("uc_browser_reused_count")
                try:
                    if self._driver.current_window_handle != self._main_handle:
                        self._driver.switch_to.window(self._main_handle)
                except Exception:
                    pass
                if not use_cache or not self._live_links:
                    self._live_links = self._collect_live_links(self._driver, By, max_live_links=max_live_links)
            
            live_links = self._live_links
            selected_url = self._select_live_link(vehicle_url, live_links, allow_unmatched_first=allow_unmatched_first)
            
            if not selected_url:
                self._increment("stale_redirect_count")
                self._increment("uc_popup_skipped_no_live_link_count")
                return self._failure(vehicle_url, "stale_or_not_visible", "Detail URL not in live links.", started, selected_url="", live_links=live_links)

            old_handles = set(self._driver.window_handles)
            self._increment("popup_opened_count")
            self._increment("uc_detail_tabs_opened_count")
            self._driver.execute_script("window.open(arguments[0], '_blank');", selected_url)

            new_handle = self._wait_for_new_handle(self._driver, old_handles, timeout_seconds=5)
            captured_handle = ""
            if new_handle:
                captured_handle = new_handle
                self._driver.switch_to.window(new_handle)
                self._increment("popup_captured_count")
            else:
                if set(self._driver.window_handles) - old_handles:
                    self._increment("wrong_tab_capture_count")
                if clean_text(self._driver.current_url) == clean_text(listing_url):
                    self._increment("popup_capture_failed_count")
                    return self._failure(vehicle_url, "popup_capture_failed", "No new tab captured.", started, selected_url=selected_url, live_links=live_links)
                captured_handle = self._driver.current_window_handle

            self._wait_for_detail_dom(self._driver, WebDriverWait)
            final_url = self._driver.current_url
            title = self._driver.title
            html = self._driver.page_source or ""
            classification = classify_detail_page(html, final_url, title)
            
            artifacts_mode = getattr(self.config, 'detail_artifacts_mode', 'errors')
            is_error = classification.classification != "real_detail_page"
            if artifacts_mode == 'all' or (artifacts_mode == 'errors' and is_error) or getattr(self.config, 'save_debug_artifacts', False):
                artifacts = self._save_artifacts(output_dir, requested_url=vehicle_url, final_url=final_url, title=title, html=html, driver=self._driver)

            self._record_classification_metrics(classification.classification)

            try:
                self._driver.close()
                self._increment("uc_detail_tabs_closed_count")
                self._driver.switch_to.window(self._main_handle)
            except Exception as e:
                logger.debug("Failed to switch back to main handle: %s", e)

            if captured_handle in old_handles and new_handle:
                self._increment("wrong_tab_capture_count")
                return self._failure(vehicle_url, "wrong_tab_capture", "A popup opened, but capture remained on a pre-existing tab.", started, selected_url=selected_url, live_links=live_links, final_url=final_url, html=html, artifacts=artifacts)

            if is_error:
                reason = classification.reason or classification.classification
                if classification.classification == "home_redirect":
                    self._increment("stale_redirect_count")
                self._increment("uc_popup_failed_count")
                return UcPopupResult(
                    fetch_result=FetchResult(url=vehicle_url, final_url=final_url, html=html, strategy="uc-popup", browser="undetected_chromedriver", elapsed_ms=(time.perf_counter() - started) * 1000, error_type=classification.classification, error_message=reason, classification=classification.classification, detail_status=classification.classification, failure_reason=reason, screenshot_path=artifacts.screenshot_path, html_dump_path=artifacts.html_path, visible_text_path=artifacts.visible_text_path, extracted_fields_path=artifacts.extracted_fields_path),
                    selected_url=selected_url, live_links=live_links, final_title=title, artifacts=artifacts)

            self._increment("detail_page_loaded_count")
            self._increment("real_detail_page_loaded_count")
            self._increment("uc_popup_success_count")
            return UcPopupResult(
                fetch_result=FetchResult(url=vehicle_url, final_url=final_url, html=html, strategy="uc-popup", browser="undetected_chromedriver", elapsed_ms=(time.perf_counter() - started) * 1000, classification=classification.classification, detail_status=classification.classification, screenshot_path=artifacts.screenshot_path, html_dump_path=artifacts.html_path, visible_text_path=artifacts.visible_text_path, extracted_fields_path=artifacts.extracted_fields_path),
                selected_url=selected_url, live_links=live_links, final_title=title, artifacts=artifacts)

        except Exception as exc:
            logger.exception("UC popup detail fetch failed for %s: %s", vehicle_url, exc)
            return self._failure(vehicle_url, "uc_popup_exception", str(exc), started, selected_url=selected_url, live_links=live_links, artifacts=artifacts, error_type=exc.__class__.__name__)
        finally:
            reuse_enabled = getattr(self.config, 'uc_reuse_browser', True)
            if not reuse_enabled:
                self.close()

    def _failure(
        self,
        vehicle_url: str,
        reason: str,
        message: str,
        started: float,
        *,
        selected_url: str = "",
        live_links: list[LiveLink] | None = None,
        final_url: str = "",
        html: str = "",
        artifacts: UcPopupArtifacts | None = None,
        error_type: str = "",
    ) -> UcPopupResult:
        self._increment("uc_popup_failed_count")
        artifacts = artifacts or UcPopupArtifacts()
        return UcPopupResult(
            fetch_result=FetchResult(
                url=vehicle_url,
                final_url=final_url or vehicle_url,
                html=html,
                strategy="uc-popup",
                browser="undetected_chromedriver",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_type=error_type or reason,
                error_message=message,
                classification=reason,
                detail_status=reason,
                failure_reason=message,
                screenshot_path=artifacts.screenshot_path,
                html_dump_path=artifacts.html_path,
                visible_text_path=artifacts.visible_text_path,
                extracted_fields_path=artifacts.extracted_fields_path,
            ),
            selected_url=selected_url,
            live_links=live_links or [],
            artifacts=artifacts,
        )

    def _start_driver(self, uc):
        options = uc.ChromeOptions()
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=de-DE")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        import os
        if os.environ.get("UC_BLOCK_RESOURCES", "false").lower() == "true":
            options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
            options.add_argument("--blink-settings=imagesEnabled=false")
        import os
        if os.environ.get("UC_BLOCK_RESOURCES", "false").lower() == "true":
            options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
            options.add_argument("--blink-settings=imagesEnabled=false")
        if getattr(self.config, "uc_block_resources", False):
            options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
            options.add_argument("--blink-settings=imagesEnabled=false")
        if getattr(self.config, 'uc_block_resources', False):
            options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
            options.add_argument("--blink-settings=imagesEnabled=false")
        if self.config.browser_mode == "headless":
            options.add_argument("--headless=new")
        version_raw = os.getenv("UC_CHROME_VERSION_MAIN", "").strip()
        if not version_raw:
            version_raw = self._detect_chrome_major_version()
        kwargs: dict[str, Any] = {"options": options}
        if version_raw.isdigit():
            kwargs["version_main"] = int(version_raw)
        return uc.Chrome(**kwargs)

    def _detect_chrome_major_version(self) -> str:
        registry_version = self._detect_chrome_major_from_registry()
        if registry_version:
            return registry_version
        candidates = [
            os.getenv("CHROME_PATH", ""),
            os.path.join(os.getenv("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.getenv("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.getenv("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ]
        for candidate in [item for item in candidates if item]:
            try:
                completed = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except Exception:
                continue
            match = re.search(r"(\d{2,3})\.", (completed.stdout or completed.stderr or ""))
            if match:
                return match.group(1)
        return ""

    def _detect_chrome_major_from_registry(self) -> str:
        try:
            import winreg
        except Exception:
            return ""
        for root in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            try:
                with winreg.OpenKey(root, r"Software\Google\Chrome\BLBeacon") as key:
                    version, _ = winreg.QueryValueEx(key, "version")
            except Exception:
                continue
            match = re.search(r"(\d{2,3})\.", str(version))
            if match:
                return match.group(1)
        return ""

    def _listing_source_url(self, fallback: dict[str, Any]) -> str:
        for key in ["source_category_url", "Vehicle_Category_URL", "source_vendor_url", "vendor_url"]:
            value = normalize_vehicle_url(str(fallback.get(key, ""))) if key == "Vehicle_URL" else clean_text(fallback.get(key, ""))
            if value:
                return value
        return ""

    def _accept_cookies(self, driver) -> None:
        try:
            clicked = driver.execute_script(
                """
                const buttons = Array.from(document.querySelectorAll('button'));
                const accept = buttons.find((button) => {
                  const text = (button.innerText || '').toLowerCase();
                  return text.includes('akzeptieren') || text.includes('zustimmen')
                    || text.includes('einverstanden') || text.includes('alle akzeptieren');
                });
                if (accept) { accept.click(); return true; }
                return false;
                """
            )
            if clicked:
                self._increment("cookie_consent_click_count")
                time.sleep(0.5)
        except Exception as exc:
            logger.debug("UC cookie accept failed: %s", exc)

    def _settle_listing_page(self, driver) -> None:
        for _ in range(5):
            try:
                driver.execute_script("window.scrollBy(0, 500);")
            except Exception:
                break
            time.sleep(1)

    def _collect_live_links(self, driver, By, *, max_live_links: int = 25) -> list[LiveLink]:
        links: list[LiveLink] = []
        seen: set[str] = set()
        for element in driver.find_elements(By.TAG_NAME, "a"):
            try:
                href = element.get_attribute("href") or ""
                if "details.html" not in href and "/auto-inserat/" not in href:
                    continue
                url = normalize_vehicle_url(href)
                vehicle_id = vehicle_id_from_url(url)
                if not url or not vehicle_id or url in seen:
                    continue
                seen.add(url)
                links.append(LiveLink(url=url, vehicle_id=vehicle_id, text=clean_text(element.text)))
                if len(links) >= max_live_links:
                    break
            except Exception:
                continue
        try:
            html = driver.page_source or ""
            payload_urls = list(parse_vehicle_listing_summaries(html).keys())
            payload_urls.extend(parse_vehicle_listing_urls(html))
            for href in payload_urls:
                url = normalize_vehicle_url(href)
                vehicle_id = vehicle_id_from_url(url)
                if not url or not vehicle_id or url in seen:
                    continue
                seen.add(url)
                links.append(LiveLink(url=url, vehicle_id=vehicle_id, text="live_page_payload"))
                if len(links) >= max_live_links:
                    break
        except Exception as exc:
            logger.debug("UC live payload link extraction failed: %s", exc)
        return links

    def _select_live_link(
        self,
        vehicle_url: str,
        live_links: list[LiveLink],
        *,
        allow_unmatched_first: bool = False,
    ) -> str:
        requested = normalize_vehicle_url(vehicle_url)
        requested_id = vehicle_id_from_url(requested)
        for link in live_links:
            if normalize_vehicle_url(link.url) == requested:
                return link.url
        if requested_id:
            for link in live_links:
                if link.vehicle_id == requested_id:
                    return link.url
        if allow_unmatched_first and live_links:
            return live_links[0].url
        return ""

    def _wait_for_new_handle(self, driver, old_handles: set[str], *, timeout_seconds: int) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current = set(driver.window_handles)
            new_handles = list(current - old_handles)
            if new_handles:
                return new_handles[-1]
            time.sleep(0.5)
        return ""

    def _wait_for_detail_dom(self, driver, WebDriverWait) -> None:
        try:
            WebDriverWait(driver, 10).until(
                lambda current: current.execute_script("return document.readyState") in {"interactive", "complete"}
            )
        except Exception:
            pass
        wait_profile = getattr(self.config, 'uc_popup_wait_profile', 'fast')
        time.sleep(1 if wait_profile == 'safe' else 0.2)

    def _save_artifacts(
        self,
        output_dir: Path,
        *,
        requested_url: str,
        final_url: str,
        title: str,
        html: str,
        driver,
    ) -> UcPopupArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        base = self._artifact_base(requested_url)
        html_path = output_dir / f"{base}.html"
        screenshot_path = output_dir / f"{base}.png"
        visible_text_path = output_dir / f"{base}_visible_text.txt"
        result_path = output_dir / f"{base}_result.json"
        html_path.write_text(html, encoding="utf-8")
        visible_text = clean_text(BeautifulSoup(html, "lxml").get_text(" ", strip=True))
        visible_text_path.write_text(visible_text, encoding="utf-8")
        try:
            driver.save_screenshot(str(screenshot_path))
        except Exception as exc:
            logger.debug("UC screenshot save failed: %s", exc)
            screenshot_path = Path("")
        result_path.write_text(
            json.dumps(
                {
                    "requested_url": requested_url,
                    "final_url": final_url,
                    "title": title,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return UcPopupArtifacts(
            html_path=str(html_path),
            screenshot_path=str(screenshot_path) if str(screenshot_path) else "",
            visible_text_path=str(visible_text_path),
            result_path=str(result_path),
        )

    def _output_dir(self, output_dir: Path | None) -> Path:
        if output_dir is not None:
            return output_dir
        return self.config.debug_dir / "uc_popup"

    def _artifact_base(self, url: str) -> str:
        vehicle_id = vehicle_id_from_url(url) or "vehicle"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{stamp}_{vehicle_id}"

    def _record_classification_metrics(self, classification: str) -> None:
        if classification == "error_page":
            self._increment("detail_error_page_count")
            self._increment("detail_error_page_detected_count")
        elif classification == "home_redirect":
            self._increment("detail_home_redirect_count")
        elif classification == "listing_page":
            self._increment("wrong_tab_capture_count")
        elif classification == "blank_page":
            self._increment("popup_capture_failed_count")

    def _increment(self, name: str, amount: int = 1) -> None:
        setattr(self.config, name, int(getattr(self.config, name, 0) or 0) + amount)

    def _close_driver(self, driver) -> None:
        try:
            handles = list(driver.window_handles)
            for handle in handles[1:]:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except Exception:
                    continue
            if handles:
                try:
                    driver.switch_to.window(handles[0])
                except Exception:
                    pass
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            try:
                driver.quit = lambda *args, **kwargs: None
            except Exception:
                pass


def vehicle_id_from_url(url: str) -> str:
    """Extract a mobile.de listing id from canonical detail URLs."""
    url = clean_text(url)
    if not url:
        return ""
    parsed = urlparse(url)
    query_id = (parse_qs(parsed.query).get("id") or [""])[0]
    if query_id.isdigit():
        return query_id
    match = DETAIL_ID_RE.search(url)
    return match.group(1) if match else ""
