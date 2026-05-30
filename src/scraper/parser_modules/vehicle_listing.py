from typing import Any, Dict, List, Optional, Iterator, Union, Tuple
import json
import re
import logging
from bs4 import BeautifulSoup, Tag
from urllib.parse import parse_qs, urlparse
from src.scraper.parser_modules.normalization import clean_text, normalize_dealer_url, normalize_vehicle_url, dealer_identifier
from src.scraper.parser_modules.common import walk_json, iter_dicts, _none_if_placeholder, extract_next_payloads, _first_present
from src.scraper.parsers import KNOWN_BRANDS, VEHICLE_CATEGORY_LABELS, LISTING_ID_RE, DEFAULT_VEHICLE_CATEGORY_VALUES, VEHICLE_BODY_TYPE_LABELS, VEHICLE_CATEGORY_ALIASES, _parse_vehicle_json_ld
logger = logging.getLogger(__name__)

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
