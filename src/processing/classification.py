"""
Vehicle classification module.

Classifies vehicles by:
1. Vehicle type → PKW, Motorrad, Freizeitfahrzeuge, LKW, Andere
2. Manufacturer origin → Deutschland, Italien, Korea, Japan, Frankreich, Andere

Manufacturer grouping follows the task-defined categories, not historical
or legal corporate-origin definitions.
"""

from __future__ import annotations
import logging
import pandas as pd

logger = logging.getLogger("mobile_de.classification")

# ─── Vehicle Type Mapping ─────────────────────────────────────────────────────
_TYPE_LISTS: dict[str, list[str]] = {
    "PKW": [
        "PKW",
        "Pkw",
        "Car",
        "Cabrio/Roadster",
        "Kleinwagen",
        "Kombi",
        "Limousine",
        "Sportwagen/Coupé",
        "SUV/Geländewagen/Pickup",
        "SUV/Off-road Vehicle/Pickup Truck",
        "Van/Kleinbus",
        "Van/Minibus",
    ],
    "Motorrad": [
        "Chopper/Cruiser",
        "Mofa/Mokick/Moped",
        "Rallye/Cross",
        "Streetfighter",
        "Dirt Bike",
        "Motorrad",
        "Rennsport",
        "Super Moto",
        "Enduro/Reiseenduro",
        "Naked Bike",
        "Roller/Scooter",
        "Tourer",
        "Gespann/Seitenwagen",
        "Pocket Bike",
        "Sportler/Supersportler",
        "Trike",
        "Klein/Leichtkraftrad",
        "Quad",
        "Sporttourer",
    ],
    "Freizeitfahrzeuge": [
        "Alkoven",
        "Mobilheim",
        "Wohnmobil andere",
        "Integrierter",
        "Teilintegrierter",
        "Wohnmobil Pickup",
        "Kastenwagen",
        "Wohnkabine",
        "Wohnwagen",
    ],
    "LKW": [
        "Transporter und Lkw bis 7,5 t",
        "Lkw ab 7,5 t",
        "Sattelzugmaschinen",
        "Anhänger",
        "Auflieger",
        "Baumaschinen",
        "Busse",
        "Agrarfahrzeuge",
        "Stapler",
    ],
}

VEHICLE_TYPE_MAP: dict[str, str] = {}
for _cat, _types in _TYPE_LISTS.items():
    for _t in _types:
        VEHICLE_TYPE_MAP[_t.lower()] = _cat

# ─── Manufacturer Origin Mapping ─────────────────────────────────────────────
# Grouping follows the task specification.  Ford and Volvo are listed under
# Deutschland in the task description.
_ORIGIN_LISTS: dict[str, list[str]] = {
    "Deutschland": [
        "Audi",
        "Volkswagen",
        "VW",
        "Skoda",
        "Škoda",
        "Seat",
        "SEAT",
        "Smart",
        "BMW",
        "Cupra",
        "Mini",
        "MINI",
        "Mercedes-Benz",
        "Mercedes",
        "Porsche",
        "Volvo",
        "Opel",
        "Ford",
    ],
    "Italien": [
        "Alfa Romeo",
        "Lancia",
        "Fiat",
        "Abarth",
        "Maserati",
        "Ferrari",
        "Lamborghini",
    ],
    "Korea": [
        "Hyundai",
        "SsangYong",
        "KGM",
        "Kia",
        "Genesis",
        "Daewoo",
    ],
    "Japan": [
        "Toyota",
        "Honda",
        "Nissan",
        "Mazda",
        "Mitsubishi",
        "Suzuki",
        "Subaru",
        "Daihatsu",
        "Lexus",
        "Infiniti",
        "Isuzu",
    ],
    "Frankreich": [
        "Peugeot",
        "Renault",
        "Citroën",
        "Citroen",
        "Dacia",
        "DS Automobiles",
        "DS",
        "Alpine",
    ],
}

ORIGIN_MAP: dict[str, str] = {}
for _origin, _brands in _ORIGIN_LISTS.items():
    for _b in _brands:
        ORIGIN_MAP[_b.lower()] = _origin


SOURCE_CATEGORY_MAP = {
    "car": "PKW",
    "motorbike": "Motorrad",
    "motorhome": "Freizeitfahrzeuge",
    "vanupto7500": "LKW",
    "truckover7500": "LKW",
    "semitrailertruck": "LKW",
    "semitrailer": "LKW",
    "trailer": "LKW",
    "constructionmachine": "LKW",
    "bus": "LKW",
    "agriculturalvehicle": "LKW",
    "forklifttruck": "LKW",
}


def classify_vehicle_type(fahrzeugtyp: str) -> str:
    """Classify a raw Fahrzeugtyp string into a task category."""
    return classify_vehicle_type_details(fahrzeugtyp)[0]


def classify_vehicle_type_details(
    fahrzeugtyp: str,
    source_category: str | None = None,
) -> tuple[str, str, float, str]:
    """Return (category, normalized_value, confidence, rule)."""
    normalized = _normalize_value(fahrzeugtyp)
    source_key = _normalize_value(source_category).lower()
    key = normalized.lower()

    if (
        key == "kastenwagen"
        and source_key in SOURCE_CATEGORY_MAP
        and SOURCE_CATEGORY_MAP[source_key] == "LKW"
    ):
        return "LKW", normalized, 0.95, "source_category_override"

    if not key:
        if source_key in SOURCE_CATEGORY_MAP:
            return (
                SOURCE_CATEGORY_MAP[source_key],
                normalized,
                0.90,
                "source_category_match",
            )
        return "Andere", normalized, 0.0, "unknown_to_andere"

    if key in VEHICLE_TYPE_MAP:
        return VEHICLE_TYPE_MAP[key], normalized, 1.0, "exact_task_match"

    if source_key in SOURCE_CATEGORY_MAP:
        return (
            SOURCE_CATEGORY_MAP[source_key],
            normalized,
            0.90,
            "source_category_match",
        )

    for pattern, category in VEHICLE_TYPE_MAP.items():
        if pattern in key or key in pattern:
            return category, normalized, 0.70, "keyword_fallback"
    return "Andere", normalized, 0.0, "unknown_to_andere"


def classify_origin(marke: str) -> str:
    """Classify a manufacturer name into a task-defined origin country."""
    return classify_origin_details(marke)[0]


def classify_origin_details(marke: str) -> tuple[str, str, float, str]:
    """Return (origin, normalized_value, confidence, rule)."""
    normalized = _normalize_value(marke)
    key = normalized.lower()
    if not key:
        return "Andere", normalized, 0.0, "unknown_to_andere"
    if key in ORIGIN_MAP:
        return ORIGIN_MAP[key], normalized, 1.0, "exact_task_match"
    for brand, origin in ORIGIN_MAP.items():
        if brand in key or key in brand:
            return origin, normalized, 0.85, "alias_match"
    return "Andere", normalized, 0.0, "unknown_to_andere"


def _normalize_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"", "nan", "None", "NaN", "<NA>"} else text


def classify_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Add classification columns to a vehicle DataFrame.

    Produces both the legacy columns (Fahrzeug_Klasse, Herkunftsland) and
    new metadata columns (vehicle_category, vehicle_category_rule, etc.).
    """
    logger.info("Classifying %d vehicles.", len(df))

    if df.empty:
        for col in [
            "source_category",
            "source_category_label",
            "source_category_url",
            "raw_vehicle_type",
            "normalized_vehicle_type",
            "vehicle_category",
            "vehicle_category_confidence",
            "vehicle_category_rule",
            "Fahrzeug_Klasse",
            "raw_manufacturer",
            "normalized_manufacturer",
            "manufacturer_origin",
            "manufacturer_origin_confidence",
            "manufacturer_origin_rule",
            "Herkunftsland",
        ]:
            df[col] = pd.Series(dtype="object")
        return df

    if "Fahrzeugtyp" not in df.columns:
        df["Fahrzeugtyp"] = ""
    if "Markes" not in df.columns:
        df["Markes"] = ""

    source_categories = _source_category_series(df)
    if "source_category" not in df.columns:
        df["source_category"] = source_categories
    else:
        df["source_category"] = df["source_category"].where(
            df["source_category"].astype(str).str.strip() != "",
            source_categories,
        )
    if "source_category_label" not in df.columns:
        df["source_category_label"] = df.get(
            "Vehicle_Category_Label", pd.Series("", index=df.index)
        )
    if "source_category_url" not in df.columns:
        df["source_category_url"] = df.get(
            "Vehicle_Category_URL", pd.Series("", index=df.index)
        )

    type_results = [
        classify_vehicle_type_details(fahrzeugtyp, source_category)
        for fahrzeugtyp, source_category in zip(
            df["Fahrzeugtyp"], source_categories, strict=False
        )
    ]
    df["raw_vehicle_type"] = df["Fahrzeugtyp"]
    df["normalized_vehicle_type"] = [result[1] for result in type_results]
    df["vehicle_category"] = [result[0] for result in type_results]
    df["vehicle_category_confidence"] = [result[2] for result in type_results]
    df["vehicle_category_rule"] = [result[3] for result in type_results]
    df["Fahrzeug_Klasse"] = df["vehicle_category"]

    origin_results = [classify_origin_details(marke) for marke in df["Markes"]]
    df["raw_manufacturer"] = df["Markes"]
    df["normalized_manufacturer"] = [result[1] for result in origin_results]
    df["manufacturer_origin"] = [result[0] for result in origin_results]
    df["manufacturer_origin_confidence"] = [result[2] for result in origin_results]
    df["manufacturer_origin_rule"] = [result[3] for result in origin_results]
    df["Herkunftsland"] = df["manufacturer_origin"]

    logger.info(
        "Vehicle class distribution:\n%s",
        df["Fahrzeug_Klasse"].value_counts().to_string(),
    )
    logger.info(
        "Origin distribution:\n%s",
        df["Herkunftsland"].value_counts().to_string(),
    )
    return df


def _source_category_series(df: pd.DataFrame) -> pd.Series:
    if "source_category" in df.columns:
        base = df["source_category"].copy()
    else:
        base = pd.Series("", index=df.index)
    for column in [
        "Vehicle_Category",
        "source_category_label",
        "Vehicle_Category_Label",
    ]:
        if column in df.columns:
            base = base.where(base.astype(str).str.strip() != "", df[column])
    return base
