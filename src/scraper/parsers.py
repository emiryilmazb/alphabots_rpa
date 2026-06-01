"""HTML and embedded Next.js payload parsers for mobile.de pages."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

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
    "TruckOver7500": [
        "Lkw ab 7,5 t",
        "LKW ab 7,5 t",
        "Truck over 7.5 t",
        "Truck over 7,5 t",
    ],
    "SemiTrailerTruck": [
        "Sattelzugmaschine",
        "Sattelzugmaschinen",
        "Semi-trailer truck",
    ],
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


# ---------------------------------------------------------------------------
# Vehicle URL and detail parsing


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
    labels_lower = {
        _canonical_spec_label(label).lower(): _canonical_spec_label(label)
        for label in KNOWN_SPEC_LABELS
    }
    for index, elem in enumerate(elements):
        text = clean_text(elem.get_text(" ", strip=True)).rstrip(":")
        canonical = _canonical_spec_label(text)
        if not canonical:
            for raw_label in [*KNOWN_SPEC_LABELS, *SPEC_LABEL_ALIASES]:
                label = _canonical_spec_label(raw_label) or raw_label
                if not label:
                    continue
                match = re.match(
                    rf"^{re.escape(raw_label)}\s*[:\-]\s*(.+)$", text, re.I
                )
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
        (
            r"\b(Benzin|Diesel|Elektro|Hybrid|Erdgas|Autogas|Wasserstoff)\b",
            "Kraftstoffart",
        ),
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
        value = re.split(
            r"\s+(?:[A-Z]\d{2,3}|\d{3}[A-Z]?|[A-Z]{2,4}\d?)\s+", value, maxsplit=1
        )[0]
        value = re.split(
            r"\s+[A-Za-z0-9-]*Paket\b|\s+Exterieur\b|\s+Interieur\b",
            value,
            maxsplit=1,
            flags=re.I,
        )[0]
        value = re.sub(
            r"\b(?:Paket|Exterieur|Interieur|Sicherheit)\b.*$", "", value, flags=re.I
        )
        value = clean_text(value).strip(" -")
        if value and value.lower() not in {
            "und -pakete",
            "ausstattungslinien und -pakete",
        }:
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
    if lowered.startswith(
        ("co₂-emissionen", "co2-emissionen", "co₂ emissionen", "co2 emissionen")
    ):
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


from src.scraper.parser_modules.financing import parse_financing_data
from src.scraper.parser_modules.common import (
    walk_json,
    iter_dicts,
    _none_if_placeholder,
    extract_next_payloads,
)
from src.scraper.parser_modules.vehicle_listing import (
    parse_vehicle_title,
    parse_vehicle_price,
)
