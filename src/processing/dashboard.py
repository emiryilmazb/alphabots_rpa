"""Dashboard summary tables and explainable ranking metrics."""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("mobile_de.dashboard")


def prepare_dashboard(df_v: pd.DataFrame, df_c: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Prepare all dashboard-ready tables."""
    result: dict[str, pd.DataFrame] = {}
    result["vendor_summary"] = _vendor_summary(df_v, df_c)
    result["manufacturer_summary"] = _value_summary(df_c, "Markes", "Manufacturer")
    result["category_summary"] = _value_summary(df_c, "Fahrzeug_Klasse", "Category")
    result["origin_summary"] = _value_summary(df_c, "Herkunftsland", "Origin")
    result["category_manufacturer_summary"] = _category_by_manufacturer(df_c)
    result["best_deals"] = _compute_deals(df_c, best=True)
    result["worst_deals"] = _compute_deals(df_c, best=False)
    result["efficient_vehicles"] = _compute_efficient(df_c)
    logger.info("Dashboard tables prepared: %s", list(result.keys()))
    return result


def _vendor_summary(df_v: pd.DataFrame, df_c: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Händler ID",
        "Händlername",
        "PLZ",
        "Städte",
        "Bundesland",
        "Total_Vehicle_Count",
        "Scraped_Vehicle_Count",
        "Mobile.de_Links",
    ]
    if df_v.empty:
        return pd.DataFrame(columns=columns)

    vendors = df_v.copy()
    scraped = pd.DataFrame(columns=["Händler ID", "Scraped_Vehicle_Count"])
    if not df_c.empty and "Händler ID" in df_c.columns:
        scraped = df_c.groupby("Händler ID").size().reset_index(name="Scraped_Vehicle_Count")

    vendors = vendors.merge(scraped, on="Händler ID", how="left")
    vendors["Scraped_Vehicle_Count"] = vendors["Scraped_Vehicle_Count"].fillna(0).astype(int)
    vendors["Total_Vehicle_Count"] = pd.to_numeric(
        vendors.get("Anzahl der Fahrzeuge"), errors="coerce"
    ).fillna(vendors["Scraped_Vehicle_Count"])
    available = [col for col in columns if col in vendors.columns]
    return vendors[available].sort_values(
        ["Total_Vehicle_Count", "Scraped_Vehicle_Count", "Händlername"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def _value_summary(df: pd.DataFrame, source_col: str, out_col: str) -> pd.DataFrame:
    columns = [out_col, "Count", "Share"]
    if df.empty or source_col not in df.columns:
        return pd.DataFrame(columns=columns)
    series = df[source_col].replace("", pd.NA).fillna("Unknown")
    table = series.value_counts(dropna=False).reset_index()
    table.columns = [out_col, "Count"]
    total = table["Count"].sum()
    table["Share"] = table["Count"] / total if total else 0
    return table


def _category_by_manufacturer(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["Manufacturer", "Category", "Count"]
    required = {"Markes", "Fahrzeug_Klasse"}
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame(columns=columns)
    work = df.copy()
    work["Markes"] = work["Markes"].replace("", pd.NA).fillna("Unknown")
    work["Fahrzeug_Klasse"] = work["Fahrzeug_Klasse"].replace("", pd.NA).fillna("Andere")
    return (
        work.groupby(["Markes", "Fahrzeug_Klasse"])
        .size()
        .reset_index(name="Count")
        .rename(columns={"Markes": "Manufacturer", "Fahrzeug_Klasse": "Category"})
        .sort_values(["Manufacturer", "Count"], ascending=[True, False])
        .reset_index(drop=True)
    )


def _compute_deals(df: pd.DataFrame, *, best: bool) -> pd.DataFrame:
    cols = [
        "Händler ID",
        "Händlername",
        "Markes",
        "Models",
        "Fahrzeugtyp",
        "Preis",
        "Preis_EUR",
        "Kilometerstand",
        "Kilometerstand_km",
        "Erstzulassung",
        "EZ_Jahr",
        "Leistung",
        "Leistung_kW",
        "Preis_pro_kW",
        "CO₂-Emissionen",
        "CO2_gkm",
        "Vehicle_URL",
    ]
    if df.empty:
        return pd.DataFrame(columns=cols + ["Deal_Score", "Metric_Count", "Metric_Definition"])
    work = df[[col for col in cols if col in df.columns]].copy()

    metrics: list[tuple[str, pd.Series, bool]] = [
        ("price", pd.to_numeric(work.get("Preis_EUR"), errors="coerce"), True),
        ("mileage", pd.to_numeric(work.get("Kilometerstand_km"), errors="coerce"), True),
        ("registration_year", pd.to_numeric(work.get("EZ_Jahr"), errors="coerce"), False),
        ("price_per_kw", pd.to_numeric(work.get("Preis_pro_kW"), errors="coerce"), True),
        ("co2", pd.to_numeric(work.get("CO2_gkm"), errors="coerce"), True),
    ]
    score, count = _weighted_score(metrics)
    work["Deal_Score"] = score
    work["Metric_Count"] = count
    work["Metric_Definition"] = (
        "lower price, lower mileage, newer first registration, lower price/kW, lower CO2"
    )
    work = work[work["Metric_Count"] >= 2].copy()
    if work.empty:
        return pd.DataFrame(columns=list(work.columns))
    return (
        work.nsmallest(20, "Deal_Score") if best else work.nlargest(20, "Deal_Score")
    ).reset_index(drop=True)


def _compute_efficient(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "Händler ID",
        "Händlername",
        "Markes",
        "Models",
        "Fahrzeugtyp",
        "Preis_EUR",
        "CO₂-Emissionen",
        "CO2_gkm",
        "Kilometerstand_km",
        "Erstzulassung",
        "EZ_Jahr",
        "Kraftstoffart",
        "Vehicle_URL",
    ]
    if df.empty:
        return pd.DataFrame(columns=cols + ["Efficiency_Score", "Metric_Count", "Metric_Definition"])
    work = df[[col for col in cols if col in df.columns]].copy()
    metrics: list[tuple[str, pd.Series, bool]] = [
        ("co2", pd.to_numeric(work.get("CO2_gkm"), errors="coerce"), True),
        ("mileage", pd.to_numeric(work.get("Kilometerstand_km"), errors="coerce"), True),
        ("price", pd.to_numeric(work.get("Preis_EUR"), errors="coerce"), True),
        ("registration_year", pd.to_numeric(work.get("EZ_Jahr"), errors="coerce"), False),
    ]
    score, count = _weighted_score(metrics)
    work["Efficiency_Score"] = score
    work["Metric_Count"] = count
    work["Metric_Definition"] = (
        "low CO2, low mileage, reasonable price, newer first registration; "
        "fuel consumption is used only if present in source data"
    )
    work = work[work["Metric_Count"] >= 2].copy()
    if work.empty:
        return pd.DataFrame(columns=list(work.columns))
    return work.nsmallest(20, "Efficiency_Score").reset_index(drop=True)


def _weighted_score(metrics: list[tuple[str, pd.Series, bool]]) -> tuple[pd.Series, pd.Series]:
    index = metrics[0][1].index if metrics else pd.RangeIndex(0)
    score = pd.Series(0.0, index=index, dtype="float64")
    count = pd.Series(0, index=index, dtype="int64")

    for _name, series, lower_is_better in metrics:
        if series is None:
            continue
        series = pd.to_numeric(series, errors="coerce")
        mask = series.notna()
        if not mask.any():
            continue
        normalized = _normalize(series[mask])
        contribution = normalized if lower_is_better else 1 - normalized
        score.loc[mask] += contribution
        count.loc[mask] += 1

    score = score / count.replace(0, pd.NA)
    return score, count


def _normalize(series: pd.Series) -> pd.Series:
    minimum = series.min()
    maximum = series.max()
    if pd.isna(minimum) or pd.isna(maximum) or maximum == minimum:
        return pd.Series(0.5, index=series.index)
    return (series - minimum) / (maximum - minimum)
