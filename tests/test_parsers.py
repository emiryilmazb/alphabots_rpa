"""Tests for mobile.de embedded payload parsers."""

import json

from src.scraper.parsers import (
    parse_vendor_next_data,
    parse_vendor_vehicle_count,
    parse_vehicle_listing_urls,
    parse_vehicle_listing_summaries,
    parse_vehicle_category_values,
    parse_vehicle_urls_from_next_data,
    parse_vehicle_specs,
    parse_vehicle_detail_fields,
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
    assert data["country"] == "Deutschland"


def test_parse_vendor_next_data_normalizes_foreign_country_without_default_region():
    html = _next_script(
        json.dumps(
            [
                "$",
                "Header",
                None,
                {
                    "dealerData": {
                        "customerId": "456",
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
    data = parse_vendor_next_data(html)
    assert data["country"] == "Italien"
    assert data["region"] == ""


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
                                "pvo": "2",
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
    assert vehicle["Anzahl der Fahrzeughalter"] == "2"
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


def test_parse_detail_label_value_targets_from_html_fixture():
    html = """
    <html><head><title>BMW 320 für 22.000 €</title></head><body>
      <h1>BMW 320 Touring</h1>
      <div data-testid="price-label">22.000 €</div>
      <h3>Technische Daten</h3>
      <dl>
        <dt>Baureihe</dt><dd>G21</dd>
        <dt>Ausstattungslinie</dt><dd>Luxury Line</dd>
        <dt>Anzahl der Fahrzeughalter</dt><dd>2</dd>
        <dt>Hubraum</dt><dd>1.995 cm³</dd>
        <dt>Anzahl der Türen</dt><dd>4/5</dd>
        <dt>Schadstoffklasse</dt><dd>Euro6d</dd>
        <dt>Farbe</dt><dd>Blau Metallic</dd>
        <dt>Anzahl Sitzplätze</dt><dd>5</dd>
        <dt>CO2-Emissionen</dt><dd>124 g/km</dd>
      </dl>
    </body></html>
    """

    specs = parse_vehicle_specs(html)
    assert specs["CO₂-Emissionen"] == "124 g/km"
    assert specs["Baureihe"] == "G21"
    assert specs["Ausstattungslinie"] == "Luxury Line"
    assert specs["Anzahl der Fahrzeughalter"] == "2"
    assert specs["Hubraum"] == "1.995 cm³"
    assert specs["Anzahl der Türen"] == "4/5"
    assert specs["Schadstoffklasse"] == "Euro6d"
    assert specs["Farbe"] == "Blau Metallic"
    assert specs["Anzahl Sitzplätze"] == "5"

    fields = parse_vehicle_detail_fields(html)
    assert fields["Markes"] == "BMW"
    assert fields["Models"] == "320 Touring"
    assert fields["CO₂-Emissionen"] == "124 g/km"


def test_parse_detail_description_trim_line_without_section_header_noise():
    html = """
    <html><body>
      <h1>Mercedes-Benz S 350</h1>
      <div data-testid="price-label">85.890 €</div>
      <h3>Technische Daten</h3>
      <dl><dt>Baureihe</dt><dd>223</dd></dl>
      <b>Ausstattungslinien und -Pakete</b>
      <ul>
        <li>Design- und Ausstattungslinie Standard</li>
        <li>P20 Fahrassistenz-Paket</li>
      </ul>
    </body></html>
    """

    assert parse_vehicle_specs(html)["Ausstattungslinie"] == "Standard"
