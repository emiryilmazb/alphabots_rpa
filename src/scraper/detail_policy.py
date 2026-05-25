"""Vehicle detail-page fetch policy helpers."""

from __future__ import annotations

from typing import Any

from src.config import ScraperConfig

REQUIRED_LISTING_FIELDS = [
    "Markes",
    "Models",
    "Fahrzeugtyp",
    "Preis",
    "Kilometerstand",
    "Erstzulassung",
]

FINANCING_FIELDS = [
    "Finanzierung",
    "Financing",
    "Bank",
    "Darlehensvermittler",
    "Fahrzeugpreis",
    "Anzahlung",
    "Schlussrate",
    "Fester Sollzins p.a.",
    "Effektiver Jahreszins",
    "Gesamtzins",
    "Gesamtbetrag",
    "Laufzeit",
]


def should_fetch_vehicle_detail(
    config: ScraperConfig,
    vehicle_url: str,
    fallback: dict[str, Any] | None,
    *,
    temporarily_disabled: bool = False,
) -> bool:
    """Decide whether to request the detail page after listing-card parsing."""
    if temporarily_disabled or config.skip_vehicle_details:
        return False
    if not is_real_vehicle_detail_url(vehicle_url):
        return False
    if config.detail_policy == "never":
        return False
    if config.detail_policy == "always":
        return True

    fallback = fallback or {}
    if config.detail_policy == "financing-only":
        return not _has_any_value(fallback, FINANCING_FIELDS)
    if config.detail_policy == "missing-required":
        return not _has_all_values(fallback, REQUIRED_LISTING_FIELDS)
    return True


def is_real_vehicle_detail_url(url: str) -> bool:
    return "/fahrzeuge/details" in url or "/auto-inserat/" in url


def _has_all_values(record: dict[str, Any], fields: list[str]) -> bool:
    return all(_has_value(record.get(field, "")) for field in fields)


def _has_any_value(record: dict[str, Any], fields: list[str]) -> bool:
    return any(_has_value(record.get(field, "")) for field in fields)


def _has_value(value: Any) -> bool:
    return str(value).strip() not in {"", "None", "nan", "NaN", "<NA>"}
