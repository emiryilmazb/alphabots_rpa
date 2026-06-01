import pytest
from src.scraper.parsers import _first_match

def test_fallback_field_regex():
    attrs = "756.000 km • 338 kW (460 PS) • Diesel • Automatik • Euro6 • Gebrauchtfahrzeug • 10/2016"
    
    km = _first_match(attrs, r"\b[\d.]+\s*km\b")
    zustand = _first_match(attrs, r"\b(?:Gebrauchtfahrzeug|Neufahrzeug|Jahreswagen|Vorführfahrzeug|Tageszulassung)\b")
    schadstoff = _first_match(attrs, r"\bEuro\s*\d[a-zA-Z]?\b")
    
    assert km == "756.000 km"
    assert zustand == "Gebrauchtfahrzeug"
    assert schadstoff == "Euro6"
