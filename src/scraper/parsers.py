"""HTML and embedded Next.js payload parsers for mobile.de pages."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger("mobile_de.parsers")

HOME_BASE = "https://home.mobile.de"
SEARCH_BASE = "https://suchen.mobile.de"
DEALER_URL_RE = re.compile(r"https?://home\.mobile\.de/[A-Za-z0-9][A-Za-z0-9_-]*")
LISTING_ID_RE = re.compile(r'"listingId"\s*:\s*(\d{5,})')


DEFAULT_VEHICLE_CATEGORY_VALUES = [
    "Car",
    "Motorbike",
    "Motorhome",
    "VanUpTo7500",
    "TruckOver7500",
    "SemiTrailerTruck",
    "SemiTrailer",
    "Trailer",
    "ConstructionMachine",
    "Bus",
    "AgriculturalVehicle",
    "ForkliftTruck",
]


VEHICLE_CATEGORY_LABELS = {
    "Car": "PKW",
    "Motorbike": "Motorrad",
    "Motorhome": "Wohnmobil andere",
    "VanUpTo7500": "Transporter und Lkw bis 7,5 t",
    "TruckOver7500": "Lkw ab 7,5 t",
    "SemiTrailerTruck": "Sattelzugmaschinen",
    "SemiTrailer": "Auflieger",
    "Trailer": "Anhänger",
    "ConstructionMachine": "Baumaschinen",
    "Bus": "Busse",
    "AgriculturalVehicle": "Agrarfahrzeuge",
    "ForkliftTruck": "Stapler",
}


VEHICLE_CATEGORY_ALIASES = {
    "Car": ["Pkw", "PKW", "Car", "Auto", "Autos"],
    "Motorbike": ["Motorrad", "Motorräder", "Motorraeder", "Motorbike"],
    "Motorhome": ["Wohnmobil", "Wohnmobile", "Wohnmobil andere", "Motorhome"],
    "VanUpTo7500": [
        "Transporter",
        "Transporter und Lkw bis 7,5 t",
        "Lkw bis 7,5 t",
        "Van or truck up to 7.5 t",
        "Van or truck up to 7,5 t",
    ],
    "TruckOver7500": ["Lkw ab 7,5 t", "LKW ab 7,5 t", "Truck over 7.5 t", "Truck over 7,5 t"],
    "SemiTrailerTruck": ["Sattelzugmaschine", "Sattelzugmaschinen", "Semi-trailer truck"],
    "SemiTrailer": ["Auflieger", "Semi-trailer"],
    "Trailer": ["Anhänger", "Anhaenger", "Trailer"],
    "ConstructionMachine": ["Baumaschine", "Baumaschinen"],
    "Bus": ["Bus", "Busse"],
    "AgriculturalVehicle": ["Agrarfahrzeug", "Agrarfahrzeuge", "Agricultural vehicle"],
    "ForkliftTruck": ["Stapler", "Forklift truck"],
}


VEHICLE_BODY_TYPE_LABELS = {
    # Passenger cars
    "Cabrio": "Cabrio/Roadster",
    "Convertible": "Cabrio/Roadster",
    "SmallCar": "Kleinwagen",
    "EstateCar": "Kombi",
    "StationWagon": "Kombi",
    "Limousine": "Limousine",
    "SportsCar": "Sportwagen/Coupé",
    "SportsCarCoupe": "Sportwagen/Coupé",
    "OffRoad": "SUV/Geländewagen/Pickup",
    "Suv": "SUV/Geländewagen/Pickup",
    "Van": "Van/Kleinbus",
    "Minibus": "Van/Kleinbus",
    # Motorcycles
    "ChopperCruiser": "Chopper/Cruiser",
    "Moped": "Mofa/Mokick/Moped",
    "RallyeCross": "Rallye/Cross",
    "Streetfighter": "Streetfighter",
    "DirtBike": "Dirt Bike",
    "Racing": "Rennsport",
    "SuperMoto": "Super Moto",
    "Enduro": "Enduro/Reiseenduro",
    "NakedBike": "Naked Bike",
    "Scooter": "Roller/Scooter",
    "Tourer": "Tourer",
    "Sidecar": "Gespann/Seitenwagen",
    "PocketBike": "Pocket Bike",
    "Supersport": "Sportler/Supersportler",
    "Trike": "Trike",
    "LightweightMotorcycle": "Klein/Leichtkraftrad",
    "Quad": "Quad",
    "SportTourer": "Sporttourer",
    # Recreational vehicles
    "Alcove": "Alkoven",
    "MobileHome": "Mobilheim",
    "Integrated": "Integrierter",
    "SemiIntegrated": "Teilintegrierter",
    "PanelVan": "Kastenwagen",
    "Cabin": "Wohnkabine",
    "Caravan": "Wohnwagen",
    # Commercial vehicles
    "BoxAndIsolatedSemiTrailer": "Auflieger",
    "BoxSemiTrailer": "Auflieger",
    "CarCarrierSemiTrailer": "Auflieger",
    "ChassisSemiTrailer": "Auflieger",
    "SwapChassisSemiTrailer": "Auflieger",
    "PlatformSemiTrailer": "Auflieger",
    "RefrigeratorBodySemiTrailer": "Auflieger",
    "StakeBodyAndTarpaulinSemiTrailer": "Auflieger",
    "TipperSemiTrailer": "Auflieger",
    "WalkingFloorSemiTrailer": "Auflieger",
}


KNOWN_BRANDS = [
    "Mercedes-Benz",
    "Alfa Romeo",
    "Land Rover",
    "Volkswagen",
    "Citroën",
    "Citroen",
    "SsangYong",
    "Aston Martin",
    "Rolls-Royce",
    "DS Automobiles",
    "Audi",
    "BMW",
    "Skoda",
    "Škoda",
    "Seat",
    "Smart",
    "Cupra",
    "Mini",
    "MINI",
    "Porsche",
    "Volvo",
    "Opel",
    "Ford",
    "Fiat",
    "Lancia",
    "Maserati",
    "Ferrari",
    "Lamborghini",
    "Abarth",
    "Hyundai",
    "Kia",
    "Genesis",
    "Toyota",
    "Honda",
    "Nissan",
    "Mazda",
    "Mitsubishi",
    "Suzuki",
    "Subaru",
    "Daihatsu",
    "Lexus",
    "Infiniti",
    "Isuzu",
    "Peugeot",
    "Renault",
    "Dacia",
    "Tesla",
    "Polestar",
    "Jeep",
    "Dodge",
    "Chevrolet",
    "Andere",
]


KNOWN_SPEC_LABELS = {
    "Fahrzeugzustand",
    "Kategorie",
    "Fahrzeugtyp",
    "Baureihe",
    "Ausstattungslinie",
    "Kilometerstand",
    "Hubraum",
    "Leistung",
    "Getriebe",
    "Kraftstoffart",
    "Schadstoffklasse",
    "Umweltplakette",
    "Erstzulassung",
    "Anzahl der Fahrzeughalter",
    "Farbe",
    "Farbe (Hersteller)",
    "Anzahl Sitzplätze",
    "Anzahl der Türen",
    "CO₂-Emissionen",
    "CO2-Emissionen",
    "Kraftfahrzeugsteuer",
    "Innenausstattung",
    "Zylinder",
}


SPEC_LABEL_ALIASES = {
    "CO2-Emissionen": "CO₂-Emissionen",
    "CO₂ Emissionen": "CO₂-Emissionen",
    "CO2 Emissionen": "CO₂-Emissionen",
    "CO₂-Ausstoß": "CO₂-Emissionen",
    "CO2-Ausstoß": "CO₂-Emissionen",
    "Fahrzeughalter": "Anzahl der Fahrzeughalter",
    "Vorbesitzer": "Anzahl der Fahrzeughalter",
    "Anzahl Vorbesitzer": "Anzahl der Fahrzeughalter",
    "Anzahl der Vorbesitzer": "Anzahl der Fahrzeughalter",
    "Modellreihe": "Baureihe",
    "Series": "Baureihe",
    "Ausstattungslinie": "Ausstattungslinie",
    "Trim": "Ausstattungslinie",
    "Line": "Ausstattungslinie",
    "Edition": "Ausstattungslinie",
}


DETAIL_TARGET_FIELDS = [
    "CO₂-Emissionen",
    "Baureihe",
    "Ausstattungslinie",
    "Anzahl der Fahrzeughalter",
    "Hubraum",
    "Anzahl der Türen",
    "Schadstoffklasse",
    "Farbe",
    "Anzahl Sitzplätze",
]


def clean_text(value: Any) -> str:
    """Normalize whitespace while preserving German characters."""
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_dealer_url(url: str) -> str:
    """Normalize a mobile.de dealer URL to a stable, query-free homepage URL."""
    if not url:
        return ""
    url = url.strip().strip('"').strip("'")
    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("/"):
        url = urljoin(HOME_BASE, url)
    elif not url.startswith("http"):
        url = f"{HOME_BASE}/{url.lstrip('/')}"

    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != "home.mobile.de":
        return url
    parts = [part for part in parsed.path.split("/") if part]
    path = f"/{parts[0].upper()}" if len(parts) == 1 else parsed.path.rstrip("/")
    return urlunparse(("https", "home.mobile.de", path, "", "", ""))


def normalize_vehicle_url(url: str) -> str:
    """Normalize a vehicle URL or listing id to an absolute detail URL."""
    url = clean_text(url)
    if not url:
        return ""
    if url.isdigit():
        return f"{SEARCH_BASE}/fahrzeuge/details.html?id={url}"
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(SEARCH_BASE, url)
    if not url.startswith("http"):
        return f"https://{url}"
    return url


def dealer_identifier(url: str) -> str:
    """Return the stable slug/customer id part from a dealer URL."""
    parsed = urlparse(normalize_dealer_url(url))
    return parsed.path.strip("/").split("/")[0]


# ---------------------------------------------------------------------------
# Next.js flight payload parsing


def extract_next_payloads(html: str) -> list[Any]:
    """
    Extract JSON payloads pushed through ``self.__next_f.push`` scripts.

    mobile.de dealer pages put important structured data (dealerData,
    listingId, legalData, result counts) in these payloads. The outer script is
    JavaScript, but the push argument itself is a JSON array; the second array
    element is often another JSON value prefixed by an internal id like ``29:``.
    """
    payloads: list[Any] = []
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I)
    for script in scripts:
        script = script.strip()
        if not script.startswith("self.__next_f.push("):
            continue
        inner = script[len("self.__next_f.push(") :]
        if inner.endswith(");"):
            inner = inner[:-2]
        elif inner.endswith(")"):
            inner = inner[:-1]
        try:
            outer = json.loads(inner)
        except json.JSONDecodeError:
            continue
        payloads.append(outer)
        if isinstance(outer, list) and len(outer) > 1 and isinstance(outer[1], str):
            text = outer[1]
            _, sep, value = text.partition(":")
            candidate = value if sep and value[:1] in "[{" else text
            if candidate[:1] in "[{":
                try:
                    payloads.append(json.loads(candidate))
                except json.JSONDecodeError:
                    pass
    return payloads


def walk_json(value: Any) -> Iterator[Any]:
    """Yield every nested JSON-like value."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def iter_dicts(value: Any) -> Iterator[dict[str, Any]]:
    for item in walk_json(value):
        if isinstance(item, dict):
            yield item


def _none_if_placeholder(value: Any) -> str:
    text = clean_text(value)
    return "" if text in {"$undefined", "undefined", "None", "null"} else text


# ---------------------------------------------------------------------------
# Regional page parsing


def parse_regional_page(html: str) -> list[dict[str, str]]:
    """
    Parse a regional state page and extract dealer entries.

    The parser first uses visible anchors, then falls back to URLs embedded in
    Next.js script payloads. When names/addresses are not present in the
    regional card, the vendor scraper fills them from the dealer page.
    """
    soup = BeautifulSoup(html, "lxml")
    dealers: dict[str, dict[str, str]] = {}

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if not _looks_like_dealer_link(href):
            continue
        url = normalize_dealer_url(href)
        if not url:
            continue
        card = _nearest_card(link)
        name = _extract_name_from_link(link)
        street, plz, city = _extract_address_from_container(card or link.parent)
        dealers[url] = {
            "name": name,
            "url": url,
            "street": street,
            "plz": plz,
            "city": city,
        }

    # Fallback for URLs only present in script payloads.
    for raw_url in DEALER_URL_RE.findall(html):
        url = normalize_dealer_url(raw_url)
        if _looks_like_dealer_link(url) and url not in dealers:
            dealers[url] = {"name": "", "url": url, "street": "", "plz": "", "city": ""}

    result = sorted(dealers.values(), key=lambda item: item["url"].lower())
    logger.info("Parsed %d dealers from regional page.", len(result))
    return result


def _looks_like_dealer_link(href: str) -> bool:
    if not href:
        return False
    href = href.strip()
    if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
        return False
    if "/regional/" in href or href.endswith(".html"):
        return False
    normalized = normalize_dealer_url(href)
    parsed = urlparse(normalized)
    if parsed.netloc != "home.mobile.de":
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 1:
        return False
    slug = parts[0].lower()
    blocked = {
        "akam",
        "api",
        "cdn",
        "consent",
        "datenschutz",
        "favicon.ico",
        "haendler",
        "impressum",
        "kontakt",
        "robots.txt",
        "services",
        "static",
        "about",
    }
    return slug not in blocked and len(slug) > 1


def _nearest_card(link: Tag) -> Tag | None:
    for parent in link.parents:
        if not isinstance(parent, Tag):
            continue
        text = clean_text(parent.get_text(" ", strip=True))
        if len(text) > 20:
            return parent
    return None


def _extract_name_from_link(link: Tag) -> str:
    for selector in ["strong", "b", "h1", "h2", "h3", "[data-testid*='title']"]:
        elem = link.select_one(selector)
        if elem:
            text = clean_text(elem.get_text(" ", strip=True))
            if text:
                return text
    return clean_text(link.get_text(" ", strip=True))


def _extract_address_from_container(container: Tag | None) -> tuple[str, str, str]:
    if container is None:
        return "", "", ""
    text = clean_text(container.get_text(" ", strip=True))
    plz, city = "", ""
    m = re.search(r"\b(?:DE[-\s]?)?(\d{5})\s+([A-ZÄÖÜ][\wÄÖÜäöüß .'\-]+)", text)
    if m:
        plz = m.group(1)
        city = clean_text(m.group(2))
        city = re.split(r"\s{2,}|Kontakt|Telefon|Tel\.?|Bewertung", city)[0].strip(" ,")

    street = ""
    street_re = re.compile(
        r"([A-ZÄÖÜ0-9][\wÄÖÜäöüß .'\-]+(?:str\.|straße|strasse|weg|platz|allee|ring|damm|gasse|chaussee)\s+\d+[A-Za-z]?)",
        re.I,
    )
    sm = street_re.search(text)
    if sm:
        street = clean_text(sm.group(1))
    return street, plz, city


# ---------------------------------------------------------------------------
# Vendor page parsing


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


def _first_present(*values: Any) -> str:
    for value in values:
        cleaned = _none_if_placeholder(value)
        if cleaned:
            return cleaned
    return ""


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


# ---------------------------------------------------------------------------
# Vehicle URL and detail parsing


def parse_vehicle_listing_urls(html: str) -> list[str]:
    """Extract individual vehicle detail URLs from a dealer listing page."""
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if _is_vehicle_href(href):
            normalized = normalize_vehicle_url(href)
            if normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)

    for url in parse_vehicle_urls_from_next_data(html):
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_vehicle_listing_summaries(html: str) -> dict[str, dict[str, str]]:
    """Extract best-effort vehicle data visible on dealer listing cards."""
    summaries: dict[str, dict[str, str]] = {}

    for payload in extract_next_payloads(html):
        for obj in iter_dicts(payload):
            search_results = obj.get("searchResults")
            if isinstance(search_results, dict):
                for listing in search_results.get("listings") or []:
                    if not isinstance(listing, dict):
                        continue
                    summary = _summary_from_search_result_listing(listing)
                    url = summary.get("Vehicle_URL", "")
                    if url:
                        _merge_listing_summary(summaries, url, summary)

            listing_id = obj.get("listingId")
            if not _is_valid_listing_id(listing_id):
                continue
            url = normalize_vehicle_url(str(listing_id))
            strings = _meaningful_strings(obj)
            title = _choose_listing_title(strings)
            brand, model = split_vehicle_title(title)
            attrs = _choose_attribute_text(strings)
            attr_fields = extract_listing_attribute_fields(attrs)
            summary = {
                "Vehicle_URL": url,
                "Markes": brand,
                "Models": model,
                "Preis": _choose_price(strings),
                "Kilometerstand": _first_match(attrs, r"\b\d[\d. ]*\s*km\b"),
                "Erstzulassung": _first_match(attrs, r"\b(?:EZ\s*)?\d{2}/\d{4}\b").replace("EZ ", ""),
                "Leistung": _first_match(attrs, r"\b\d{1,4}\s*kW\s*\(\s*\d{1,4}\s*PS\s*\)|\b\d{1,4}\s*kW\b"),
                "Kraftstoffart": _first_match(attrs, r"\b(?:Benzin|Diesel|Elektro|Hybrid|Erdgas|Autogas|Wasserstoff)\b"),
                "Getriebe": _first_match(attrs, r"\b(?:Automatik|Schaltgetriebe|Halbautomatik)\b"),
                **attr_fields,
            }
            _merge_listing_summary(summaries, url, {k: v for k, v in summary.items() if v})

    return summaries


def parse_vehicle_category_options(
    html: str,
    *,
    require_positive_count: bool = False,
) -> list[dict[str, Any]]:
    """Return discovered vehicle category filters, optionally requiring count > 0."""
    category_options: list[dict[str, Any]] = []
    by_value: dict[str, dict[str, Any]] = {}
    allowed = set(DEFAULT_VEHICLE_CATEGORY_VALUES)

    def add(value: Any, *, label: Any = "", count: Any = None, url: Any = "") -> None:
        text = _none_if_placeholder(value)
        if text not in allowed:
            return
        parsed_count = _parse_count_value(count)
        if parsed_count is not None and parsed_count <= 0:
            return
        if require_positive_count and parsed_count is None:
            return

        existing = by_value.get(text)
        if existing is None:
            existing = {
                "value": text,
                "label": _none_if_placeholder(label) or VEHICLE_CATEGORY_LABELS.get(text, text),
                "count": parsed_count,
                "url": _none_if_placeholder(url),
            }
            by_value[text] = existing
            category_options.append(existing)
            return
        if existing.get("count") is None and parsed_count is not None:
            existing["count"] = parsed_count
        if not existing.get("label") and label:
            existing["label"] = _none_if_placeholder(label)
        if not existing.get("url") and url:
            existing["url"] = _none_if_placeholder(url)

    soup = BeautifulSoup(html, "lxml")
    sidebar_options = _category_options_from_sidebar_inputs(soup)
    for option in sidebar_options:
        add(
            option.get("value"),
            label=option.get("label"),
            count=option.get("count"),
            url=option.get("url", ""),
        )
    if sidebar_options:
        return category_options

    for payload in extract_next_payloads(html):
        for obj in iter_dicts(payload):
            count = _category_count_from_obj(obj)
            label = _first_present(obj.get("label"), obj.get("name"), obj.get("localized"))
            add(obj.get("vc"), label=label, count=count)
            add(obj.get("vehicleCategory"), label=label, count=count)
            raw_values = obj.get("values")
            if isinstance(raw_values, list) and not require_positive_count:
                for value in raw_values:
                    add(value)
            raw_options = obj.get("options")
            if isinstance(raw_options, list):
                for option in raw_options:
                    if isinstance(option, dict):
                        add(
                            option.get("value"),
                            label=_first_present(option.get("label"), option.get("name"), option.get("localized")),
                            count=_category_count_from_obj(option),
                        )

    for elem in soup.find_all(["a", "button", "label"]):
        if elem.find_parent(["script", "style", "noscript"]):
            continue
        text = clean_text(elem.get_text(" ", strip=True))
        if not text:
            continue
        href = _none_if_placeholder(elem.get("href") or elem.get("data-href"))
        href_value = _category_value_from_href(href)
        if href_value:
            add(
                href_value,
                label=_category_label_from_text(text, href_value),
                count=_category_count_from_text(text, href_value),
                url=href,
            )
            continue

    return category_options


def _category_options_from_sidebar_inputs(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Parse the real sidebar vehicle-category controls from labelled input chips."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = set(DEFAULT_VEHICLE_CATEGORY_VALUES)
    for input_elem in soup.select("input[value]"):
        value = _none_if_placeholder(input_elem.get("value"))
        if value not in allowed or value in seen:
            continue
        label_elem = input_elem.find_parent("label")
        if label_elem is None:
            continue
        text = clean_text(label_elem.get_text(" ", strip=True))
        count = _category_count_from_text(text, value)
        if count is None:
            count = _parenthesized_count_from_text(text)
        if count is None or count <= 0:
            continue
        label = _category_sidebar_label(label_elem, value)
        options.append({"value": value, "label": label, "count": count, "url": ""})
        seen.add(value)
    return options


def _category_sidebar_label(label_elem: Tag, value: str) -> str:
    for elem in label_elem.find_all(True):
        class_text = " ".join(str(part) for part in elem.get("class", []))
        if "vehicleCategoryChipLabel" in class_text:
            text = clean_text(elem.get_text(" ", strip=True))
            if text:
                return text
    return _category_label_from_text(clean_text(label_elem.get_text(" ", strip=True)), value)


def parse_vehicle_category_values(html: str) -> list[str]:
    """Return vehicle category query values exposed by the dealer inventory page."""
    values: list[str] = []
    allowed = set(DEFAULT_VEHICLE_CATEGORY_VALUES)

    def add(value: Any) -> None:
        text = _none_if_placeholder(value)
        if text in allowed and text not in values:
            values.append(text)

    for option in parse_vehicle_category_options(html, require_positive_count=True):
        add(option.get("value"))

    for payload in extract_next_payloads(html):
        for obj in iter_dicts(payload):
            add(obj.get("vc"))
            add(obj.get("vehicleCategory"))
            raw_values = obj.get("values")
            if isinstance(raw_values, list):
                for value in raw_values:
                    add(value)
            options = obj.get("options")
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict):
                        add(option.get("value"))

    return values


def _category_count_from_obj(obj: dict[str, Any]) -> int | None:
    for key in [
        "count",
        "cnt",
        "numResults",
        "numResultsTotal",
        "resultCount",
        "resultsCount",
        "total",
        "hits",
    ]:
        count = _parse_count_value(obj.get(key))
        if count is not None:
            return count
    return None


def _parse_count_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = clean_text(value)
    match = re.search(r"\d[\d.\s]*", text)
    if not match:
        return None
    return int(re.sub(r"\D", "", match.group(0)))


def _parenthesized_count_from_text(text: str) -> int | None:
    matches = re.findall(r"[\(\[]\s*(\d{1,6}(?:[.\s]\d{3})*)\s*[\)\]]", clean_text(text))
    if not matches:
        return None
    return _parse_count_value(matches[-1])


def _category_value_from_href(href: str) -> str:
    if not href:
        return ""
    query = parse_qs(urlparse(href).query)
    values = query.get("vc") or query.get("vehicleCategory")
    if values:
        value = _none_if_placeholder(values[0])
        if value in DEFAULT_VEHICLE_CATEGORY_VALUES:
            return value
    return ""


def _category_aliases(value: str) -> list[str]:
    aliases = [value, VEHICLE_CATEGORY_LABELS.get(value, "")]
    aliases.extend(VEHICLE_CATEGORY_ALIASES.get(value, []))
    return [alias for alias in dict.fromkeys(clean_text(alias) for alias in aliases) if alias]


def _category_label_from_text(text: str, value: str) -> str:
    lowered = text.lower()
    for alias in _category_aliases(value):
        if alias.lower() in lowered:
            return alias
    return VEHICLE_CATEGORY_LABELS.get(value, value)


def _category_count_from_text(text: str, value: str) -> int | None:
    cleaned = clean_text(text)
    for alias in _category_aliases(value):
        escaped = re.escape(alias)
        patterns = [
            rf"\b{escaped}\b\s*[\(\[]?\s*(\d{{1,6}}(?:[.\s]\d{{3}})*)",
            rf"(\d{{1,6}}(?:[.\s]\d{{3}})*)\s*\b{escaped}\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned, re.I)
            if match:
                return _parse_count_value(match.group(1))
    return None


def _merge_listing_summary(
    summaries: dict[str, dict[str, str]],
    url: str,
    incoming: dict[str, str],
) -> None:
    incoming = {key: value for key, value in incoming.items() if value}
    existing = summaries.get(url, {})
    if not existing:
        summaries[url] = incoming
        return
    merged = {**incoming, **existing}
    for key, value in incoming.items():
        if not merged.get(key):
            merged[key] = value
    if _summary_score(incoming) > _summary_score(existing):
        merged = {**existing, **incoming}
    summaries[url] = merged


def _summary_score(summary: dict[str, str]) -> int:
    return sum(1 for value in summary.values() if clean_text(value))


def _summary_from_search_result_listing(listing: dict[str, Any]) -> dict[str, str]:
    listing_id = listing.get("id") or listing.get("listingId")
    if not _is_valid_listing_id(listing_id):
        return {}

    attr = listing.get("attr") if isinstance(listing.get("attr"), dict) else {}
    title = _first_present(
        listing.get("title"),
        " ".join(
            part
            for part in [listing.get("shortTitle"), listing.get("subTitle")]
            if _none_if_placeholder(part)
        ),
    )
    make = _localized_value(listing.get("make"))
    model = _model_text_from_listing(title, make, listing)

    summary = {
        "Vehicle_URL": normalize_vehicle_url(str(listing_id)),
        "Markes": make or split_vehicle_title(title)[0],
        "Models": model,
        "Fahrzeugtyp": _vehicle_type_from_listing(listing, attr),
        "Fahrzeugzustand": _vehicle_condition_from_listing(listing),
        "Erstzulassung": _first_present(attr.get("fr"), attr.get("firstRegistration")),
        "Kilometerstand": _first_present(attr.get("ml"), attr.get("mileage")),
        "Kraftstoffart": _first_present(attr.get("ft"), attr.get("fuel")),
        "CO₂-Emissionen": _co2_from_listing(listing, attr),
        "Preis": _price_from_listing(listing),
        "Leistung": _first_present(attr.get("pw"), attr.get("power")),
        "Anzahl Sitzplätze": _first_present(attr.get("sc"), attr.get("seats")),
        "Getriebe": _first_present(attr.get("tr"), attr.get("transmission")),
        "Schadstoffklasse": _first_present(attr.get("emc"), attr.get("emissionClass")),
        "Farbe": _first_present(attr.get("ecol"), attr.get("color")),
        "Baureihe": _first_present(attr.get("sr"), attr.get("series")),
        "Ausstattungslinie": _first_present(attr.get("trim"), attr.get("trimLine")),
        "Hubraum": _first_present(attr.get("cc"), attr.get("ccm"), attr.get("displacement")),
        "Anzahl der Türen": _first_present(attr.get("door"), attr.get("doors")),
        "Anzahl der Fahrzeughalter": _first_present(
            attr.get("owners"),
            attr.get("owner"),
            attr.get("pvo"),
            attr.get("pv"),
            attr.get("vehicleOwners"),
            attr.get("previousOwners"),
            attr.get("numberOfOwners"),
        ),
        "Fahrzeugtyp_Raw": _first_present(listing.get("category"), attr.get("c")),
        "Vehicle_Category": _first_present(listing.get("vc"), listing.get("segment")),
    }
    summary.update(_financing_from_search_result_listing(listing, summary["Preis"]))
    return {key: value for key, value in summary.items() if value}


def _localized_value(value: Any) -> str:
    if isinstance(value, dict):
        return _first_present(value.get("localized"), value.get("name"), value.get("value"), value.get("id"))
    return _none_if_placeholder(value)


def _model_text_from_listing(title: str, make: str, listing: dict[str, Any]) -> str:
    title = clean_text(title)
    make = clean_text(make)
    if title and make and title.lower().startswith(make.lower()):
        return clean_text(title[len(make) :])
    model = _localized_value(listing.get("model"))
    subtitle = _none_if_placeholder(listing.get("subTitle"))
    return clean_text(f"{model} {subtitle}") if model or subtitle else split_vehicle_title(title)[1]


def _vehicle_type_from_listing(listing: dict[str, Any], attr: dict[str, Any]) -> str:
    vc = _none_if_placeholder(listing.get("vc") or listing.get("segment"))
    raw_category = _first_present(listing.get("category"), attr.get("c"))
    if vc in {"Car", "Motorbike", "Motorhome"}:
        return _vehicle_body_label(raw_category) or VEHICLE_CATEGORY_LABELS.get(vc, "")
    return VEHICLE_CATEGORY_LABELS.get(vc) or _vehicle_body_label(raw_category) or raw_category


def _vehicle_body_label(value: Any) -> str:
    text = _none_if_placeholder(value)
    if not text:
        return ""
    return VEHICLE_BODY_TYPE_LABELS.get(text, text)


def _vehicle_condition_from_listing(listing: dict[str, Any]) -> str:
    if listing.get("isDamageCase") is True or listing.get("hasDamage") is True:
        return "Beschädigt"
    if listing.get("readyToDrive") is False:
        return "Nicht fahrtauglich"
    if listing.get("hasDamage") is False:
        return "Unfallfrei"
    return ""


def _price_from_listing(listing: dict[str, Any]) -> str:
    price = listing.get("price")
    if isinstance(price, dict):
        gross = price.get("grs") if isinstance(price.get("grs"), dict) else {}
        net = price.get("nt") if isinstance(price.get("nt"), dict) else {}
        return _first_present(gross.get("localized"), net.get("localized"))
    return _first_present(listing.get("p"), listing.get("price"))


def _co2_from_listing(listing: dict[str, Any], attr: dict[str, Any]) -> str:
    for key in ["co2", "co2Emissions", "co2Emission", "co₂", "envkvCo2"]:
        value = _none_if_placeholder(attr.get(key))
        if value:
            return value
    strings = _meaningful_strings(listing)
    return _first_match(" • ".join(strings), r"\b\d{1,4}\s*g/km\b")


def _financing_from_search_result_listing(listing: dict[str, Any], vehicle_price: str) -> dict[str, str]:
    plans = listing.get("financePlans")
    if not isinstance(plans, list) or not plans:
        return {}
    plan = next((item for item in plans if isinstance(item, dict)), {})
    offer = plan.get("offer") if isinstance(plan.get("offer"), dict) else {}
    localized = offer.get("localized") if isinstance(offer.get("localized"), dict) else {}
    monthly = _first_present(localized.get("monthlyInstallment"), offer.get("monthlyInstallment"))
    result = {
        "Financing": f"{monthly} mtl." if monthly and "€" in monthly and "mtl" not in monthly.lower() else monthly,
        "Bank": _first_present(offer.get("bankName")),
        "Darlehensvermittler": _first_present(offer.get("loanBroker")),
        "Fahrzeugpreis": vehicle_price,
        "Anzahlung": _first_present(localized.get("downPayment"), offer.get("downPayment")),
        "Jährliche Kilometerleistung": _first_present(localized.get("yearlyMileage"), offer.get("yearlyMileage")),
        "Schlussrate": _first_present(localized.get("finalInstallment"), offer.get("finalInstallment")),
        "Fester Sollzins p.a.": _first_present(
            localized.get("interestRateNominal"),
            offer.get("interestRateNominal"),
        ),
        "Effektiver Jahreszins": _first_present(
            localized.get("interestRateEffective"),
            offer.get("interestRateEffective"),
        ),
        "Gesamtzins": _first_present(localized.get("totalInterest"), offer.get("totalInterest")),
        "Gesamtbetrag": _first_present(localized.get("totalAmount"), offer.get("totalAmount")),
        "Laufzeit": _credit_term(localized.get("creditTerm") or offer.get("creditTerm")),
    }
    return {key: value for key, value in result.items() if value}


def _credit_term(value: Any) -> str:
    text = _none_if_placeholder(value)
    if not text:
        return ""
    return text if re.search(r"\b(?:Monat|month)", text, re.I) else f"{text} Monate"


def parse_vehicle_urls_from_next_data(html: str) -> list[str]:
    """Build vehicle detail URLs from listing ids embedded in Next payloads."""
    ids: list[str] = []
    seen: set[str] = set()

    for payload in extract_next_payloads(html):
        for obj in iter_dicts(payload):
            listing_id = obj.get("listingId")
            if isinstance(listing_id, int):
                text = str(listing_id)
            elif isinstance(listing_id, str) and listing_id.isdigit():
                text = listing_id
            else:
                continue
            if text not in seen and _is_valid_listing_id(text):
                seen.add(text)
                ids.append(text)

    for match in LISTING_ID_RE.findall(html):
        if match not in seen:
            seen.add(match)
            ids.append(match)

    return [normalize_vehicle_url(listing_id) for listing_id in ids]


def _is_valid_listing_id(value: Any) -> bool:
    text = str(value) if value is not None else ""
    return text.isdigit() and len(text) >= 8


def _meaningful_strings(value: Any) -> list[str]:
    strings: list[str] = []
    for item in walk_json(value):
        if not isinstance(item, str):
            continue
        text = clean_text(item)
        if not text or text in {"$undefined", "undefined", "null"}:
            continue
        if "__" in text or text.startswith("$") or "module" in text.lower():
            continue
        if "classistatic" in text or re.fullmatch(r"[0-9a-fA-F-]{20,}", text):
            continue
        if text.startswith("listing-") or text.startswith("srp/"):
            continue
        strings.append(text)
    return strings


def _choose_listing_title(strings: list[str]) -> str:
    skip = {
        "default",
        "Header",
        "ResultList",
        "SemiTrailer",
        "Trailer",
        "Car",
        "Truck",
        "Motorbike",
        "Vehicle",
    }
    for text in strings:
        if text in skip:
            continue
        if "€" in text or "MwSt" in text or "data:image" in text:
            continue
        if re.search(r"\b(?:EZ|km|kW|PS)\b", text):
            continue
        if 4 <= len(text) <= 140 and re.search(r"[A-Za-zÄÖÜäöüß]", text):
            return text
    return ""


def split_vehicle_title(title: str) -> tuple[str, str]:
    title = clean_text(title)
    if not title:
        return "", ""
    title = _strip_new_badge(title)
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if title.lower().startswith(brand.lower()):
            return brand, clean_text(title[len(brand) :])
    parts = title.split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")


def _strip_new_badge(title: str) -> str:
    if not title.upper().startswith("NEU"):
        return title
    candidate = title[3:].lstrip()
    if not candidate:
        return title
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if candidate.lower().startswith(brand.lower()):
            return candidate
    return title


def _choose_price(strings: list[str]) -> str:
    for text in strings:
        match = re.search(r"\b\d[\d.]*,?\d*\s*€(?:\s*\([^)]*\))?", text)
        if match:
            return clean_text(match.group(0))
    return ""


def _choose_attribute_text(strings: list[str]) -> str:
    attributes = [
        text for text in strings
        if "•" in text or re.search(r"\b(?:EZ|km|kW|PS|Benzin|Diesel|Automatik)\b", text)
    ]
    return " • ".join(attributes)


def extract_listing_attribute_fields(text: str) -> dict[str, str]:
    """Split card attributes into vehicle type and condition where possible."""
    first = _first_attribute(text)
    if not first:
        return {}
    condition_markers = {
        "unfallfrei",
        "gebrauchtfahrzeug",
        "neufahrzeug",
        "vorführfahrzeug",
        "tageszulassung",
        "beschädigt",
        "fahrtauglich",
        "nicht fahrtauglich",
        "neuwagen",
    }
    if first.lower() in condition_markers:
        return {"Fahrzeugzustand": first}
    if re.search(r"\b(?:EZ\s*)?\d{2}/\d{4}\b|\b\d[\d. ]*\s*km\b|\b\d{1,4}\s*kW\b", first, re.I):
        return {}
    return {"Fahrzeugtyp": first}


def _first_attribute(text: str) -> str:
    if not text:
        return ""
    return clean_text(text.split("•", 1)[0])


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I)
    return clean_text(match.group(0)) if match else ""


def _is_vehicle_href(href: str) -> bool:
    if not href or href.startswith(("mailto:", "tel:", "#")):
        return False
    return any(
        marker in href
        for marker in [
            "/fahrzeuge/details",
            "/auto-inserat/",
            "suchen.mobile.de/fahrzeuge/details",
        ]
    )


def parse_vehicle_title(html: str) -> tuple[str, str]:
    """Extract manufacturer and model from JSON-LD or visible title."""
    title = ""
    json_ld = _parse_vehicle_json_ld(html)
    if json_ld:
        title = json_ld.get("name", "")
        brand = json_ld.get("brand", "")
        model = json_ld.get("model", "")
        if brand:
            return brand, model or _strip_brand(title, brand)

    soup = BeautifulSoup(html, "lxml")
    for selector in [
        "h1",
        "[data-testid='listing-title']",
        "[data-testid*='title'] h1",
        "[data-testid*='title'] h3",
        "div.listing-title",
        "title",
    ]:
        elem = soup.select_one(selector)
        if elem:
            title = clean_text(elem.get_text(" ", strip=True))
            if title:
                break
    if not title:
        return "", ""
    title = _strip_price_from_title(title)

    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if title.lower().startswith(brand.lower()):
            return brand, clean_text(title[len(brand) :])

    return split_vehicle_title(title)


def _strip_brand(title: str, brand: str) -> str:
    if title.lower().startswith(brand.lower()):
        return clean_text(title[len(brand) :])
    return title


def _strip_price_from_title(title: str) -> str:
    return clean_text(re.sub(r"\s+für\s+\d[\d.]*,?\d*\s*€.*$", "", title, flags=re.I))


def parse_vehicle_price(html: str) -> str:
    """Extract the main price from a vehicle detail page."""
    soup = BeautifulSoup(html, "lxml")
    for selector in [
        "[data-testid='price-label']",
        "[data-testid='main-price-label']",
        ".PriceLabel-module__tsmUda__mainPrice",
        "[class*='mainPrice']",
    ]:
        elem = soup.select_one(selector)
        if elem:
            price_text = clean_text(elem.get_text(" ", strip=True))
            price_text = re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]", "", price_text).strip()
            if "€" in price_text:
                return price_text

    json_ld = _parse_vehicle_json_ld(html)
    if json_ld.get("price"):
        return clean_text(f"{json_ld['price']} €")

    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"\b\d[\d.]*,?\d*\s*€(?:\s*\([^)]*\))?", text)
    return clean_text(match.group(0)) if match else ""


def parse_vehicle_specs(html: str) -> dict[str, str]:
    """Parse technical data and quick facts from a vehicle detail page."""
    soup = BeautifulSoup(html, "lxml")
    specs: dict[str, str] = {}

    _extract_dl_pairs(soup, specs)
    _extract_table_pairs(soup, specs)
    _extract_known_label_pairs(soup, specs)
    _extract_initial_state_specs(html, specs)
    _extract_from_next_text(html, specs)
    _extract_quick_stats(clean_text(soup.get_text(" ", strip=True)), specs)
    _extract_description_line_specs(soup, specs)

    if "CO2-Emissionen" in specs and "CO₂-Emissionen" not in specs:
        specs["CO₂-Emissionen"] = specs["CO2-Emissionen"]
    if "Fahrzeugtyp" in specs and "Kategorie" not in specs:
        specs["Kategorie"] = specs["Fahrzeugtyp"]
    return specs


def _extract_dl_pairs(soup: BeautifulSoup, specs: dict[str, str]) -> None:
    for dt in soup.find_all("dt"):
        label = clean_text(dt.get_text(" ", strip=True)).rstrip(":")
        dd = dt.find_next_sibling("dd")
        value = clean_text(dd.get_text(" ", strip=True)) if dd else ""
        _add_spec(specs, label, value)


def _extract_table_pairs(soup: BeautifulSoup, specs: dict[str, str]) -> None:
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            _add_spec(
                specs,
                clean_text(cells[0].get_text(" ", strip=True)).rstrip(":"),
                clean_text(cells[1].get_text(" ", strip=True)),
            )


def _extract_known_label_pairs(soup: BeautifulSoup, specs: dict[str, str]) -> None:
    elements = list(soup.find_all(True))
    labels_lower = {_canonical_spec_label(label).lower(): _canonical_spec_label(label) for label in KNOWN_SPEC_LABELS}
    for index, elem in enumerate(elements):
        text = clean_text(elem.get_text(" ", strip=True)).rstrip(":")
        canonical = _canonical_spec_label(text)
        if not canonical:
            for raw_label in [*KNOWN_SPEC_LABELS, *SPEC_LABEL_ALIASES]:
                label = _canonical_spec_label(raw_label) or raw_label
                if not label:
                    continue
                match = re.match(rf"^{re.escape(raw_label)}\s*[:\-]\s*(.+)$", text, re.I)
                if match:
                    canonical = label
                    value = match.group(1).strip(" :")
                    _add_spec(specs, canonical, value)
                    break
            continue
        value = ""
        sibling = elem.find_next_sibling()
        if sibling:
            value = clean_text(sibling.get_text(" ", strip=True))
        if not value and index + 1 < len(elements):
            candidate = clean_text(elements[index + 1].get_text(" ", strip=True))
            if candidate.lower().rstrip(":") not in labels_lower:
                value = candidate
        _add_spec(specs, canonical, value)


def _extract_initial_state_specs(html: str, specs: dict[str, str]) -> None:
    state = _extract_window_initial_state(html)
    if not state:
        return
    for obj in iter_dicts(state):
        label = _none_if_placeholder(obj.get("label"))
        value = _none_if_placeholder(obj.get("value"))
        if label and value:
            _add_spec(specs, label, value)
        tag = _none_if_placeholder(obj.get("tag"))
        tag_mapping = {
            "modelRange": "Baureihe",
            "trimLine": "Ausstattungslinie",
            "line": "Ausstattungslinie",
            "edition": "Ausstattungslinie",
            "numberOfPreviousOwners": "Anzahl der Fahrzeughalter",
            "cubicCapacity": "Hubraum",
            "doorCount": "Anzahl der Türen",
            "emissionClass": "Schadstoffklasse",
            "manufacturerColorName": "Farbe (Hersteller)",
            "color": "Farbe",
            "numSeats": "Anzahl Sitzplätze",
            "envkv.co2Emissions": "CO₂-Emissionen",
            "co2Emissions": "CO₂-Emissionen",
            "co2Emission": "CO₂-Emissionen",
        }
        if tag and value and tag in tag_mapping:
            _add_spec(specs, tag_mapping[tag], value)


def _extract_window_initial_state(html: str) -> dict[str, Any]:
    marker = "window.__INITIAL_STATE__"
    start_marker = html.find(marker)
    if start_marker < 0:
        return {}
    start = html.find("{", start_marker)
    if start < 0:
        return {}
    level = 0
    in_string = False
    escaped = False
    for index, char in enumerate(html[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            level += 1
        elif char == "}":
            level -= 1
            if level == 0:
                try:
                    data = json.loads(html[start : index + 1])
                except json.JSONDecodeError:
                    return {}
                return data if isinstance(data, dict) else {}
    return {}


def _extract_from_next_text(html: str, specs: dict[str, str]) -> None:
    # Decode Next payload strings and scan them as text. This catches listing
    # attributes that are not emitted as visible DOM in static HTML snapshots.
    texts: list[str] = []
    for payload in extract_next_payloads(html):
        for item in walk_json(payload):
            if isinstance(item, str) and len(item) < 200:
                texts.append(item)
    text = clean_text(" ".join(texts))
    _extract_quick_stats(text, specs)

    for label in KNOWN_SPEC_LABELS:
        canonical = _canonical_spec_label(label) or label
        if canonical in specs:
            continue
        match = re.search(rf"{re.escape(label)}\s*[:\-]\s*([^|•]{{1,80}})", text)
        if match:
            _add_spec(specs, canonical, clean_text(match.group(1)))


def _extract_quick_stats(text: str, specs: dict[str, str]) -> None:
    patterns = [
        (r"\b(\d[\d. ]*)\s*km\b", "Kilometerstand"),
        (r"\b(\d{1,4}\s*kW\s*\(\s*\d{1,4}\s*PS\s*\))", "Leistung"),
        (r"\b(\d{1,4}\s*kW)\b", "Leistung"),
        (r"\bEZ\s*(\d{2}/\d{4})", "Erstzulassung"),
        (r"\bErstzulassung\s*[:\-]?\s*(\d{2}/\d{4})", "Erstzulassung"),
        (r"\b(Benzin|Diesel|Elektro|Hybrid|Erdgas|Autogas|Wasserstoff)\b", "Kraftstoffart"),
        (r"\b(Automatik|Schaltgetriebe|Halbautomatik)\b", "Getriebe"),
        (r"\b(\d+\s*g\s*/?\s*km)\b", "CO₂-Emissionen"),
        (r"\b(\d+[.,]?\d*\s*cm³)\b", "Hubraum"),
    ]
    for pattern, key in patterns:
        if key in specs and specs[key]:
            continue
        match = re.search(pattern, text, re.I)
        if match:
            specs[key] = clean_text(match.group(1))


def _extract_description_line_specs(soup: BeautifulSoup, specs: dict[str, str]) -> None:
    if specs.get("Ausstattungslinie"):
        return
    text = clean_text(soup.get_text(" ", strip=True))
    patterns = [
        r"\bDesign-\s*und\s*Ausstattungslinie\s+([^.;,\n|•<]{2,80})",
        r"\bAusstattungslinie\s+([^.;,\n|•<]{2,80})",
        r"\b(?:AMG|S\s*line|M\s*Sport|R-Line|Edition)\s+[A-Za-z0-9][^.;,\n|•<]{0,60}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        value = match.group(1) if match.lastindex else match.group(0)
        value = re.split(r"\s+(?:[A-Z]\d{2,3}|\d{3}[A-Z]?|[A-Z]{2,4}\d?)\s+", value, maxsplit=1)[0]
        value = re.split(r"\s+[A-Za-z0-9-]*Paket\b|\s+Exterieur\b|\s+Interieur\b", value, maxsplit=1, flags=re.I)[0]
        value = re.sub(r"\b(?:Paket|Exterieur|Interieur|Sicherheit)\b.*$", "", value, flags=re.I)
        value = clean_text(value).strip(" -")
        if value and value.lower() not in {"und -pakete", "ausstattungslinien und -pakete"}:
            _add_spec(specs, "Ausstattungslinie", value)
            return


def _add_spec(specs: dict[str, str], label: str, value: str) -> None:
    label = _canonical_spec_label(label)
    value = clean_text(value)
    if not label or not value:
        return
    if re.fullmatch(r"[-–—]+\s*(?:g\s*/?\s*km|cm³|ccm)?", value, re.I):
        return
    if label not in KNOWN_SPEC_LABELS:
        return
    if label not in specs or not specs[label]:
        specs[label] = value


def _canonical_spec_label(label: str) -> str:
    label = clean_text(label).rstrip(":")
    if not label:
        return ""
    lowered = label.lower()
    if lowered.startswith(("co₂-emissionen", "co2-emissionen", "co₂ emissionen", "co2 emissionen")):
        return "CO₂-Emissionen"
    if label in KNOWN_SPEC_LABELS:
        return SPEC_LABEL_ALIASES.get(label, label)
    alias_map = {key.lower(): value for key, value in SPEC_LABEL_ALIASES.items()}
    if lowered in alias_map:
        return alias_map[lowered]
    for known in KNOWN_SPEC_LABELS:
        if lowered == known.lower():
            return known
    return ""


def parse_vehicle_detail_fields(html: str) -> dict[str, str]:
    """Return normalized vehicle fields parsed from one detail-page HTML snapshot."""
    fields: dict[str, str] = {}
    brand, model = parse_vehicle_title(html)
    if brand:
        fields["Markes"] = brand
    if model:
        fields["Models"] = model
    price = parse_vehicle_price(html)
    if price:
        fields["Preis"] = price
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
    for spec_key, field_key in spec_mapping.items():
        value = specs.get(spec_key, "")
        if value:
            fields[field_key] = value
    financing = parse_financing_data(html)
    fields.update(financing)
    if fields.get("Financing") and not fields.get("Finanzierung"):
        fields["Finanzierung"] = fields["Financing"]
    return fields






def _parse_vehicle_json_ld(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            schema_type = item.get("@type", "")
            if schema_type not in {"Vehicle", "Car", "Product"}:
                continue
            offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            brand = item.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            return {
                "name": _none_if_placeholder(item.get("name")),
                "brand": _none_if_placeholder(brand),
                "model": _none_if_placeholder(item.get("model")),
                "price": _none_if_placeholder(offers.get("price")),
            }
    return {}

from src.scraper.parser_modules.financing import parse_financing_data, _extract_financing_pairs