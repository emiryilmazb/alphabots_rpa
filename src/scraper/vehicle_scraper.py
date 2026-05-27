"""
Vehicle detail page scraper.

Navigates to each vehicle listing and extracts all required fields
from the detail page, including technical specs and financing info.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from src.config import ScraperConfig
from src.scraper.browser import BrowserManager
from src.scraper.fetchers import FetchResult, FetchStrategyManager, StaticValidation
from src.scraper.fetchers.uc_popup_fetcher import UcPopupFetcher
from src.scraper.parsers import (
    DETAIL_TARGET_FIELDS,
    clean_text,
    normalize_vehicle_url,
    parse_vehicle_title,
    parse_vehicle_price,
    parse_vehicle_specs,
    parse_vehicle_detail_fields,
    parse_financing_data,
    parse_vehicle_listing_urls,
    parse_vehicle_listing_summaries,
    parse_vehicle_category_values,
    parse_vehicle_category_options,
    DEFAULT_VEHICLE_CATEGORY_VALUES,
    VEHICLE_CATEGORY_LABELS,
    split_vehicle_title,
    extract_listing_attribute_fields,
)

logger = logging.getLogger("mobile_de.vehicle")


def _unique_urls(urls: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


class VehicleScraper:
    """Extracts vehicle details from individual listing pages."""

    def __init__(self, browser: BrowserManager, config: ScraperConfig):
        self.browser = browser
        self.config = config
        self.fetch_manager = FetchStrategyManager(config, browser)
        self.uc_popup_fetcher = UcPopupFetcher(config)
        self.listing_summaries: dict[str, dict[str, str]] = {}
        self.category_metadata: dict[str, dict[str, Any]] = {}
        self.last_category_report: list[dict[str, Any]] = []

    async def collect_vehicle_urls(self, dealer_url: str) -> list[str]:
        """
        Collect all vehicle listing URLs from a dealer's page.

        Paginates through the dealer's vehicle listings if there are
        multiple pages.

        Args:
            dealer_url: The dealer's home page URL.

        Returns:
            List of vehicle detail URLs.
        """
        entries = await self.collect_vehicle_entries(dealer_url)
        return [entry["Vehicle_URL"] for entry in entries if entry.get("Vehicle_URL")]

    async def collect_vehicle_entries(self, dealer_url: str) -> list[dict[str, str]]:
        """Collect vehicle listing-card records from every dealer inventory category."""
        entries_by_key: dict[str, dict[str, str]] = {}
        self.category_metadata = {}
        self.last_category_report = []
        category_values = await self._category_sequence_from_current_page()
        visited_categories = 0
        empty_categories = 0
        visited_category_urls: list[str] = []
        for category_index, category_value in enumerate(category_values):
            current_category_url = dealer_url
            metadata = self.category_metadata.get(category_value or "", {})
            category_report = {
                "category": category_value or "base",
                "label": metadata.get("source_category_label") or VEHICLE_CATEGORY_LABELS.get(category_value or "", "base"),
                "count": metadata.get("source_category_count"),
                "url": current_category_url,
                "visited": False,
                "skipped": False,
                "skip_reason": "",
                "vehicle_count": 0,
            }
            if category_value:
                category_url = self._dealer_category_url(dealer_url, category_value)
                current_category_url = category_url
                category_report["url"] = category_url
                metadata = self.category_metadata.setdefault(category_value, {})
                metadata.setdefault("source_category", category_value)
                metadata.setdefault("source_category_label", VEHICLE_CATEGORY_LABELS.get(category_value, ""))
                metadata["source_category_url"] = category_url
                if not await self.browser.safe_goto(category_url):
                    category_report["skipped"] = True
                    category_report["skip_reason"] = self.browser.last_error or "navigation_failed"
                    self.last_category_report.append(category_report)
                    logger.debug(
                        "Skipping vehicle category %s for %s: %s",
                        category_value,
                        dealer_url,
                        self.browser.last_error,
                    )
                    continue
            visited_category_urls.append(current_category_url)
            category_report["visited"] = True

            category_entries = await self._collect_entries_from_loaded_inventory(
                dealer_url,
                category_value,
                len(entries_by_key),
            )
            new_entries_in_category = 0
            for entry in category_entries:
                key = self._entry_key(entry)
                is_new = key not in entries_by_key
                existing = entries_by_key.get(key, {})
                entries_by_key[key] = self._merge_entry(existing, entry)
                if is_new:
                    new_entries_in_category += 1
                if self.config.max_cars_per_vendor > 0 and len(entries_by_key) >= self.config.max_cars_per_vendor:
                    break
            if new_entries_in_category:
                visited_categories += 1
            else:
                empty_categories += 1
            category_report["vehicle_count"] = new_entries_in_category
            self.last_category_report.append(category_report)
            if self.config.max_cars_per_vendor > 0 and len(entries_by_key) >= self.config.max_cars_per_vendor:
                remaining_categories = [
                    str(value)
                    for value in category_values[category_index + 1 :]
                    if value
                ]
                if remaining_categories:
                    reason = f"max_cars_per_vendor reached after {category_value or 'current'}"
                    for remaining in remaining_categories:
                        remaining_metadata = self.category_metadata.get(remaining, {})
                        self.last_category_report.append(
                            {
                                "category": remaining,
                                "label": remaining_metadata.get("source_category_label") or VEHICLE_CATEGORY_LABELS.get(remaining, ""),
                                "count": remaining_metadata.get("source_category_count"),
                                "url": self._dealer_category_url(dealer_url, remaining),
                                "visited": False,
                                "skipped": True,
                                "skip_reason": reason,
                                "vehicle_count": 0,
                            }
                        )
                    logger.info(
                        "max-cars-per-vendor reached after %s; skipping remaining categories: %s",
                        category_value or "current",
                        ", ".join(remaining_categories),
                    )
                break
            await self.browser.polite_delay()

        entries = list(entries_by_key.values())
        logger.info(
            "Found %d vehicle listing cards for dealer across %d populated categories.",
            len(entries),
            visited_categories,
        )
        logger.info(
            "Vehicle category traversal summary for %s: category_urls=%s skipped_empty_categories=%d",
            dealer_url,
            ",".join(visited_category_urls) or dealer_url,
            empty_categories,
        )
        for report in self.last_category_report:
            logger.info(
                "Vehicle category result for %s: category=%s count=%s visited=%s skipped=%s reason=%s vehicles=%d url=%s",
                dealer_url,
                report["category"],
                report.get("count"),
                report["visited"],
                report["skipped"],
                report.get("skip_reason", ""),
                report["vehicle_count"],
                report["url"],
            )
        return entries

    async def _collect_entries_from_loaded_inventory(
        self,
        dealer_url: str,
        category_value: str | None,
        existing_count: int,
    ) -> list[dict[str, str]]:
        """Collect paginated listing cards from the currently loaded category."""
        entries: list[dict[str, str]] = []
        seen: set[str] = set()
        page = self.browser.page
        category_metadata = self.category_metadata.get(category_value or "", {})

        logger.debug(
            "Collecting vehicle entries from: %s category=%s",
            dealer_url,
            category_value or "current",
        )

        page_index = 0
        while True:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.debug("Vehicle list network idle wait timed out.")
            await self._settle_listing_page()

            html = await page.content()
            structured_summaries = parse_vehicle_listing_summaries(html)
            for url, summary in structured_summaries.items():
                self._apply_category_fallback(summary, category_value, category_metadata)
                self.listing_summaries[url] = self._merge_entry(
                    self.listing_summaries.get(url, {}),
                    summary,
                )
                if url not in seen:
                    seen.add(url)
                    entries.append(self.listing_summaries[url])

            page_urls = _unique_urls(
                [normalize_vehicle_url(url) for url in parse_vehicle_listing_urls(html)]
                + await self._extract_vehicle_urls_from_dom()
            )
            dom_summaries = await self._extract_listing_summaries_from_dom(category_value)

            for summary_index, summary in enumerate(dom_summaries):
                summary_url = normalize_vehicle_url(summary.get("Vehicle_URL", ""))
                if not summary_url and summary_index < len(page_urls):
                    summary_url = page_urls[summary_index]
                if not summary_url:
                    summary_url = self._synthetic_vehicle_url(
                        dealer_url,
                        page_index,
                        summary_index,
                        summary,
                        category_value,
                    )
                summary["Vehicle_URL"] = summary_url
                self._apply_category_fallback(summary, category_value, category_metadata)
                self.listing_summaries[summary_url] = self._merge_entry(
                    self.listing_summaries.get(summary_url, {}),
                    summary,
                )
                if summary_url not in seen:
                    seen.add(summary_url)
                    entries.append(self.listing_summaries[summary_url])

            for url in page_urls:
                if url in seen:
                    continue
                summary = self.listing_summaries.get(url, {"Vehicle_URL": url})
                self._apply_category_fallback(summary, category_value, category_metadata)
                seen.add(url)
                entries.append(summary)

            if (
                self.config.max_cars_per_vendor > 0
                and existing_count + len(entries) >= self.config.max_cars_per_vendor
            ):
                allowed = self.config.max_cars_per_vendor - existing_count
                entries = entries[:allowed]
                break

            if not await self._go_to_next_listing_page(page):
                break

            page_index += 1
            if page_index > 1000:
                logger.warning("Stopping listing pagination after 1000 pages for %s", dealer_url)
                break
            await self.browser.polite_delay()

        return entries

    async def _category_sequence_from_current_page(self) -> list[str | None]:
        mode = getattr(self.config, "category_traversal", "discovered")

        # --category-traversal off  OR  legacy --traverse-vehicle-categories false
        if mode == "off" or not self.config.traverse_vehicle_categories:
            return [None]

        try:
            html = await self.browser.page.content()
        except Exception:
            html = ""
        discovered_options = parse_vehicle_category_options(html, require_positive_count=True)
        self.category_metadata = {
            str(option["value"]): {
                "source_category": str(option["value"]),
                "source_category_label": str(option.get("label") or VEHICLE_CATEGORY_LABELS.get(str(option["value"]), "")),
                "source_category_count": option.get("count"),
                "source_category_url": str(option.get("url") or ""),
            }
            for option in discovered_options
            if option.get("value")
        }
        discovered = [str(option["value"]) for option in discovered_options if option.get("value")]

        if mode == "all":
            # Legacy brute-force: discovered first, then all hardcoded (deduplicated)
            if not discovered:
                discovered = parse_vehicle_category_values(html)
            if not discovered:
                return [None, *DEFAULT_VEHICLE_CATEGORY_VALUES]
            sequence: list[str | None] = []
            for value in [*discovered, *DEFAULT_VEHICLE_CATEGORY_VALUES]:
                if value not in sequence:
                    sequence.append(value)
            return sequence

        # mode == "discovered" (default)
        if discovered:
            logger.info(
                "Discovered %d vehicle categories from dealer page: %s",
                len(discovered),
                ", ".join(discovered),
            )
            return discovered
        else:
            logger.warning(
                "Could not parse category sidebar; using current/base page only."
            )
            return [None]

    @staticmethod
    def _dealer_category_url(dealer_url: str, category_value: str) -> str:
        parsed = urlparse(dealer_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.pop("page", None)
        query.pop("pageNumber", None)
        query["vc"] = category_value
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

    @staticmethod
    def _entry_key(entry: dict[str, str]) -> str:
        return (
            normalize_vehicle_url(entry.get("Vehicle_URL", ""))
            or "|".join(
                clean_text(entry.get(key, ""))
                for key in ["Markes", "Models", "Preis", "Kilometerstand", "Erstzulassung"]
            )
        )

    @staticmethod
    def _merge_entry(existing: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
        merged = dict(existing)
        for key, value in incoming.items():
            if value and not merged.get(key):
                merged[key] = value
        if sum(bool(clean_text(v)) for v in incoming.values()) > sum(bool(clean_text(v)) for v in existing.values()):
            for key, value in incoming.items():
                if value:
                    merged[key] = value
        return merged

    @staticmethod
    def _apply_category_fallback(
        summary: dict[str, str],
        category_value: str | None,
        category_metadata: dict[str, Any] | None = None,
    ) -> None:
        if category_value and not summary.get("Vehicle_Category"):
            summary["Vehicle_Category"] = category_value
        if category_value:
            category_metadata = category_metadata or {}
            label = VEHICLE_CATEGORY_LABELS.get(category_value, "")
            source_label = str(category_metadata.get("source_category_label") or label)
            source_url = str(category_metadata.get("source_category_url") or "")
            summary.setdefault("Vehicle_Category_Label", source_label)
            summary.setdefault("Vehicle_Category_URL", source_url)
            summary.setdefault("source_category", category_value)
            summary.setdefault("source_category_label", source_label)
            if category_metadata.get("source_category_count") is not None:
                summary.setdefault("source_category_count", str(category_metadata["source_category_count"]))
            summary.setdefault("source_category_url", source_url)
            if label and VehicleScraper._should_replace_vehicle_type(summary.get("Fahrzeugtyp", "")):
                summary["Fahrzeugtyp"] = label

    @staticmethod
    def _should_replace_vehicle_type(value: str) -> bool:
        text = clean_text(value)
        if not text:
            return True
        lowered = text.lower()
        condition_or_stat = {
            "unfallfrei",
            "gebrauchtfahrzeug",
            "neufahrzeug",
            "neuwagen",
            "vorführfahrzeug",
            "tageszulassung",
            "beschädigt",
            "fahrtauglich",
            "nicht fahrtauglich",
            "stake body",
            "box",
            "panel van",
        }
        return lowered in condition_or_stat or bool(
            re.search(r"\b(?:EZ\s*)?\d{2}/\d{4}\b|\b\d[\d. ]*\s*km\b|\b\d{1,4}\s*kW\b", text, re.I)
        )

    async def _legacy_collect_vehicle_urls(self, dealer_url: str) -> list[str]:
        all_urls: list[str] = []
        seen: set[str] = set()
        page = self.browser.page

        logger.debug("Collecting vehicle URLs from: %s", dealer_url)

        page_index = 0
        while True:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.debug("Vehicle list network idle wait timed out.")
            await self._settle_listing_page()

            html = await page.content()
            self.listing_summaries.update(parse_vehicle_listing_summaries(html))
            page_urls = [normalize_vehicle_url(url) for url in parse_vehicle_listing_urls(html)]
            page_urls.extend(await self._extract_vehicle_urls_from_dom())
            dom_summaries = await self._extract_listing_summaries_from_dom()
            for summary_index, summary in enumerate(dom_summaries):
                summary_url = normalize_vehicle_url(summary.get("Vehicle_URL", ""))
                if not summary_url and summary_index < len(page_urls):
                    summary_url = page_urls[summary_index]
                    summary["Vehicle_URL"] = summary_url
                if summary_url:
                    self.listing_summaries[summary_url] = summary

            for normalized in page_urls:
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    all_urls.append(normalized)

            if self.config.max_cars_per_vendor > 0 and len(all_urls) >= self.config.max_cars_per_vendor:
                all_urls = all_urls[: self.config.max_cars_per_vendor]
                break

            if not await self._go_to_next_listing_page(page):
                break

            page_index += 1
            if page_index > 1000:
                logger.warning("Stopping listing pagination after 1000 pages for %s", dealer_url)
                break
            await self.browser.polite_delay()

        logger.info("Found %d vehicle URLs for dealer.", len(all_urls))
        return all_urls

    @staticmethod
    def _synthetic_vehicle_url(
        dealer_url: str,
        page_index: int,
        summary_index: int,
        summary: dict[str, str],
        category_value: str | None = None,
    ) -> str:
        title = " ".join(
            part for part in [summary.get("Markes", ""), summary.get("Models", "")] if part
        ).strip()
        slug = quote(re.sub(r"[^A-Za-z0-9ÄÖÜäöüß-]+", "-", title).strip("-")[:80])
        category = f"{category_value}-" if category_value else ""
        return f"{dealer_url.rstrip('/')}#listing-{category}{page_index + 1}-{summary_index + 1}-{slug}"

    async def _settle_listing_page(self) -> None:
        """Give lazy-loaded dealer listing cards a chance to render."""
        page = self.browser.page
        try:
            await page.wait_for_timeout(1000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1200)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)
        except Exception as e:
            logger.debug("Listing page settle failed: %s", e)

    async def _extract_vehicle_urls_from_dom(self) -> list[str]:
        """Extract vehicle detail anchors directly from the rendered DOM."""
        try:
            urls = await self.browser.page.evaluate(
                """
                () => Array.from(document.querySelectorAll('a[href]'))
                  .map((a) => a.href || a.getAttribute('href') || '')
                  .filter((href) => href.includes('/fahrzeuge/details') || href.includes('/auto-inserat/'))
                """
            )
        except Exception as e:
            logger.debug("DOM vehicle URL extraction failed: %s", e)
            return []
        return [normalize_vehicle_url(url) for url in urls if url]

    async def _extract_listing_summaries_from_dom(
        self,
        category_value: str | None = None,
    ) -> list[dict[str, str]]:
        """Read visible listing card data from the rendered dealer inventory DOM."""
        try:
            rows = await self.browser.page.evaluate(
                """
                () => Array.from(document.querySelectorAll('[data-testid^="listing-"][data-testid$="-title"]'))
                  .map((titleEl) => {
                    const testId = titleEl.getAttribute('data-testid') || '';
                    const match = testId.match(/^listing-(\\d+)-title$/);
                    const n = match ? match[1] : '';
                    const root = titleEl.closest('article')
                      || titleEl.closest('a')
                      || titleEl.closest('[class*="listingCard"]')
                      || titleEl.parentElement;
                    const link = (root && root.querySelector('a[href*="/fahrzeuge/details"], a[href*="/auto-inserat/"]'))
                      || titleEl.closest('a');
                    const price = root && (
                      root.querySelector(`[data-testid="listing-${n}-price-section"]`)
                      || root.querySelector('[data-testid="price-label"]')
                      || root.querySelector('[data-testid="main-price-label"]')
                      || root.querySelector('[class*="price"]')
                    );
                    const details = root && (
                      root.querySelector('[data-testid="listing-details-attributes"]')
                      || root.querySelector('[data-testid="listing-details"]')
                    );
                    return {
                      url: link ? link.href : '',
                      title: titleEl.innerText || '',
                      price: price ? price.innerText : '',
                      details: details ? details.innerText : ''
                    };
                  })
                """
            )
        except Exception as e:
            logger.debug("DOM listing summary extraction failed: %s", e)
            return []

        summaries: list[dict[str, str]] = []
        category_metadata = self.category_metadata.get(category_value or "", {})
        for row in rows or []:
            title = clean_text(row.get("title", ""))
            brand, model = split_vehicle_title(title)
            details = clean_text(row.get("details", ""))
            attr_fields = extract_listing_attribute_fields(details)
            summary = {
                "Vehicle_URL": normalize_vehicle_url(row.get("url", "")),
                "Markes": brand,
                "Models": model,
                "Preis": clean_text(row.get("price", "")).splitlines()[0] if row.get("price") else "",
                "Kilometerstand": self._match_text(details, r"\b\d[\d. ]*\s*km\b"),
                "Erstzulassung": self._match_text(details, r"\b(?:EZ\s*)?\d{2}/\d{4}\b").replace("EZ ", ""),
                "Leistung": self._match_text(details, r"\b\d{1,4}\s*kW\s*\(\s*\d{1,4}\s*PS\s*\)|\b\d{1,4}\s*kW\b"),
                "Kraftstoffart": self._match_text(details, r"\b(?:Benzin|Diesel|Elektro|Hybrid|Erdgas|Autogas|Wasserstoff)\b"),
                "Getriebe": self._match_text(details, r"\b(?:Automatik|Schaltgetriebe|Halbautomatik)\b"),
                **attr_fields,
            }
            self._apply_category_fallback(summary, category_value, category_metadata)
            summaries.append({key: value for key, value in summary.items() if value})
        return summaries

    @staticmethod
    def _match_text(text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.I)
        return clean_text(match.group(0)) if match else ""

    async def _go_to_next_listing_page(self, page) -> bool:
        """Click a usable next-page control if present."""
        selectors = [
            "a[aria-label*='Nächste']",
            "button[aria-label*='Nächste']",
            "[data-testid='pagination-next']",
            "a:has-text('Nächste')",
            "button:has-text('Nächste')",
            "a:has-text('Weiter')",
            "button:has-text('Weiter')",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count == 0:
                    continue
                candidate = locator.first
                aria_disabled = await candidate.get_attribute("aria-disabled")
                disabled = await candidate.get_attribute("disabled")
                if aria_disabled == "true" or disabled is not None:
                    continue
                previous_url = page.url
                await candidate.click(timeout=8000)
                await page.wait_for_timeout(1500)
                if page.url != previous_url or await page.locator("[data-testid*='listing']").count() > 0:
                    return True
            except Exception as e:
                logger.debug("Next pagination selector failed (%s): %s", selector, e)
        return False

    def _extract_listing_urls_from_html(self, html: str, base_url: str) -> list[str]:
        """Extract vehicle listing URLs from page HTML."""
        return parse_vehicle_listing_urls(html)

    def _is_vehicle_url(self, url: str) -> bool:
        """Check if a URL points to a vehicle detail page."""
        indicators = [
            "/auto-inserat/",
            "/fahrzeuge/details",
            "suchen.mobile.de",
            "id=",
        ]
        return any(ind in url for ind in indicators)

    def _normalize_url(self, url: str) -> str:
        """Normalize a URL to absolute form."""
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("/"):
            return f"https://suchen.mobile.de{url}"
        if not url.startswith("http"):
            return f"https://{url}"
        return url

    async def scrape_vehicle(
        self,
        vehicle_url: str,
        vendor_info: dict[str, str],
        fallback: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Scrape a single vehicle's detail page.

        Args:
            vehicle_url: URL of the vehicle detail page.
            vendor_info: Dict with Händler ID, Händlername, PLZ.

        Returns:
            Dict with all vehicle fields.
        """
        vehicle: dict[str, Any] = {
            "Händler ID": vendor_info.get("Händler ID", ""),
            "Händlername": vendor_info.get("Händlername", ""),
            "PLZ": vendor_info.get("PLZ", ""),
            "Markes": "",
            "Models": "",
            "Fahrzeugtyp": "",
            "Fahrzeugzustand": "",
            "Erstzulassung": "",
            "Kilometerstand": "",
            "Kraftstoffart": "",
            "CO₂-Emissionen": "",
            "Preis": "",
            "Leistung": "",
            "Anzahl Sitzplätze": "",
            "Getriebe": "",
            "Schadstoffklasse": "",
            "Farbe": "",
            "Baureihe": "",
            "Ausstattungslinie": "",
            "Hubraum": "",
            "Anzahl der Türen": "",
            "Anzahl der Fahrzeughalter": "",
            "Financing": "",
            "Finanzierung": "",
            "Bank": "",
            "Darlehensvermittler": "",
            "Fahrzeugpreis": "",
            "Anzahlung": "",
            "Jährliche Kilometerleistung": "",
            "Schlussrate": "",
            "Fester Sollzins p.a.": "",
            "Effektiver Jahreszins": "",
            "Gesamtzins": "",
            "Gesamtbetrag": "",
            "Laufzeit": "",
            "Vehicle_URL": vehicle_url,
            "source_vehicle_url": vehicle_url,
            "fetch_strategy": "",
            "fetch_status": "",
            "parse_status": "partial",
            "vehicle_data_source": "detail_page",
        }
        if fallback:
            self._apply_fallback(vehicle, fallback)

        logger.debug("Scraping vehicle: %s", vehicle_url)

        if self.config.detail_open_strategy == "listing-only":
            vehicle["fetch_strategy"] = "listing_payload"
            vehicle["vehicle_data_source"] = "listing_fallback"
            vehicle["detail_strategy_used"] = "listing-only"
            vehicle["detail_status"] = "listing_only"
            return vehicle

        if self.config.detail_open_strategy == "uc-popup":
            uc_started = time.perf_counter()
            uc_result = await asyncio.to_thread(
                self.uc_popup_fetcher.fetch,
                vehicle_url,
                fallback=fallback or {},
            )
            self._increment_config_counter(
                "uc_popup_total_seconds",
                time.perf_counter() - uc_started,
            )
            fetch_result = uc_result.fetch_result
        else:
            fetch_result = await self.fetch_manager.fetch(
                vehicle_url,
                validator=self._validate_vehicle_static,
                playwright_max_retries=getattr(self.config, "detail_max_retries", 1),
            )
        if not fetch_result.ok:
            logger.warning("Failed to load vehicle page: %s", vehicle_url)
            vehicle["fetch_strategy"] = fetch_result.strategy
            vehicle["fetch_status"] = fetch_result.status_code or ""
            vehicle["fetch_fallback_reason"] = fetch_result.fallback_reason
            vehicle["detail_strategy_used"] = self.config.detail_open_strategy
            vehicle["detail_status"] = fetch_result.detail_status or fetch_result.classification or "fetch_failed"
            vehicle["detail_failure_reason"] = (
                fetch_result.failure_reason
                or fetch_result.error_message
                or fetch_result.error_type
                or "fetch_failed"
            )
            vehicle["detail_artifact_html_path"] = fetch_result.html_dump_path
            vehicle["detail_artifact_screenshot_path"] = fetch_result.screenshot_path
            vehicle["parse_status"] = fetch_result.error_message or "fetch_failed"
            vehicle["vehicle_data_source"] = "listing_fallback"
            return vehicle

        vehicle["fetch_strategy"] = fetch_result.strategy
        vehicle["fetch_status"] = fetch_result.status_code or ""
        vehicle["fetch_fallback_reason"] = fetch_result.fallback_reason
        vehicle["parse_status"] = "ok"
        vehicle["detail_strategy_used"] = self.config.detail_open_strategy
        vehicle["detail_status"] = fetch_result.detail_status or fetch_result.classification or "real_detail_page"
        vehicle["detail_artifact_html_path"] = fetch_result.html_dump_path
        vehicle["detail_artifact_screenshot_path"] = fetch_result.screenshot_path
        vehicle["vehicle_data_source"] = (
            "detail_page_uc_popup"
            if fetch_result.strategy == "uc-popup"
            else "detail_page"
            if fetch_result.strategy.startswith("playwright")
            else "static_html"
        )

        if fetch_result.strategy.startswith("playwright"):
            await asyncio.sleep(1.5)
            # Try to click "Mehr anzeigen" to expand all technical data
            await self._expand_tech_data()
            html = await self.browser.get_page_html()
        else:
            html = fetch_result.html

        detail_fields = parse_vehicle_detail_fields(html)
        detail_filled_fields = self._merge_detail_fields(vehicle, detail_fields, fetch_result.strategy)
        target_extracted_count = sum(
            1 for field in DETAIL_TARGET_FIELDS if clean_text(detail_fields.get(field, ""))
        )
        if target_extracted_count:
            self._increment_config_counter("detail_target_fields_extracted_count", target_extracted_count)
        elif vehicle.get("detail_status") == "real_detail_page":
            self._increment_config_counter("detail_real_page_but_no_target_fields_count")
        vehicle["detail_target_fields_extracted_count"] = target_extracted_count
        vehicle["detail_fields_filled"] = ", ".join(detail_filled_fields)
        vehicle["detail_data_source"] = fetch_result.strategy

        # 4. Parse inline quick-stats if we missed them from specs
        if fetch_result.strategy.startswith("playwright"):
            await self._extract_inline_stats(vehicle)
        if vehicle.get("Financing") and not vehicle.get("Finanzierung"):
            vehicle["Finanzierung"] = vehicle["Financing"]

        logger.debug("Vehicle scraped: %s %s | %s", vehicle["Markes"],
                      vehicle["Models"], vehicle["Preis"])
        return vehicle

    @staticmethod
    def _apply_fallback(vehicle: dict[str, Any], fallback: dict[str, str]) -> None:
        for key, value in fallback.items():
            if value and not vehicle.get(key):
                vehicle[key] = value

    def _merge_detail_fields(
        self,
        vehicle: dict[str, Any],
        detail_fields: dict[str, str],
        source: str,
    ) -> list[str]:
        filled: list[str] = []
        conflicts: dict[str, dict[str, str]] = {}
        for key, value in detail_fields.items():
            if not value or key not in vehicle:
                continue
            if not vehicle.get(key):
                vehicle[key] = value
                filled.append(key)
                vehicle[f"{key}_source"] = source
                continue
            if clean_text(vehicle.get(key, "")) != clean_text(value):
                conflicts[key] = {"listing": clean_text(vehicle.get(key, "")), "detail": clean_text(value)}
        if conflicts:
            vehicle["detail_conflicts_json"] = str(conflicts)
        if source == "uc-popup" and filled:
            self._increment_config_counter("fields_added_by_uc_popup_count", len(filled))
        return filled

    def _increment_config_counter(self, name: str, amount: int | float = 1) -> None:
        current = getattr(self.config, name, 0) or 0
        if isinstance(amount, float) or isinstance(current, float):
            setattr(self.config, name, float(current) + float(amount))
        else:
            setattr(self.config, name, int(current) + int(amount))

    async def _expand_tech_data(self) -> None:
        """Click 'Mehr anzeigen' to expand the full technical data table."""
        page = self.browser.page
        try:
            more_btn = page.locator(
                "button:has-text('Mehr anzeigen'), a:has-text('Mehr anzeigen'), "
                "button:has-text('Alle technischen Daten')"
            )
            for index in range(min(await more_btn.count(), 3)):
                try:
                    await more_btn.nth(index).click(timeout=5000)
                    await asyncio.sleep(0.8)
                    logger.debug("Expanded technical data control %d.", index + 1)
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Could not expand tech data: %s", e)

    async def _extract_inline_stats(self, vehicle: dict[str, Any]) -> None:
        """
        Extract inline quick-stats visible at the top of the vehicle page.

        These show: Kilometerstand, Leistung, Kraftstoffart, Getriebe,
        Erstzulassung, Fahrzeughalter as icon+text pairs.
        """
        page = self.browser.page
        try:
            # Get the entire page text for pattern matching
            body_text = clean_text(await page.inner_text("body"))

            # Try to extract from quick-stat patterns
            patterns = [
                (r"(\d[\d.]*)\s*km", "Kilometerstand"),
                (r"(\d+)\s*kW\s*\((\d+)\s*PS\)", "Leistung"),
                (r"EZ\s*(\d{2}/\d{4})", "Erstzulassung"),
            ]

            for pattern, field in patterns:
                if not vehicle.get(field):
                    m = re.search(pattern, body_text)
                    if m:
                        vehicle[field] = m.group(0)

        except Exception as e:
            logger.debug("Inline stats extraction: %s", e)

    @staticmethod
    def _validate_vehicle_static(result: FetchResult) -> StaticValidation:
        html = result.html
        brand, model = parse_vehicle_title(html)
        price = parse_vehicle_price(html)
        specs = parse_vehicle_specs(html)
        if not (brand or model):
            return StaticValidation(False, "missing_vehicle_title_in_static_html")
        if not (price or specs):
            return StaticValidation(False, "missing_vehicle_fields_in_static_html")
        return StaticValidation(True)
