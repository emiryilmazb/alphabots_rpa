"""Tests for vendor location normalization."""

from __future__ import annotations

import json

from src.scraper.vendor_scraper import VendorScraper


def _next_script(payload: str) -> str:
    encoded = json.dumps([1, f"29:{payload}"])
    return f"<html><body><script>self.__next_f.push({encoded})</script></body></html>"


def test_vendor_bundesland_uses_actual_country_not_search_state():
    html = _next_script(
        json.dumps(
            [
                "$",
                "Header",
                None,
                {
                    "dealerData": {
                        "homepageUrl": "https://home.mobile.de/ITALIA-AUTO",
                        "name": "Italia Auto",
                        "location": {
                            "street": "Via Tonale 89",
                            "zipcode": "47922",
                            "city": "Rimini",
                            "country": "IT",
                        },
                    },
                },
            ]
        )
    )
    vendor = {
        "Händlername": "",
        "Standort": "",
        "PLZ": "",
        "Städte": "",
        "Bundesland": "Nordrhein-Westfalen",
        "Land": "",
        "Telephone Number": "",
        "2. Telephone Number": "",
        "MobilTelefon": "",
        "Fax Number": "",
        "Email ID": "",
        "Hauptseite": "",
        "Mobile.de_Links": "https://home.mobile.de/ITALIA-AUTO",
        "Anzahl der Fahrzeuge": None,
    }

    VendorScraper._apply_vendor_html(html, vendor)

    assert vendor["Land"] == "Italien"
    assert vendor["Bundesland"] == ""


def test_vendor_bundesland_maps_german_postcode_when_country_is_germany():
    html = _next_script(
        json.dumps(
            [
                "$",
                "Header",
                None,
                {
                    "dealerData": {
                        "homepageUrl": "https://home.mobile.de/KOELN-AUTO",
                        "name": "Köln Auto",
                        "location": {
                            "street": "Teststr. 1",
                            "zipcode": "50667",
                            "city": "Köln",
                            "country": "DE",
                        },
                    },
                },
            ]
        )
    )
    vendor = {
        "Händlername": "",
        "Standort": "",
        "PLZ": "",
        "Städte": "",
        "Bundesland": "",
        "Land": "",
        "Telephone Number": "",
        "2. Telephone Number": "",
        "MobilTelefon": "",
        "Fax Number": "",
        "Email ID": "",
        "Hauptseite": "",
        "Mobile.de_Links": "https://home.mobile.de/KOELN-AUTO",
        "Anzahl der Fahrzeuge": None,
    }

    VendorScraper._apply_vendor_html(html, vendor)

    assert vendor["Land"] == "Deutschland"
    assert vendor["Bundesland"] == "Nordrhein-Westfalen"
