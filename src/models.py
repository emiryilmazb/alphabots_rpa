"""Structured models and canonical output columns."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


VENDOR_COLUMNS = [
    "Händler ID",
    "Händlername",
    "Standort",
    "PLZ",
    "Städte",
    "Bundesland",
    "Land",
    "Telephone Number",
    "2. Telephone Number",
    "MobilTelefon",
    "Fax Number",
    "Email ID",
    "Hauptseite",
    "Mobile.de_Links",
    "Anzahl der Fahrzeuge",
]


VEHICLE_COLUMNS = [
    "Händler ID",
    "Händlername",
    "PLZ",
    "Markes",
    "Models",
    "Fahrzeugtyp",
    "Fahrzeugzustand",
    "Erstzulassung",
    "Kilometerstand",
    "Kraftstoffart",
    "CO₂-Emissionen",
    "Preis",
    "Leistung",
    "Anzahl Sitzplätze",
    "Getriebe",
    "Schadstoffklasse",
    "Farbe",
    "Baureihe",
    "Ausstattungslinie",
    "Hubraum",
    "Anzahl der Türen",
    "Anzahl der Fahrzeughalter",
    "Finanzierung",
    "Financing",
    "Bank",
    "Darlehensvermittler",
    "Fahrzeugpreis",
    "Anzahlung",
    "Jährliche Kilometerleistung",
    "Schlussrate",
    "Fester Sollzins p.a.",
    "Effektiver Jahreszins",
    "Gesamtzins",
    "Gesamtbetrag",
    "Laufzeit",
    "Vehicle_URL",
    "source_vendor_url",
    "source_vehicle_url",
    "source_category",
    "source_category_label",
    "source_category_count",
    "source_category_url",
    "fetch_strategy",
    "fetch_status",
    "parse_status",
    "vehicle_data_source",
    "detail_data_source",
    "detail_strategy_used",
    "detail_status",
    "detail_failure_reason",
    "detail_target_fields_extracted_count",
    "detail_fields_filled",
    "detail_artifact_html_path",
    "detail_artifact_screenshot_path",
    "scraped_at",
    "run_id",
]


VEHICLE_REQUIRED_FIELDS = [
    "Händler ID",
    "Händlername",
    "PLZ",
    "Markes",
    "Models",
    "Fahrzeugtyp",
    "Fahrzeugzustand",
    "Erstzulassung",
    "Kilometerstand",
    "Kraftstoffart",
    "CO₂-Emissionen",
    "Preis",
    "Leistung",
    "Anzahl Sitzplätze",
    "Getriebe",
    "Schadstoffklasse",
    "Farbe",
    "Baureihe",
    "Ausstattungslinie",
    "Hubraum",
    "Anzahl der Türen",
    "Anzahl der Fahrzeughalter",
]


VEHICLE_BASIC_FIELDS = [
    "Händler ID",
    "Händlername",
    "PLZ",
    "Markes",
    "Models",
    "Fahrzeugtyp",
    "Fahrzeugzustand",
    "Erstzulassung",
    "Kilometerstand",
    "Kraftstoffart",
    "Preis",
    "Leistung",
]


VEHICLE_TECHNICAL_FIELDS = [
    "CO₂-Emissionen",
    "Anzahl Sitzplätze",
    "Getriebe",
    "Schadstoffklasse",
    "Farbe",
    "Baureihe",
    "Ausstattungslinie",
    "Hubraum",
    "Anzahl der Türen",
    "Anzahl der Fahrzeughalter",
]


FINANCING_REQUIRED_FIELDS = [
    "Finanzierung",
    "Bank",
    "Darlehensvermittler",
    "Fahrzeugpreis",
    "Anzahlung",
    "Jährliche Kilometerleistung",
    "Schlussrate",
    "Fester Sollzins p.a.",
    "Effektiver Jahreszins",
    "Gesamtzins",
    "Gesamtbetrag",
    "Laufzeit",
]


CLASSIFICATION_REQUIRED_FIELDS = [
    "vehicle_category",
    "manufacturer_origin",
]


LOW_SOURCE_COVERAGE_FIELDS = {
    "CO₂-Emissionen",
    "Baureihe",
    "Ausstattungslinie",
    "Anzahl der Fahrzeughalter",
}


SOURCE_METADATA_COLUMNS = [
    "source_vendor_url",
    "source_vehicle_url",
    "source_category",
    "source_category_label",
    "source_category_count",
    "source_category_url",
    "fetch_strategy",
    "fetch_status",
    "parse_status",
    "vehicle_data_source",
    "detail_data_source",
    "detail_strategy_used",
    "detail_status",
    "detail_failure_reason",
    "detail_target_fields_extracted_count",
    "detail_fields_filled",
    "detail_artifact_html_path",
    "detail_artifact_screenshot_path",
    "scraped_at",
    "run_id",
]


def validate_required_columns(df, expected_columns: list[str]) -> list[str]:
    """Return required columns that are missing from a DataFrame-like object."""
    columns = set(getattr(df, "columns", []))
    return [column for column in expected_columns if column not in columns]


class VendorData(BaseModel):
    """Represents a single car dealer / vendor on mobile.de."""

    haendler_id: str = Field("", alias="Händler ID")
    haendlername: str = Field("", alias="Händlername")
    standort: str = Field("", alias="Standort")
    plz: str = Field("", alias="PLZ")
    staedte: str = Field("", alias="Städte")
    bundesland: str = Field("", alias="Bundesland")
    land: str = Field("Deutschland", alias="Land")
    telephone_number: str = Field("", alias="Telephone Number")
    telephone_number_2: str = Field("", alias="2. Telephone Number")
    mobil_telefon: str = Field("", alias="MobilTelefon")
    fax_number: str = Field("", alias="Fax Number")
    email_id: str = Field("", alias="Email ID")
    hauptseite: str = Field("", alias="Hauptseite")
    mobile_de_links: str = Field("", alias="Mobile.de_Links")
    anzahl_der_fahrzeuge: int | None = Field(None, alias="Anzahl der Fahrzeuge")

    model_config = ConfigDict(populate_by_name=True)


class FinancingData(BaseModel):
    """Financing details for a vehicle listing."""

    financing: str = Field("", alias="Financing")
    bank: str = Field("", alias="Bank")
    darlehensvermittler: str = Field("", alias="Darlehensvermittler")
    fahrzeugpreis: str = Field("", alias="Fahrzeugpreis")
    anzahlung: str = Field("", alias="Anzahlung")
    jaehrliche_kilometerleistung: str = Field("", alias="Jährliche Kilometerleistung")
    schlussrate: str = Field("", alias="Schlussrate")
    fester_sollzins: str = Field("", alias="Fester Sollzins p.a.")
    effektiver_jahreszins: str = Field("", alias="Effektiver Jahreszins")
    gesamtzins: str = Field("", alias="Gesamtzins")
    gesamtbetrag: str = Field("", alias="Gesamtbetrag")
    laufzeit: str = Field("", alias="Laufzeit")

    model_config = ConfigDict(populate_by_name=True)


class VehicleData(BaseModel):
    """Represents a single vehicle listing on mobile.de."""

    haendler_id: str = Field("", alias="Händler ID")
    haendlername: str = Field("", alias="Händlername")
    plz: str = Field("", alias="PLZ")
    markes: str = Field("", alias="Markes")
    models: str = Field("", alias="Models")
    fahrzeugtyp: str = Field("", alias="Fahrzeugtyp")
    fahrzeugzustand: str = Field("", alias="Fahrzeugzustand")
    erstzulassung: str = Field("", alias="Erstzulassung")
    kilometerstand: str = Field("", alias="Kilometerstand")
    kraftstoffart: str = Field("", alias="Kraftstoffart")
    co2_emissionen: str = Field("", alias="CO₂-Emissionen")
    preis: str = Field("", alias="Preis")
    leistung: str = Field("", alias="Leistung")
    anzahl_sitzplaetze: str = Field("", alias="Anzahl Sitzplätze")
    getriebe: str = Field("", alias="Getriebe")
    schadstoffklasse: str = Field("", alias="Schadstoffklasse")
    farbe: str = Field("", alias="Farbe")
    baureihe: str = Field("", alias="Baureihe")
    ausstattungslinie: str = Field("", alias="Ausstattungslinie")
    hubraum: str = Field("", alias="Hubraum")
    anzahl_der_tueren: str = Field("", alias="Anzahl der Türen")
    anzahl_der_fahrzeughalter: str = Field("", alias="Anzahl der Fahrzeughalter")

    # Financing fields (flattened)
    finanzierung: str = Field("", alias="Finanzierung")
    financing: str = Field("", alias="Financing")
    bank: str = Field("", alias="Bank")
    darlehensvermittler: str = Field("", alias="Darlehensvermittler")
    fahrzeugpreis: str = Field("", alias="Fahrzeugpreis")
    anzahlung: str = Field("", alias="Anzahlung")
    jaehrliche_kilometerleistung: str = Field("", alias="Jährliche Kilometerleistung")
    schlussrate: str = Field("", alias="Schlussrate")
    fester_sollzins: str = Field("", alias="Fester Sollzins p.a.")
    effektiver_jahreszins: str = Field("", alias="Effektiver Jahreszins")
    gesamtzins: str = Field("", alias="Gesamtzins")
    gesamtbetrag: str = Field("", alias="Gesamtbetrag")
    laufzeit: str = Field("", alias="Laufzeit")

    # Internal tracking
    vehicle_url: str = Field("", alias="Vehicle_URL")
    source_vendor_url: str = Field("", alias="source_vendor_url")
    source_vehicle_url: str = Field("", alias="source_vehicle_url")
    source_category: str = Field("", alias="source_category")
    source_category_label: str = Field("", alias="source_category_label")
    source_category_count: str = Field("", alias="source_category_count")
    source_category_url: str = Field("", alias="source_category_url")
    fetch_strategy: str = Field("", alias="fetch_strategy")
    fetch_status: str = Field("", alias="fetch_status")
    parse_status: str = Field("", alias="parse_status")
    vehicle_data_source: str = Field("", alias="vehicle_data_source")
    detail_data_source: str = Field("", alias="detail_data_source")
    detail_strategy_used: str = Field("", alias="detail_strategy_used")
    detail_status: str = Field("", alias="detail_status")
    detail_failure_reason: str = Field("", alias="detail_failure_reason")
    detail_target_fields_extracted_count: str = Field("", alias="detail_target_fields_extracted_count")
    detail_fields_filled: str = Field("", alias="detail_fields_filled")
    detail_artifact_html_path: str = Field("", alias="detail_artifact_html_path")
    detail_artifact_screenshot_path: str = Field("", alias="detail_artifact_screenshot_path")
    scraped_at: str = Field("", alias="scraped_at")
    run_id: str = Field("", alias="run_id")

    model_config = ConfigDict(populate_by_name=True)
