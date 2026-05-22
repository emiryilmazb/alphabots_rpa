"""Tests for vehicle classification logic."""
import pytest
from src.processing.classification import classify_vehicle_type, classify_origin


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

    def test_japan(self):
        assert classify_origin("Toyota") == "Japan"
        assert classify_origin("Honda") == "Japan"
        assert classify_origin("Mazda") == "Japan"

    def test_frankreich(self):
        assert classify_origin("Peugeot") == "Frankreich"
        assert classify_origin("Renault") == "Frankreich"
        assert classify_origin("Citroën") == "Frankreich"
        assert classify_origin("Dacia") == "Frankreich"

    def test_andere(self):
        assert classify_origin("") == "Other/Unknown"
        assert classify_origin("Tesla") == "Other/Unknown"
        assert classify_origin(None) == "Other/Unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
