"""Tests for data cleaning functions."""

import pandas as pd
import pytest
from src.processing.cleaning import (
    _parse_price,
    _parse_kw,
    _parse_ps,
    _parse_percentage,
    _parse_registration_year,
    _parse_duration_months,
    _parse_registration_month,
    clean_dataframes,
)


class TestParsePrice:
    def test_german_format(self):
        assert _parse_price("48.450 €") == 48450.0
        assert _parse_price("2.618 € (Brutto)") == 2618.0
        assert _parse_price("4.284 €") == 4284.0

    def test_decimal_comma(self):
        assert _parse_price("1.413,72 €") == 1413.72

    def test_english_thousands_comma(self):
        assert _parse_price("€8,900 (Net)") == 8900.0

    def test_empty(self):
        assert _parse_price("") is None
        assert _parse_price("nan") is None


class TestParsePower:
    def test_kw(self):
        assert _parse_kw("150 kW (204 PS)") == 150.0
        assert _parse_kw("75 kW") == 75.0

    def test_ps(self):
        assert _parse_ps("150 kW (204 PS)") == 204.0
        assert _parse_ps("102 PS") == 102.0


class TestParsePercentage:
    def test_german(self):
        assert _parse_percentage("5,83%") == 5.83
        assert _parse_percentage("5,99%") == 5.99


class TestParseRegistrationYear:
    def test_formats(self):
        assert _parse_registration_year("03/2024") == 2024
        assert _parse_registration_year("06/2022") == 2022

    def test_empty(self):
        assert _parse_registration_year("") is None


class TestParseRegistrationMonth:
    def test_month_year_format(self):
        assert _parse_registration_month("03/2024") == 3


class TestParseDuration:
    def test_months(self):
        assert _parse_duration_months("60 Months") == 60
        assert _parse_duration_months("48 Monate") == 48


def test_clean_dataframes_adds_snake_case_numeric_aliases():
    _, cars = clean_dataframes(
        pd.DataFrame(),
        pd.DataFrame(
            [
                {
                    "Preis": "4.284 €",
                    "Kilometerstand": "381.753 km",
                    "Leistung": "75 kW (102 PS)",
                    "Hubraum": "1.496 cm³",
                    "Fester Sollzins p.a.": "5,83%",
                    "Effektiver Jahreszins": "5,99%",
                    "Gesamtzins": "1.413,72 €",
                    "Gesamtbetrag": "12.345,67 €",
                    "Laufzeit": "48 Monate",
                    "Erstzulassung": "03/2024",
                    "Finanzierung": "100 € mtl.",
                }
            ]
        ),
    )

    row = cars.iloc[0]
    assert row["price_eur"] == 4284.0
    assert row["mileage_km"] == 381753.0
    assert row["power_kw"] == 75.0
    assert row["power_ps"] == 102.0
    assert row["displacement_cc"] == 1496.0
    assert row["borrowing_rate_pct"] == 5.83
    assert row["annual_interest_pct"] == 5.99
    assert row["total_interest_eur"] == 1413.72
    assert row["duration_months"] == 48
    assert row["first_registration_month"] == 3
    assert row["first_registration_year"] == 2024
    assert row["Financing_Available"] == "Yes"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
