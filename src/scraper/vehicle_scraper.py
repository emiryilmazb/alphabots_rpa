"""
Vehicle detail page scraper.

Navigates to each vehicle listing and extracts all required fields
from the detail page, including technical specs and financing info.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from src.config import ScraperConfig
from src.scraper.browser import BrowserManager
from src.scraper.parsers import (
    clean_text,
    normalize_vehicle_url,
    parse_vehicle_title,
    parse_vehicle_price,
    parse_vehicle_specs,
    parse_financing_data,
    parse_vehicle_listing_urls,
    parse_vehicle_listing_summaries,
    parse_vehicle_category_values,
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
        self.listing_summaries: dict[str, dict[str, str]] = {}

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
        category_values = await self._category_sequence_from_current_page()
        if not category_values:
            category_values = [None]

        visited_categories = 0
        for category_value in category_values:
            if category_value:
                category_url = self._dealer_category_url(dealer_url, category_value)
                if not await self.browser.safe_goto(category_url):
                    logger.debug(
                        "Skipping vehicle category %s for %s: %s",
                        category_value,
                        dealer_url,
                        self.browser.last_error,
                    )
                    continue

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
            if self.config.max_cars_per_vendor > 0 and len(entries_by_key) >= self.config.max_cars_per_vendor:
                break
            await self.browser.polite_delay()

        entries = list(entries_by_key.values())
        logger.info(
            "Found %d vehicle listing cards for dealer across %d populated categories.",
            len(entries),
            visited_categories,
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
                self._apply_category_fallback(summary, category_value)
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
                self._apply_category_fallback(summary, category_value)
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
                self._apply_category_fallback(summary, category_value)
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
        if not self.config.traverse_vehicle_categories:
            return [None]

        try:
            html = await self.browser.page.content()
        except Exception:
            html = ""
        discovered = parse_vehicle_category_values(html)
        if not discovered:
            return [None, *DEFAULT_VEHICLE_CATEGORY_VALUES]
        sequence: list[str | None] = []
        for value in [*discovered, *DEFAULT_VEHICLE_CATEGORY_VALUES]:
            if value not in sequence:
                sequence.append(value)
        return sequence

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
    def _apply_category_fallback(summary: dict[str, str], category_value: str | None) -> None:
        if category_value and not summary.get("Vehicle_Category"):
            summary["Vehicle_Category"] = category_value
        if category_value:
            label = VEHICLE_CATEGORY_LABELS.get(category_value, "")
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
            self._apply_category_fallback(summary, category_value)
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
        }
        if fallback:
            self._apply_fallback(vehicle, fallback)

        logger.debug("Scraping vehicle: %s", vehicle_url)

        success = await self.browser.safe_goto(vehicle_url)
        if not success:
            logger.warning("Failed to load vehicle page: %s", vehicle_url)
            return vehicle

        await asyncio.sleep(1.5)

        # Try to click "Mehr anzeigen" to expand all technical data
        await self._expand_tech_data()

        html = await self.browser.get_page_html()

        # 1. Parse title → Brand + Model
        brand, model = parse_vehicle_title(html)
        vehicle["Markes"] = brand
        vehicle["Models"] = model

        # 2. Parse price
        vehicle["Preis"] = parse_vehicle_price(html)

        # 3. Parse technical specifications
        specs = parse_vehicle_specs(html)
        spec_mapping = {
            "Fahrzeugzustand": "Fahrzeugzustand",
            "Kategorie": "Fahrzeugtyp",
            "Kilometerstand": "Kilometerstand",
            "Kraftstoffart": "Kraftstoffart",
            "CO₂-Emissionen": "CO₂-Emissionen",
            "Leistung": "Leistung",
            "Anzahl Sitzplätze": "Anzahl Sitzplätze",
            "Getriebe": "Getriebe",
            "Schadstoffklasse": "Schadstoffklasse",
            "Farbe": "Farbe",
            "Baureihe": "Baureihe",
            "Ausstattungslinie": "Ausstattungslinie",
            "Hubraum": "Hubraum",
            "Anzahl der Türen": "Anzahl der Türen",
            "Anzahl der Fahrzeughalter": "Anzahl der Fahrzeughalter",
            "Erstzulassung": "Erstzulassung",
        }

        for spec_key, vehicle_key in spec_mapping.items():
            if spec_key in specs and not vehicle[vehicle_key]:
                vehicle[vehicle_key] = specs[spec_key]

        # 4. Parse inline quick-stats if we missed them from specs
        await self._extract_inline_stats(vehicle)

        # 5. Parse financing data
        financing = parse_financing_data(html)
        finance_mapping = {
            "Financing": "Financing",
            "Bank": "Bank",
            "Darlehensvermittler": "Darlehensvermittler",
            "Fahrzeugpreis": "Fahrzeugpreis",
            "Anzahlung": "Anzahlung",
            "Jährliche Kilometerleistung": "Jährliche Kilometerleistung",
            "Schlussrate": "Schlussrate",
            "Fester Sollzins p.a.": "Fester Sollzins p.a.",
            "Effektiver Jahreszins": "Effektiver Jahreszins",
            "Gesamtzins": "Gesamtzins",
            "Gesamtbetrag": "Gesamtbetrag",
            "Laufzeit": "Laufzeit",
        }
        for fin_key, vehicle_key in finance_mapping.items():
            if fin_key in financing:
                vehicle[vehicle_key] = financing[fin_key]

        logger.debug("Vehicle scraped: %s %s | %s", vehicle["Markes"],
                      vehicle["Models"], vehicle["Preis"])
        return vehicle

    @staticmethod
    def _apply_fallback(vehicle: dict[str, Any], fallback: dict[str, str]) -> None:
        for key, value in fallback.items():
            if value and not vehicle.get(key):
                vehicle[key] = value

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
