"""Tests for vehicle classification logic."""

import pytest
import pandas as pd

from src.processing.classification import (
    classify_dataframe,
    classify_origin,
    classify_origin_details,
    classify_vehicle_type,
    classify_vehicle_type_details,
)


class TestVehicleTypeClassification:
    def test_pkw_types(self):
        assert classify_vehicle_type("Limousine") == "PKW"
        assert classify_vehicle_type("SUV/Geländewagen/Pickup") == "PKW"
        assert classify_vehicle_type("Van/Kleinbus") == "PKW"
        assert classify_vehicle_type("Kombi") == "PKW"
        assert classify_vehicle_type("Cabrio/Roadster") == "PKW"

    def test_motorrad_types(self):
        assert classify_vehicle_type("Motorrad") == "Motorrad"
        assert classify_vehicle_type("Chopper/Cruiser") == "Motorrad"
        assert classify_vehicle_type("Roller/Scooter") == "Motorrad"
        assert classify_vehicle_type("Quad") == "Motorrad"

    def test_freizeit_types(self):
        assert classify_vehicle_type("Wohnwagen") == "Freizeitfahrzeuge"
        assert classify_vehicle_type("Kastenwagen") == "Freizeitfahrzeuge"
        assert classify_vehicle_type("Alkoven") == "Freizeitfahrzeuge"

    def test_lkw_types(self):
        assert classify_vehicle_type("Auflieger") == "LKW"
        assert classify_vehicle_type("Busse") == "LKW"
        assert classify_vehicle_type("Stapler") == "LKW"
        assert classify_vehicle_type("Anhänger") == "LKW"
        assert classify_vehicle_type("Sattelzugmaschinen") == "LKW"
        assert classify_vehicle_type("Transporter und Lkw bis 7,5 t") == "LKW"

    def test_andere(self):
        assert classify_vehicle_type("") == "Andere"
        assert classify_vehicle_type("SomethingUnknown") == "Andere"
        assert classify_vehicle_type(None) == "Andere"


class TestOriginClassification:
    def test_deutschland(self):
        assert classify_origin("Volkswagen") == "Deutschland"
        assert classify_origin("BMW") == "Deutschland"
        assert classify_origin("Mercedes-Benz") == "Deutschland"
        assert classify_origin("Audi") == "Deutschland"
        assert classify_origin("Opel") == "Deutschland"

    def test_italien(self):
        assert classify_origin("Fiat") == "Italien"
        assert classify_origin("Alfa Romeo") == "Italien"

    def test_korea(self):
        assert classify_origin("Hyundai") == "Korea"
        assert classify_origin("Kia") == "Korea"
        assert classify_origin("KGM") == "Korea"

    def test_japan(self):
        assert classify_origin("Toyota") == "Japan"
        assert classify_origin("Honda") == "Japan"
        assert classify_origin("Mazda") == "Japan"

    def test_frankreich(self):
        assert classify_origin("Peugeot") == "Frankreich"
        assert classify_origin("Renault") == "Frankreich"
        assert classify_origin("Citroën") == "Frankreich"
        assert classify_origin("Dacia") == "Frankreich"
        assert classify_origin("DS Automobiles") == "Frankreich"

    def test_andere(self):
        assert classify_origin("") == "Andere"
        assert classify_origin("Tesla") == "Andere"
        assert classify_origin(None) == "Andere"

    def test_additional_task_aliases(self):
        assert classify_origin("Ford") == "Deutschland"
        assert classify_origin("Volvo") == "Deutschland"
        assert classify_origin("Lexus") == "Japan"


def test_classification_metadata_helpers():
    assert classify_vehicle_type_details("Kleinwagen") == (
        "PKW",
        "Kleinwagen",
        1.0,
        "exact_task_match",
    )
    assert classify_origin_details("KGM") == ("Korea", "KGM", 1.0, "exact_task_match")


def test_source_category_metadata_and_kastenwagen_override():
    category, normalized, confidence, rule = classify_vehicle_type_details(
        "Kastenwagen", "VanUpTo7500"
    )
    assert category == "LKW"
    assert normalized == "Kastenwagen"
    assert confidence == 0.95
    assert rule == "source_category_override"

    category, _, _, rule = classify_vehicle_type_details("", "ForkliftTruck")
    assert category == "LKW"
    assert rule == "source_category_match"


def test_classify_dataframe_keeps_aliases_and_metadata():
    df = pd.DataFrame(
        [
            {"Fahrzeugtyp": "Kastenwagen", "Markes": "DS Automobiles"},
            {"Fahrzeugtyp": "SomethingUnknown", "Markes": "Unknown Brand"},
        ]
    )
    result = classify_dataframe(df)

    assert result.loc[0, "Fahrzeug_Klasse"] == "Freizeitfahrzeuge"
    assert result.loc[0, "vehicle_category"] == "Freizeitfahrzeuge"
    assert result.loc[0, "Herkunftsland"] == "Frankreich"
    assert result.loc[0, "manufacturer_origin"] == "Frankreich"
    assert result.loc[0, "manufacturer_origin_rule"] == "exact_task_match"
    assert result.loc[1, "vehicle_category"] == "Andere"
    assert result.loc[1, "manufacturer_origin"] == "Andere"
    assert result.loc[1, "vehicle_category_rule"] == "unknown_to_andere"
    assert "source_category" in result.columns
    assert "source_category_label" in result.columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
