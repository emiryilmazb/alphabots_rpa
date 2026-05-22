"""
Data cleaning module.

Normalizes raw scraped data into analysis-ready formats.
Cleans prices, mileage, CO₂, power, displacement, percentages, etc.
"""

from __future__ import annotations

import re
import logging
import unicodedata
import pandas as pd

from src.models import VENDOR_COLUMNS, VEHICLE_COLUMNS

logger = logging.getLogger("mobile_de.cleaning")


def clean_dataframes(df_vendors: pd.DataFrame,
                     df_cars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Clean and normalize both vendor and car DataFrames.

    Returns:
        Tuple of (cleaned_vendors, cleaned_cars)
    """
    logger.info("Cleaning vendor data (%d rows).", len(df_vendors))
    df_v = _clean_vendors(_ensure_columns(df_vendors.copy(), VENDOR_COLUMNS))

    logger.info("Cleaning vehicle data (%d rows).", len(df_cars))
    df_c = _clean_cars(_ensure_columns(df_cars.copy(), VEHICLE_COLUMNS))

    return df_v, df_c


def _clean_vendors(df: pd.DataFrame) -> pd.DataFrame:
    """Clean vendor DataFrame."""
    # Strip whitespace from all string columns
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].map(_normalize_string)

    if "Anzahl der Fahrzeuge" in df.columns:
        df["Anzahl der Fahrzeuge"] = pd.to_numeric(df["Anzahl der Fahrzeuge"], errors="coerce")

    return df


def _clean_cars(df: pd.DataFrame) -> pd.DataFrame:
    """Clean vehicle DataFrame with numeric conversions."""
    # Strip whitespace from all string columns
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].map(_normalize_string)

    # ── Price → numeric EUR ─────────────────────────────────────────────
    df["Preis_EUR"] = df["Preis"].apply(_parse_price)

    # ── Mileage → numeric km ────────────────────────────────────────────
    df["Kilometerstand_km"] = df["Kilometerstand"].apply(_parse_number)

    # ── CO₂ → numeric g/km ──────────────────────────────────────────────
    df["CO2_gkm"] = df["CO₂-Emissionen"].apply(_parse_number)

    # ── Power → kW and PS ───────────────────────────────────────────────
    df["Leistung_kW"] = df["Leistung"].apply(_parse_kw)
    df["Leistung_PS"] = df["Leistung"].apply(_parse_ps)

    # ── Displacement → numeric cm³ ──────────────────────────────────────
    df["Hubraum_ccm"] = df["Hubraum"].apply(_parse_number)

    # ── Seats → numeric ─────────────────────────────────────────────────
    df["Sitzplaetze_num"] = df["Anzahl Sitzplätze"].apply(_parse_int)

    # ── Doors → text kept, also extract first number ────────────────────
    df["Tueren_num"] = df["Anzahl der Türen"].apply(_parse_first_int)

    # ── Owners → numeric ────────────────────────────────────────────────
    df["Halter_num"] = df["Anzahl der Fahrzeughalter"].apply(_parse_int)

    # ── Registration year → numeric ─────────────────────────────────────
    df["EZ_Jahr"] = df["Erstzulassung"].apply(_parse_registration_year)

    # ── Financing amounts → numeric ─────────────────────────────────────
    df["Fahrzeugpreis_EUR"] = df["Fahrzeugpreis"].apply(_parse_price)
    df["Anzahlung_EUR"] = df["Anzahlung"].apply(_parse_price)
    df["Schlussrate_EUR"] = df["Schlussrate"].apply(_parse_price)
    df["Gesamtbetrag_EUR"] = df["Gesamtbetrag"].apply(_parse_price)
    df["Gesamtzins_EUR"] = df["Gesamtzins"].apply(_parse_price)

    # ── Interest rates → numeric ────────────────────────────────────────
    df["Sollzins_pct"] = df["Fester Sollzins p.a."].apply(_parse_percentage)
    df["EffJahreszins_pct"] = df["Effektiver Jahreszins"].apply(_parse_percentage)

    # ── Duration → numeric months ───────────────────────────────────────
    df["Laufzeit_Monate"] = df["Laufzeit"].apply(_parse_duration_months)

    # ── Derived metrics ─────────────────────────────────────────────────
    # Price per kW
    df["Preis_pro_kW"] = pd.to_numeric(df["Preis_EUR"], errors="coerce") / \
                          pd.to_numeric(df["Leistung_kW"], errors="coerce")

    # Price per km (for deal scoring)
    df["Preis_pro_km"] = pd.to_numeric(df["Preis_EUR"], errors="coerce") / \
                          (pd.to_numeric(df["Kilometerstand_km"], errors="coerce") + 1)

    return df


# ─── Parsing Helpers ──────────────────────────────────────────────────────────

def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Ensure required columns exist and appear first."""
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    remaining = [col for col in df.columns if col not in columns]
    return df[columns + remaining]


def _normalize_string(value) -> str:
    """Trim whitespace and normalize Unicode without transliterating umlauts."""
    if pd.isna(value):
        return ""
    text = str(value).replace("\xa0", " ")
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text in {"nan", "None", "NaN", "<NA>"} else text

def _parse_price(text: str) -> float | None:
    """
    Parse a German-formatted price string to a float.

    Examples:
        "48.450 €" → 48450.0
        "2.618 € (Brutto)" → 2618.0
        "4.284 €" → 4284.0
    """
    text = _normalize_string(text)
    if not text:
        return None
    match = re.search(
        r"(?:[€$]\s*)?(\d+(?:[.,]\d{3})*(?:[,.]\d{2})?|\d+(?:[,.]\d+)?)(?:\s*[€$])?",
        text,
    )
    if not match:
        return None
    text = match.group(1)
    text = re.sub(r"[^\d.,]", "", text).strip()
    if not text:
        return None
    # German format: 48.450,00 → periods are thousands sep, comma is decimal
    # If there's a comma, treat it as decimal separator
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        parts = text.split(",")
        if len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif "." in text:
        # Could be thousands separator (48.450) or decimal (48.45)
        # If there are 3 digits after the last dot, it's thousands
        parts = text.split(".")
        if len(parts[-1]) == 3:
            text = text.replace(".", "")
        # Otherwise leave as-is (it's a decimal)
    try:
        return float(text)
    except ValueError:
        return None


def _parse_number(text: str) -> float | None:
    """Parse a number from text, handling German formatting."""
    text = _normalize_string(text)
    if not text:
        return None
    # Extract numeric part
    m = re.search(r"([\d.,]+)", text)
    if not m:
        return None
    return _parse_price(m.group(1))


def _parse_int(text: str) -> int | None:
    """Parse an integer from text."""
    text = _normalize_string(text)
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def _parse_first_int(text: str) -> int | None:
    """Parse the first integer from text like '4/5' → 4."""
    text = _normalize_string(text)
    if not text:
        return None
    m = re.match(r"(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def _parse_kw(text: str) -> float | None:
    """Extract kW value from power string like '150 kW (204 PS)'."""
    text = _normalize_string(text)
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kW", text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _parse_ps(text: str) -> float | None:
    """Extract PS value from power string like '150 kW (204 PS)'."""
    text = _normalize_string(text)
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*PS", text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _parse_percentage(text: str) -> float | None:
    """Parse a percentage like '5,83%' → 5.83."""
    text = _normalize_string(text)
    if not text:
        return None
    m = re.search(r"([\d,.]+)\s*%", text)
    if m:
        return float(m.group(1).replace(".", "").replace(",", ".") if "," in m.group(1) else m.group(1))
    return None


def _parse_registration_year(text: str) -> int | None:
    """Extract year from registration date like '03/2024' → 2024."""
    text = _normalize_string(text)
    if not text:
        return None
    m = re.search(r"(\d{4})", text)
    if m:
        return int(m.group(1))
    return None


def _parse_duration_months(text: str) -> int | None:
    """Parse duration like '60 Months' or '60 Monate' → 60."""
    text = _normalize_string(text)
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    return None
