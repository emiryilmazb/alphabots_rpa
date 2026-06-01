"""
Vendor / dealer page scraper.

Extracts detailed vendor information from each dealer's home page,
including contact details from the "Über uns" modal and Impressum.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from src.config import ScraperConfig
from src.scraper.browser import BrowserManager
from src.scraper.fetchers import FetchResult, FetchStrategyManager, StaticValidation
from src.scraper.parsers import (
    clean_text,
    parse_vendor_json_ld,
    parse_vendor_next_data,
    parse_vendor_vehicle_count,
)

logger = logging.getLogger("mobile_de.vendor")


GERMAN_POSTCODE_STATE_RANGES: tuple[tuple[range, str], ...] = (
    (range(1000, 1999 + 1), "Sachsen"),
    (range(2000, 2999 + 1), "Brandenburg"),
    (range(3000, 4999 + 1), "Brandenburg"),
    (range(6000, 6999 + 1), "Sachsen-Anhalt"),
    (range(7000, 7999 + 1), "Thüringen"),
    (range(8000, 9999 + 1), "Sachsen"),
    (range(10000, 10999 + 1), "Berlin"),
    (range(11000, 13999 + 1), "Berlin"),
    (range(14000, 14999 + 1), "Brandenburg"),
    (range(15000, 19999 + 1), "Brandenburg"),
    (range(20000, 22999 + 1), "Hamburg"),
    (range(23000, 23999 + 1), "Schleswig-Holstein"),
    (range(24000, 25999 + 1), "Schleswig-Holstein"),
    (range(26000, 26999 + 1), "Niedersachsen"),
    (range(27000, 28999 + 1), "Niedersachsen"),
    (range(29000, 29999 + 1), "Niedersachsen"),
    (range(30000, 31999 + 1), "Niedersachsen"),
    (range(32000, 32999 + 1), "Nordrhein-Westfalen"),
    (range(33000, 33999 + 1), "Nordrhein-Westfalen"),
    (range(34000, 34999 + 1), "Hessen"),
    (range(35000, 36999 + 1), "Hessen"),
    (range(37000, 37999 + 1), "Niedersachsen"),
    (range(38000, 38999 + 1), "Niedersachsen"),
    (range(39000, 39999 + 1), "Sachsen-Anhalt"),
    (range(40000, 42999 + 1), "Nordrhein-Westfalen"),
    (range(44000, 48999 + 1), "Nordrhein-Westfalen"),
    (range(49000, 49999 + 1), "Niedersachsen"),
    (range(50000, 53999 + 1), "Nordrhein-Westfalen"),
    (range(54000, 54999 + 1), "Rheinland-Pfalz"),
    (range(55000, 55999 + 1), "Rheinland-Pfalz"),
    (range(56000, 56999 + 1), "Rheinland-Pfalz"),
    (range(57000, 59999 + 1), "Nordrhein-Westfalen"),
    (range(60000, 65999 + 1), "Hessen"),
    (range(66000, 66999 + 1), "Saarland"),
    (range(67000, 67999 + 1), "Rheinland-Pfalz"),
    (range(68000, 69999 + 1), "Baden-Württemberg"),
    (range(70000, 79999 + 1), "Baden-Württemberg"),
    (range(80000, 87999 + 1), "Bayern"),
    (range(88000, 89999 + 1), "Baden-Württemberg"),
    (range(90000, 99999 + 1), "Bayern"),
)
GERMAN_STATE_NAMES = {state for _, state in GERMAN_POSTCODE_STATE_RANGES}


class VendorScraper:
    """Extracts detailed information from a dealer's mobile.de page."""

    def __init__(self, browser: BrowserManager, config: ScraperConfig):
        self.browser = browser
        self.config = config
        self.fetch_manager = FetchStrategyManager(config, browser)

    async def scrape_vendor(
        self, dealer_entry: dict[str, str], bundesland: str
    ) -> dict[str, Any]:
        """
        Scrape a single vendor's detailed information.

        Args:
            dealer_entry: Dict with keys name, url, street, plz, city
            bundesland: The German state name

        Returns:
            Dict with all vendor fields.
        """
        url = dealer_entry["url"]
        logger.info("Scraping vendor: %s (%s)", dealer_entry["name"], url)

        vendor: dict[str, Any] = {
            "Händlername": dealer_entry.get("name", ""),
            "Standort": dealer_entry.get("street", ""),
            "PLZ": dealer_entry.get("plz", ""),
            "Städte": dealer_entry.get("city", ""),
            "Bundesland": _actual_region_for_vendor(
                dealer_entry.get("country", ""),
                dealer_entry.get("plz", ""),
                dealer_entry.get("region", ""),
            ),
            "Land": _normalize_country_name(dealer_entry.get("country", "")),
            "Telephone Number": "",
            "2. Telephone Number": "",
            "MobilTelefon": "",
            "Fax Number": "",
            "Email ID": "",
            "Hauptseite": "",
            "Mobile.de_Links": url,
            "Anzahl der Fahrzeuge": None,
            "search_state": bundesland,
        }

        fetch_result = await self.fetch_manager.fetch(
            url, validator=self._validate_vendor_static
        )
        if not fetch_result.ok:
            logger.warning("Failed to load vendor page: %s", url)
            _finalize_location_fields(vendor)
            return vendor

        vendor["fetch_strategy"] = fetch_result.strategy
        vendor["fetch_status"] = fetch_result.status_code or ""
        self._apply_vendor_html(fetch_result.html, vendor)

        if fetch_result.strategy == "curl_cffi":
            return vendor

        await asyncio.sleep(1.5)

        # 3. Open "Über uns" / contact modal for details not in payloads.
        await self._extract_ueber_uns(vendor)
        _finalize_location_fields(vendor)

        return vendor

    @staticmethod
    def _apply_vendor_html(html: str, vendor: dict[str, Any]) -> None:
        # Extract structured Next.js payload data. On current mobile.de dealer
        # pages this is the most complete static source for legal data, phone
        # numbers, external homepage, and customer id.
        next_data = parse_vendor_next_data(html)
        if next_data:
            vendor["Händlername"] = next_data.get("name") or vendor["Händlername"]
            vendor["Standort"] = next_data.get("street") or vendor["Standort"]
            vendor["PLZ"] = next_data.get("plz") or vendor["PLZ"]
            vendor["Städte"] = next_data.get("city") or vendor["Städte"]
            vendor["Land"] = next_data.get("country") or vendor["Land"]
            vendor["Bundesland"] = next_data.get("region") or vendor["Bundesland"]
            vendor["Telephone Number"] = (
                next_data.get("Telephone Number") or vendor["Telephone Number"]
            )
            vendor["2. Telephone Number"] = (
                next_data.get("2. Telephone Number") or vendor["2. Telephone Number"]
            )
            vendor["MobilTelefon"] = (
                next_data.get("MobilTelefon") or vendor["MobilTelefon"]
            )
            vendor["Fax Number"] = next_data.get("Fax Number") or vendor["Fax Number"]
            vendor["Email ID"] = next_data.get("email") or vendor["Email ID"]
            vendor["Hauptseite"] = next_data.get("homepage") or vendor["Hauptseite"]
            vendor["Mobile.de_Links"] = (
                next_data.get("url") or vendor["Mobile.de_Links"]
            )

        json_ld = parse_vendor_json_ld(html)
        if json_ld:
            vendor["Händlername"] = json_ld.get("name") or vendor["Händlername"]
            vendor["Standort"] = json_ld.get("street") or vendor["Standort"]
            vendor["PLZ"] = json_ld.get("plz") or vendor["PLZ"]
            vendor["Städte"] = json_ld.get("city") or vendor["Städte"]
            vendor["Bundesland"] = json_ld.get("region") or vendor["Bundesland"]
            vendor["Land"] = json_ld.get("country") or vendor["Land"]
            if json_ld.get("telephone"):
                vendor["Telephone Number"] = _format_phone(json_ld["telephone"])
            if json_ld.get("email"):
                vendor["Email ID"] = json_ld["email"]

        vcount = parse_vendor_vehicle_count(html)
        if vcount is not None:
            vendor["Anzahl der Fahrzeuge"] = vcount
        _finalize_location_fields(vendor)

    @staticmethod
    def _validate_vendor_static(result: FetchResult) -> StaticValidation:
        vendor = {
            "Händlername": "",
            "Standort": "",
            "PLZ": "",
            "Städte": "",
            "Bundesland": "",
            "Land": "Deutschland",
            "Telephone Number": "",
            "2. Telephone Number": "",
            "MobilTelefon": "",
            "Fax Number": "",
            "Email ID": "",
            "Hauptseite": "",
            "Mobile.de_Links": result.url,
            "Anzahl der Fahrzeuge": None,
        }
        VendorScraper._apply_vendor_html(result.html, vendor)
        has_identity = bool(vendor["Händlername"] and vendor["Mobile.de_Links"])
        has_location = bool(vendor["PLZ"] or vendor["Städte"])
        has_contact_or_count = bool(
            vendor["Telephone Number"]
            or vendor["Email ID"]
            or vendor["Hauptseite"]
            or vendor["Anzahl der Fahrzeuge"] is not None
        )
        if not (has_identity and has_location and has_contact_or_count):
            return StaticValidation(False, "missing_vendor_fields_in_static_html")
        return StaticValidation(True)

    async def _extract_ueber_uns(self, vendor: dict[str, Any]) -> None:
        """
        Click the 'Über uns' button and extract contact info from the modal.

        The modal contains:
        - Adresse: street, PLZ city
        - Kontakt: Tel, Tel 2, Mobil, Fax (initially hidden)
        - Internet: homepage URL
        - "Einblenden" button to reveal full phone numbers
        - "Impressum & Rechtliches" expandable section
        """
        page = self.browser.page

        try:
            # Click "Über uns" button
            ueber_uns_btn = page.locator(
                "button:has-text('Über uns'), a:has-text('Über uns'), "
                "button:has-text('Kontakt'), a:has-text('Kontakt'), "
                "button:has-text('Impressum'), a:has-text('Impressum')"
            )
            if await ueber_uns_btn.count() == 0:
                logger.debug("No 'Über uns' button found.")
                return

            await ueber_uns_btn.first.click()
            await asyncio.sleep(2)

            # Try to reveal phone numbers by clicking reveal controls.
            await self._reveal_phone_numbers()

            # Extract contact info from the modal
            modal_html = await page.content()
            self._parse_modal_contacts(modal_html, vendor)

            # Try to expand Impressum & Rechtliches for email
            await self._extract_impressum(vendor)

            # Close the modal
            try:
                close_btn = page.locator(
                    "button:has-text('Schließen'), button[aria-label*='Schließen'], "
                    "button[aria-label*='Close']"
                )
                if await close_btn.count() > 0:
                    await close_btn.first.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        except Exception as e:
            logger.debug("Error extracting Über uns: %s", e)

    async def _reveal_phone_numbers(self) -> None:
        """Click the eye icon to reveal full phone numbers."""
        page = self.browser.page
        try:
            reveal_btn = page.locator(
                "button:has-text('Einblenden'), "
                "button:has-text('Telefonnummer'), "
                "button:has-text('vollständige Telefonnummer'), "
                "button[aria-label*='Telefon'], button[aria-label*='phone']"
            )
            for index in range(min(await reveal_btn.count(), 4)):
                try:
                    await reveal_btn.nth(index).click(timeout=5000)
                    await asyncio.sleep(0.8)
                    logger.debug("Clicked phone reveal control %d.", index + 1)
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Could not reveal phone numbers: %s", e)

    def _parse_modal_contacts(self, html: str, vendor: dict[str, Any]) -> None:
        """Parse contact information from the Über uns modal HTML."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        full_text = clean_text(soup.get_text(" ", strip=True))

        # Extract phone numbers with patterns
        # Tel.: +49 XXXX XXXXXX
        # Tel. 2: +49 XXXX XXXXXX
        # Mobil: +49 XXXX XXXXXX
        # Fax: +49 XXXX XXXXXX

        phone_patterns = [
            (
                r"Tel\.?:\s*([\+\d\s\(\)/-]+?)(?=\s*(?:Tel|Mobil|Fax|Wir|Bei|Internet|$))",
                "Telephone Number",
            ),
            (
                r"Tel\.?\s*2:\s*([\+\d\s\(\)/-]+?)(?=\s*(?:Mobil|Fax|Wir|Bei|Internet|$))",
                "2. Telephone Number",
            ),
            (
                r"Mobil\.?:\s*([\+\d\s\(\)/-]+?)(?=\s*(?:Fax|Wir|Bei|Internet|$))",
                "MobilTelefon",
            ),
            (
                r"Fax\.?:\s*([\+\d\s\(\)/-]+?)(?=\s*(?:Wir|Bei|Internet|Impressum|$))",
                "Fax Number",
            ),
        ]

        for pattern, field in phone_patterns:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                phone = m.group(1).strip()
                phone = re.sub(r"\s+", " ", phone)
                if len(phone) > 5:  # Basic validation
                    vendor[field] = vendor.get(field) or phone

        # Extract homepage URL
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)
            if href.startswith("http") and "mobile.de" not in href and len(href) > 10:
                vendor["Hauptseite"] = vendor.get("Hauptseite") or href
                break
            # Also check for "Internet" label
            if "www." in text or "http" in text:
                vendor["Hauptseite"] = vendor.get("Hauptseite") or (
                    text if text.startswith("http") else f"https://{text}"
                )

        # Extract address if we don't have it yet
        if not vendor["Standort"]:
            # Look for "Adresse" section
            m = re.search(r"Adresse\s+(.*?)(?=\s*DE-|\s*Kontakt)", full_text)
            if m:
                addr_text = m.group(1).strip()
                vendor["Standort"] = clean_text(addr_text)

        # Extract PLZ and city from "DE-XXXXX City" pattern
        m = re.search(
            r"DE-(\d{5})\s+(\w[\w\s]*?)(?=\s*(?:Kontakt|Wir|Bei|$))", full_text
        )
        if m:
            vendor["Land"] = vendor.get("Land") or "Deutschland"
            if not vendor["PLZ"]:
                vendor["PLZ"] = m.group(1)
            if not vendor["Städte"]:
                vendor["Städte"] = clean_text(m.group(2))

    async def _extract_impressum(self, vendor: dict[str, Any]) -> None:
        """Expand Impressum & Rechtliches section for email."""
        page = self.browser.page
        try:
            impressum_btn = page.locator(
                "text=Impressum & Rechtliches, text=Impressum, text=Rechtliches"
            )
            if await impressum_btn.count() > 0:
                await impressum_btn.first.click()
                await asyncio.sleep(1.5)

                # Look for email in the expanded section
                html = await page.content()
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "lxml")

                # Email pattern
                for elem in soup.find_all("a", href=True):
                    href = elem["href"]
                    if href.startswith("mailto:"):
                        email = href.replace("mailto:", "").strip()
                        if email and "@" in email:
                            vendor["Email ID"] = email
                            break

                # Also check for email text pattern
                if not vendor["Email ID"]:
                    email_pattern = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}")
                    full_text = soup.get_text()
                    m = email_pattern.search(full_text)
                    if m:
                        vendor["Email ID"] = m.group(0)

        except Exception as e:
            logger.debug("Could not extract Impressum: %s", e)


def _normalize_country_name(country: Any) -> str:
    text = clean_text(country)
    normalized = text.upper()
    if normalized in {"DE", "DEU", "GERMANY", "DEUTSCHLAND"}:
        return "Deutschland"
    if normalized in {"IT", "ITA", "ITALY", "ITALIA", "ITALIEN"}:
        return "Italien"
    if normalized in {"FR", "FRA", "FRANCE", "FRANKREICH"}:
        return "Frankreich"
    if normalized in {"NL", "NLD", "NETHERLANDS", "NIEDERLANDE"}:
        return "Niederlande"
    if normalized in {"BE", "BEL", "BELGIUM", "BELGIEN"}:
        return "Belgien"
    if normalized in {"AT", "AUT", "AUSTRIA", "ÖSTERREICH", "OESTERREICH"}:
        return "Österreich"
    return text


def _actual_region_for_vendor(country: Any, plz: Any, region: Any) -> str:
    country_name = _normalize_country_name(country)
    region_text = clean_text(region)
    if _is_germany(country_name):
        return _german_state_from_postcode(plz) or region_text
    return region_text


def _finalize_location_fields(vendor: dict[str, Any]) -> None:
    country = _normalize_country_name(vendor.get("Land", ""))
    region = clean_text(vendor.get("Bundesland", ""))
    if _is_germany(country):
        vendor["Bundesland"] = (
            _german_state_from_postcode(vendor.get("PLZ", "")) or region
        )
    else:
        vendor["Bundesland"] = "" if region in GERMAN_STATE_NAMES else region
    vendor["Land"] = country


def _is_germany(country: str) -> bool:
    return _normalize_country_name(country) == "Deutschland"


def _german_state_from_postcode(plz: Any) -> str:
    match = re.search(r"\b(\d{5})\b", clean_text(plz))
    if not match:
        return ""
    value = int(match.group(1))
    for postcode_range, state in GERMAN_POSTCODE_STATE_RANGES:
        if value in postcode_range:
            return state
    return ""


def _format_phone(phone: str) -> str:
    """Format a phone number for readability."""
    phone = phone.strip()
    # Add +49 formatting if starts with raw number
    phone = re.sub(r"\s+", " ", phone)
    return phone
