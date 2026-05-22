"""Tests for mobile.de embedded payload parsers."""

import json

from src.scraper.parsers import (
    parse_vendor_next_data,
    parse_vendor_vehicle_count,
    parse_vehicle_listing_urls,
    parse_vehicle_listing_summaries,
    parse_vehicle_category_values,
    parse_vehicle_urls_from_next_data,
    extract_listing_attribute_fields,
    split_vehicle_title,
)


def _next_script(payload: str) -> str:
    encoded = json.dumps([1, f"29:{payload}"])
    return f"<html><body><script>self.__next_f.push({encoded})</script></body></html>"


def test_parse_vendor_next_data():
    html = _next_script(
        json.dumps(
            [
                "$",
                "Header",
                None,
                {
                    "dealerData": {
                        "customerId": "123",
                        "homepageUrl": "https://home.mobile.de/ABC-AUTO",
                        "name": "ABC Auto",
                        "location": {
                            "street": "Teststr. 1",
                            "zipcode": "50667",
                            "city": "Köln",
                            "country": "DE",
                        },
                        "email": "info@example.com",
                        "phoneNumbers": {
                            "phone": {
                                "internationalPrefix": "49",
                                "prefix": "0221",
                                "number": "123456",
                            }
                        },
                    },
                    "dealerHomepageData": {"userDefinedLink": "https://example.com"},
                },
            ]
        )
    )
    data = parse_vendor_next_data(html)
    assert data["name"] == "ABC Auto"
    assert data["city"] == "Köln"
    assert data["homepage"] == "https://example.com"
    assert data["Telephone Number"] == "+49 0221 123456"


def test_parse_vehicle_count_and_listing_url():
    html = _next_script(
        json.dumps(
            [
                "$",
                "ResultList",
                None,
                {
                    "numResultsTotal": 12,
                    "children": {"listingId": 442947522},
                },
            ]
        )
    )
    assert parse_vendor_vehicle_count(html) == 12
    assert parse_vehicle_listing_urls(html) == [
        "https://suchen.mobile.de/fahrzeuge/details.html?id=442947522"
    ]


def test_ignores_short_non_listing_ids():
    html = _next_script(
        json.dumps(
            {
                "id": 12100,
                "listingId": 455841337,
                "children": {"id": 19000},
            }
        )
    )
    assert parse_vehicle_urls_from_next_data(html) == [
        "https://suchen.mobile.de/fahrzeuge/details.html?id=455841337"
    ]


def test_listing_attribute_condition_not_vehicle_type():
    assert extract_listing_attribute_fields("Unfallfrei • EZ 05/2020") == {
        "Fahrzeugzustand": "Unfallfrei"
    }
    assert extract_listing_attribute_fields("Neuwagen • 100 km") == {
        "Fahrzeugzustand": "Neuwagen"
    }
    assert extract_listing_attribute_fields("EZ 02/2010 • 271.607 km") == {}
    assert extract_listing_attribute_fields("Refrigerator Box • EZ 03/2014") == {
        "Fahrzeugtyp": "Refrigerator Box"
    }


def test_split_vehicle_title_strips_new_badge():
    assert split_vehicle_title("NEUNissan Micra VISA") == ("Nissan", "Micra VISA")
    assert split_vehicle_title("NEU Volkswagen Golf") == ("Volkswagen", "Golf")


def test_parse_structured_listing_payload_with_financing():
    html = _next_script(
        json.dumps(
            {
                "searchResults": {
                    "numResultsTotal": 1,
                    "listings": [
                        {
                            "id": 455165432,
                            "vc": "Car",
                            "title": "Volkswagen Polo UNITED",
                            "category": "Kleinwagen",
                            "make": {"localized": "Volkswagen"},
                            "model": {"localized": "Polo"},
                            "attr": {
                                "fr": "06/2009",
                                "pw": "59 kW (80 PS)",
                                "ft": "Benzin",
                                "ml": "129.700 km",
                                "tr": "Schaltgetriebe",
                                "ecol": "Grau",
                                "door": "4/5",
                                "sc": "5",
                                "emc": "Euro4",
                            },
                            "hasDamage": False,
                            "readyToDrive": True,
                            "price": {"grs": {"localized": "3.490 €"}},
                            "financePlans": [
                                {
                                    "offer": {
                                        "bankName": "Santander Consumer Bank AG",
                                        "loanBroker": "Check24 GmbH",
                                        "localized": {
                                            "downPayment": "490 €",
                                            "creditTerm": "60",
                                            "yearlyMileage": "10.000",
                                            "interestRateNominal": "5,26%",
                                            "interestRateEffective": "5,39%",
                                            "monthlyInstallment": "41 €",
                                            "finalInstallment": "1.151,70 €",
                                            "totalInterest": "555,72 €",
                                            "totalAmount": "3.555,72 €",
                                        },
                                    }
                                }
                            ],
                        }
                    ],
                }
            }
        )
    )
    summaries = parse_vehicle_listing_summaries(html)
    vehicle = summaries["https://suchen.mobile.de/fahrzeuge/details.html?id=455165432"]
    assert vehicle["Markes"] == "Volkswagen"
    assert vehicle["Models"] == "Polo UNITED"
    assert vehicle["Fahrzeugtyp"] == "Kleinwagen"
    assert vehicle["Fahrzeugzustand"] == "Unfallfrei"
    assert vehicle["Bank"] == "Santander Consumer Bank AG"
    assert vehicle["Laufzeit"] == "60 Monate"


def test_parse_structured_semi_trailer_category():
    html = _next_script(
        json.dumps(
            {
                "searchResults": {
                    "numResultsTotal": 1,
                    "listings": [
                        {
                            "id": 442947522,
                            "vc": "SemiTrailer",
                            "title": "Andere Schröder CS18",
                            "category": "Wechselfahrgestell",
                            "make": {"localized": "Andere"},
                            "attr": {"fr": "05/1999", "c": "SwapChassisSemiTrailer"},
                            "p": "2.618 €",
                        }
                    ],
                },
                "values": ["SemiTrailer"],
            }
        )
    )
    summaries = parse_vehicle_listing_summaries(html)
    vehicle = summaries["https://suchen.mobile.de/fahrzeuge/details.html?id=442947522"]
    assert vehicle["Fahrzeugtyp"] == "Auflieger"
    assert vehicle["Fahrzeugtyp_Raw"] == "Wechselfahrgestell"
    assert parse_vehicle_category_values(html) == ["SemiTrailer"]
