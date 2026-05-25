"""Tests for dashboard scoring robustness."""

from __future__ import annotations

import pandas as pd

from src.processing.dashboard import prepare_dashboard


def test_dashboard_scores_remain_numeric_with_missing_values():
    cars = pd.DataFrame(
        [
            {
                "Händler ID": "C0000001",
                "Händlername": "Demo",
                "Markes": "Volkswagen",
                "Models": "Golf",
                "Fahrzeug_Klasse": "PKW",
                "Herkunftsland": "Deutschland",
                "Preis_EUR": 10000.0,
                "Kilometerstand_km": 50000.0,
                "EZ_Jahr": 2020,
                "Leistung_kW": 85.0,
                "Preis_pro_kW": 117.64,
                "CO2_gkm": None,
            },
            {
                "Händler ID": "C0000001",
                "Händlername": "Demo",
                "Markes": "",
                "Models": "Unknown",
                "Fahrzeug_Klasse": "Andere",
                "Herkunftsland": "Andere",
                "Preis_EUR": None,
                "Kilometerstand_km": None,
                "EZ_Jahr": None,
                "Preis_pro_kW": None,
                "CO2_gkm": None,
            },
        ]
    )

    dashboard = prepare_dashboard(pd.DataFrame(), cars)
    assert str(dashboard["best_deals"]["Deal_Score"].dtype) == "float64"
