from __future__ import annotations
import logging
import re
from bs4 import BeautifulSoup
from src.scraper.parser_modules.normalization import clean_text

logger = logging.getLogger(__name__)


def parse_financing_data(html: str) -> dict[str, str]:
    """Extract financing information where available."""
    soup = BeautifulSoup(html, "lxml")
    financing: dict[str, str] = {}
    labels = {
        "Bank": "Bank",
        "Darlehensvermittler": "Darlehensvermittler",
        "Fahrzeugpreis": "Fahrzeugpreis",
        "Anzahlung": "Anzahlung",
        "Jährliche Kilometerleistung": "Jährliche Kilometerleistung",
        "Schlussrate": "Schlussrate",
        "Fester Sollzins p.a.": "Fester Sollzins p.a.",
        "Sollzins": "Fester Sollzins p.a.",
        "Effektiver Jahreszins": "Effektiver Jahreszins",
        "Gesamtzins": "Gesamtzins",
        "Gesamtbetrag": "Gesamtbetrag",
        "Laufzeit": "Laufzeit",
        "Nettodarlehensbetrag": "Fahrzeugpreis",
        "Monatsrate": "Financing",
    }

    _extract_financing_pairs(soup, labels, financing)
    text = clean_text(soup.get_text(" ", strip=True))
    for label, key in labels.items():
        if key in financing:
            continue
        match = re.search(
            rf"(?:^|\s){re.escape(label)}\s*[:]\s*([^|•]{{1,80}})", text, re.I
        )
        if match:
            financing[key] = clean_text(match.group(1))

    if "Financing" not in financing:
        match = re.search(
            r"(?:Finanzierung|Rate)\s*(?:ab)?\s*(\d[\d.,]*\s*€\s*(?:mtl\.?|monatlich)?)",
            text,
            re.I,
        )
        if match:
            financing["Financing"] = clean_text(match.group(1))
    return financing


def _extract_financing_pairs(
    soup: BeautifulSoup, labels: dict[str, str], financing: dict[str, str]
) -> None:
    lower = {label.lower(): key for label, key in labels.items()}
    for dt in soup.find_all("dt"):
        label = clean_text(dt.get_text(" ", strip=True)).rstrip(":")
        key = lower.get(label.lower())
        if not key:
            continue
        dd = dt.find_next_sibling("dd")
        value = clean_text(dd.get_text(" ", strip=True)) if dd else ""
        if value:
            financing[key] = value

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = clean_text(cells[0].get_text(" ", strip=True)).rstrip(":")
        key = lower.get(label.lower())
        value = clean_text(cells[1].get_text(" ", strip=True))
        if key and value:
            financing[key] = value
