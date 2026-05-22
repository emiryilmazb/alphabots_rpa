"""
Vehicle classification module.

Classifies vehicles by:
1. Vehicle type → PKW, Motorrad, Freizeitfahrzeuge, LKW, Andere
2. Manufacturer origin → Deutschland, Italien, Korea, Japan, Frankreich, Other/Unknown
"""
from __future__ import annotations
import logging
import pandas as pd

logger = logging.getLogger("mobile_de.classification")

# ─── Vehicle Type Mapping ─────────────────────────────────────────────────────
_TYPE_LISTS = {
    "PKW": ["PKW","Pkw","Car","Cabrio/Roadster","Kleinwagen","Kombi","Limousine","Sportwagen/Coupé",
            "SUV/Geländewagen/Pickup","SUV/Off-road Vehicle/Pickup Truck",
            "Van/Kleinbus","Van/Minibus"],
    "Motorrad": ["Chopper/Cruiser","Mofa/Mokick/Moped","Rallye/Cross","Streetfighter",
                 "Dirt Bike","Motorrad","Rennsport","Super Moto","Enduro/Reiseenduro",
                 "Naked Bike","Roller/Scooter","Tourer","Gespann/Seitenwagen",
                 "Pocket Bike","Sportler/Supersportler","Trike",
                 "Klein/Leichtkraftrad","Quad","Sporttourer"],
    "Freizeitfahrzeuge": ["Alkoven","Mobilheim","Wohnmobil andere","Integrierter",
                          "Teilintegrierter","Wohnmobil Pickup","Kastenwagen",
                          "Wohnkabine","Wohnwagen"],
    "LKW": ["Transporter und Lkw bis 7,5 t","Lkw ab 7,5 t","Sattelzugmaschinen",
            "Anhänger","Auflieger","Baumaschinen","Busse","Agrarfahrzeuge","Stapler"],
}
VEHICLE_TYPE_MAP: dict[str,str] = {}
for cat, types in _TYPE_LISTS.items():
    for t in types:
        VEHICLE_TYPE_MAP[t.lower()] = cat

# ─── Manufacturer Origin Mapping ─────────────────────────────────────────────
_ORIGIN_LISTS = {
    "Deutschland": ["Audi","Volkswagen","VW","Skoda","Škoda","Seat","SEAT","Smart",
                     "BMW","Cupra","Mini","MINI","Mercedes-Benz","Mercedes",
                     "Porsche","Volvo","Opel","Ford"],
    "Italien": ["Alfa Romeo","Lancia","Fiat","Maserati","Ferrari","Lamborghini","Abarth"],
    "Korea": ["Hyundai","SsangYong","Kia","Genesis","Daewoo"],
    "Japan": ["Toyota","Honda","Nissan","Mazda","Mitsubishi","Suzuki",
              "Subaru","Daihatsu","Lexus","Infiniti","Isuzu"],
    "Frankreich": ["Peugeot","Renault","Citroën","Citroen","Dacia","DS","Alpine"],
}
ORIGIN_MAP: dict[str,str] = {}
for origin, brands in _ORIGIN_LISTS.items():
    for b in brands:
        ORIGIN_MAP[b.lower()] = origin


def classify_vehicle_type(fahrzeugtyp: str) -> str:
    if fahrzeugtyp is None or str(fahrzeugtyp).strip() in ("","nan","None"):
        return "Andere"
    key = str(fahrzeugtyp).strip().lower()
    if key in VEHICLE_TYPE_MAP:
        return VEHICLE_TYPE_MAP[key]
    for pattern, category in VEHICLE_TYPE_MAP.items():
        if pattern in key or key in pattern:
            return category
    return "Andere"


def classify_origin(marke: str) -> str:
    if marke is None or str(marke).strip() in ("","nan","None"):
        return "Other/Unknown"
    key = str(marke).strip().lower()
    if key in ORIGIN_MAP:
        return ORIGIN_MAP[key]
    for brand, origin in ORIGIN_MAP.items():
        if brand in key or key in brand:
            return origin
    return "Other/Unknown"


def classify_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Classifying %d vehicles.", len(df))
    df["Fahrzeug_Klasse"] = df["Fahrzeugtyp"].apply(classify_vehicle_type)
    df["Herkunftsland"] = df["Markes"].apply(classify_origin)
    logger.info("Vehicle class distribution:\n%s", df["Fahrzeug_Klasse"].value_counts().to_string())
    logger.info("Origin distribution:\n%s", df["Herkunftsland"].value_counts().to_string())
    return df
