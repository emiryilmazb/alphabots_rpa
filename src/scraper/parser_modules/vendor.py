from __future__ import annotations
import json
import logging
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup, Tag
import json
import re
import logging
from typing import Any, Dict, List, Optional, Iterator, Union
from bs4 import BeautifulSoup, Tag
from src.scraper.parser_modules.normalization import clean_text, normalize_dealer_url, normalize_vehicle_url, dealer_identifier
from src.scraper.parser_modules.common import walk_json, iter_dicts, _none_if_placeholder, extract_next_payloads, _first_present
logger = logging.getLogger(__name__)


def parse_vendor_json_ld(html: str) -> dict[str, Any]:
    """Extract vendor info from JSON-LD structured data."""
    soup = BeautifulSoup(html, "lxml")
    result: dict[str, Any] = {}

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            schema_type = item.get("@type", "")
            if schema_type in ("AutoDealer", "LocalBusiness", "Store", "Organization"):
                result["name"] = _none_if_placeholder(item.get("name"))
                result["telephone"] = _none_if_placeholder(item.get("telephone"))
                result["email"] = _none_if_placeholder(item.get("email"))
                result["url"] = _none_if_placeholder(item.get("url"))
                addr = item.get("address", {})
                if isinstance(addr, dict):
                    result["street"] = _none_if_placeholder(addr.get("streetAddress"))
                    result["plz"] = _none_if_placeholder(addr.get("postalCode"))
                    result["city"] = _none_if_placeholder(addr.get("addressLocality"))
                    result["region"] = _none_if_placeholder(addr.get("addressRegion"))
                    result["country"] = _country_name(_none_if_placeholder(addr.get("addressCountry")))
                return result

    return result

def parse_vendor_next_data(html: str) -> dict[str, Any]:
    """Extract dealerData/dealerHomepageData from mobile.de's Next payloads."""
    result: dict[str, Any] = {}
    for payload in extract_next_payloads(html):
        for obj in iter_dicts(payload):
            if "dealerData" not in obj:
                continue
            dealer = obj.get("dealerData") if isinstance(obj.get("dealerData"), dict) else {}
            homepage = obj.get("dealerHomepageData") if isinstance(obj.get("dealerHomepageData"), dict) else {}
            if not dealer:
                continue

            location = dealer.get("location") if isinstance(dealer.get("location"), dict) else {}
            legal = dealer.get("legalData") if isinstance(dealer.get("legalData"), dict) else {}
            phones = dealer.get("phoneNumbers") if isinstance(dealer.get("phoneNumbers"), dict) else {}

            result.update(
                {
                    "customer_id": _none_if_placeholder(dealer.get("customerId")),
                    "unique_identifier": _none_if_placeholder(dealer.get("uniqueIdentifier")),
                    "name": _none_if_placeholder(dealer.get("name")),
                    "street": _none_if_placeholder(location.get("street")),
                    "plz": _none_if_placeholder(location.get("zipcode")),
                    "city": _none_if_placeholder(location.get("city")),
                    "region": _first_present(
                        location.get("region"),
                        location.get("state"),
                        location.get("federalState"),
                        location.get("addressRegion"),
                    ),
                    "country": _country_name(_none_if_placeholder(location.get("country"))),
                    "email": _none_if_placeholder(dealer.get("email")),
                    "url": normalize_dealer_url(_none_if_placeholder(dealer.get("homepageUrl"))),
                    "homepage": _first_present(
                        dealer.get("externalHomepageUrl"),
                        homepage.get("userDefinedLink"),
                        homepage.get("externalHomepageUrl"),
                    ),
                    "imprint": _none_if_placeholder(legal.get("imprint")),
                }
            )
            phone_values = _extract_phones_from_next(phones)
            result.update(phone_values)
            _apply_imprint_values(result)
            return result
    return result

def _country_name(country: str) -> str:
    normalized = country.upper()
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
    return country or ""

def _extract_phones_from_next(phones: dict[str, Any]) -> dict[str, str]:
    mapping = {
        "phone": "Telephone Number",
        "phone2": "2. Telephone Number",
        "cellPhone": "MobilTelefon",
        "mobile": "MobilTelefon",
        "fax": "Fax Number",
    }
    values: dict[str, str] = {}
    for key, field in mapping.items():
        value = phones.get(key)
        if isinstance(value, dict):
            formatted = _format_phone_dict(value)
        else:
            formatted = _none_if_placeholder(value)
        if formatted:
            values[field] = formatted
    return values

def _format_phone_dict(value: dict[str, Any]) -> str:
    intl = _none_if_placeholder(value.get("internationalPrefix"))
    prefix = _none_if_placeholder(value.get("prefix"))
    number = _none_if_placeholder(value.get("number"))
    normalized = _none_if_placeholder(value.get("normalized"))
    if intl and prefix and number:
        return clean_text(f"+{intl} {prefix} {number}")
    if normalized:
        if normalized.startswith("49"):
            return f"+{normalized}"
        return normalized
    return clean_text(f"{prefix} {number}") if prefix or number else ""

def _apply_imprint_values(result: dict[str, Any]) -> None:
    imprint = result.get("imprint", "")
    if not imprint:
        return
    if not result.get("Fax Number"):
        m = re.search(r"\bFax(?:\.|:)?\s*([+\d][+\d\s()./-]{5,})", imprint, re.I)
        if m:
            result["Fax Number"] = clean_text(m.group(1))
    if not result.get("Email ID") and not result.get("email"):
        m = re.search(r"[\w.+-]+@[\w.-]+\.\w{2,}", imprint)
        if m:
            result["email"] = m.group(0)
    if not result.get("Telephone Number"):
        m = re.search(r"\bTelefon(?:\.|:)?\s*([+\d][+\d\s()./-]{5,})", imprint, re.I)
        if m:
            result["Telephone Number"] = clean_text(m.group(1))

def parse_vendor_vehicle_count(html: str) -> int | None:
    """Extract the total vehicle count from a dealer page."""
    for payload in extract_next_payloads(html):
        for obj in iter_dicts(payload):
            total = obj.get("numResultsTotal")
            if isinstance(total, int):
                return total
            if isinstance(total, str) and total.isdigit():
                return int(total)

    for pattern in [
        r'"numResultsTotal"\s*:\s*(\d+)',
        r"data-testid=[\"']srp-header-title[\"'][^>]*>\s*(\d+)",
        r"\b(\d{1,6})\s+(?:Fahrzeuge|Angebote|Pkw|Lkw|Motorräder|Motorrad|Auflieger|Anhänger)\b",
        r"\((\d{1,6})\)",
    ]:
        match = re.search(pattern, html, re.I)
        if match:
            value = int(match.group(1))
            if 0 <= value < 1_000_000:
                return value

    soup = BeautifulSoup(html, "lxml")
    for elem in soup.find_all(["h1", "h2", "h3", "div", "span"]):
        text = clean_text(elem.get_text(" ", strip=True))
        match = re.search(r"\b(\d{1,6})\s+(?:Fahrzeuge|Angebote|Pkw|Lkw|Auflieger|Anhänger)\b", text, re.I)
        if match:
            return int(match.group(1))
    return None
