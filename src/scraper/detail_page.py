"""Detail-page classification helpers for mobile.de vehicle pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.scraper.parsers import clean_text, parse_vehicle_price, parse_vehicle_specs, parse_vehicle_title

DetailPageClassification = Literal[
    "real_detail_page",
    "error_page",
    "home_redirect",
    "listing_page",
    "blank_page",
    "unknown",
]


ERROR_MARKERS = [
    "access denied",
    "zugriff verweigert",
    "an error occurred while processing your request",
    "errors.edgesuite.net",
    "forbidden",
    "perimeterx",
    "px-captcha",
    "_px",
    "akamai bot",
    "captcha-container",
]

HOME_TITLE_MARKERS = [
    "mobile.de",
    "gebrauchtwagen",
    "neuwagen",
]

DETAIL_PATH_MARKERS = [
    "/fahrzeuge/details",
    "/auto-inserat/",
]

DETAIL_CONTENT_MARKERS = [
    "fahrzeugbeschreibung",
    "technische daten",
    "kilometerstand",
    "erstzulassung",
    "kraftstoffart",
]


@dataclass
class DetailPageResult:
    classification: DetailPageClassification
    reason: str = ""
    signals: dict[str, object] = field(default_factory=dict)


def classify_detail_page(html: str, url: str = "", title: str = "") -> DetailPageResult:
    """Classify a captured mobile.de page before parsing detail fields."""
    html = html or ""
    url = url or ""
    title = clean_text(title)
    lowered_html = html.lower()
    lowered_title = title.lower()
    lowered_url = url.lower()

    if not clean_text(html) and not title and not url:
        return DetailPageResult("blank_page", "empty_capture")
    if lowered_url in {"about:blank", "data:,"} or (len(html.strip()) < 80 and not title):
        return DetailPageResult("blank_page", "blank_or_too_short")

    error_marker = next((marker for marker in ERROR_MARKERS if marker in lowered_html or marker in lowered_title or marker in lowered_url), "")
    if error_marker:
        return DetailPageResult("error_page", error_marker, {"error_marker": error_marker})

    parsed = urlparse(url)
    is_detail_url = any(marker in lowered_url for marker in DETAIL_PATH_MARKERS)
    is_search_listing = "search.html" in lowered_url or "/fahrzeuge/search" in lowered_url
    is_home_root = parsed.netloc == "home.mobile.de" and parsed.path.strip("/").count("/") <= 0
    title_looks_home = all(marker in lowered_title for marker in HOME_TITLE_MARKERS)

    soup = BeautifulSoup(html, "lxml")
    text = clean_text(soup.get_text(" ", strip=True))
    lowered_text = text.lower()
    has_detail_marker = any(marker in lowered_text for marker in DETAIL_CONTENT_MARKERS)
    brand, model = parse_vehicle_title(html)
    price = parse_vehicle_price(html)
    specs = parse_vehicle_specs(html)
    has_vehicle_identity = bool(brand or model) and not title_looks_home
    has_vehicle_data = bool(price or specs)

    if title_looks_home and not has_vehicle_identity and not has_detail_marker:
        return DetailPageResult("home_redirect", "home_title_without_vehicle_signals")
    if is_home_root and not has_vehicle_identity and not has_detail_marker:
        return DetailPageResult("home_redirect", "home_url_without_vehicle_signals")
    if is_search_listing and not is_detail_url:
        return DetailPageResult("listing_page", "search_listing_url")

    if is_detail_url and has_vehicle_identity and (has_vehicle_data or has_detail_marker):
        return DetailPageResult(
            "real_detail_page",
            "detail_url_with_vehicle_signals",
            {
                "brand": brand,
                "model": model,
                "price": price,
                "spec_count": len(specs),
                "has_detail_marker": has_detail_marker,
            },
        )
    if has_vehicle_identity and has_vehicle_data and has_detail_marker:
        return DetailPageResult(
            "real_detail_page",
            "vehicle_signals_without_detail_url",
            {
                "brand": brand,
                "model": model,
                "price": price,
                "spec_count": len(specs),
            },
        )
    if is_detail_url:
        return DetailPageResult(
            "unknown",
            "detail_url_without_enough_vehicle_signals",
            {"brand": brand, "model": model, "price": price, "spec_count": len(specs)},
        )
    return DetailPageResult("unknown", "no_known_detail_or_error_signals")
