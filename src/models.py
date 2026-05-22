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
]


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

    model_config = ConfigDict(populate_by_name=True)
