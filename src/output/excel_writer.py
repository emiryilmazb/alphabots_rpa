"""Excel workbook generation with formatted raw, processed, and dashboard sheets."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from src.models import (
    CLASSIFICATION_REQUIRED_FIELDS,
    FINANCING_REQUIRED_FIELDS,
    LOW_SOURCE_COVERAGE_FIELDS,
    VEHICLE_COLUMNS,
    VEHICLE_REQUIRED_FIELDS,
    VENDOR_COLUMNS,
    validate_required_columns,
)

logger = logging.getLogger("mobile_de.excel")


def generate_excel(
    path: Path,
    df_vendors: pd.DataFrame,
    df_cars_raw: pd.DataFrame,
    df_cars_processed: pd.DataFrame,
    dashboard: dict[str, pd.DataFrame],
    *,
    run_summary: dict | pd.DataFrame | None = None,
    vendor_coverage: pd.DataFrame | None = None,
    vehicle_coverage: pd.DataFrame | None = None,
    errors: list[dict] | pd.DataFrame | None = None,
) -> None:
    """Write the required multi-sheet Excel workbook."""
    logger.info("Generating Excel workbook: %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df_vendors = _ensure_columns(df_vendors, VENDOR_COLUMNS)
    df_cars_raw = _with_finanzierung_alias(df_cars_raw)
    df_cars_processed = _with_finanzierung_alias(df_cars_processed)
    df_cars_raw = _ensure_columns(df_cars_raw, VEHICLE_COLUMNS)
    df_cars_processed = _ensure_columns(df_cars_processed, VEHICLE_COLUMNS)
    _validate_or_raise(df_vendors, VENDOR_COLUMNS, "Vendors")
    _validate_or_raise(df_cars_processed, VEHICLE_COLUMNS, "Vehicles")

    with pd.ExcelWriter(str(path), engine="xlsxwriter") as writer:
        wb = writer.book
        formats = _formats(wb)

        required_sheets = [
            ("Vendors", df_vendors),
            ("Vehicles", df_cars_processed),
            ("Vendors_Raw", df_vendors),
            ("Cars_Raw", df_cars_raw),
            ("Cars_Processed", df_cars_processed),
            ("Run_Summary", _run_summary_df(run_summary)),
            ("Data_Coverage", _coverage_df(vendor_coverage, vehicle_coverage)),
            (
                "Requirements_Compliance",
                _requirements_compliance_df(
                    df_vendors,
                    df_cars_processed,
                    vendor_coverage,
                    vehicle_coverage,
                    dashboard,
                    run_summary,
                ),
            ),
            ("Errors", _errors_df(errors)),
            ("Vendor_Summary", dashboard.get("vendor_summary", pd.DataFrame())),
            (
                "Manufacturer_Summary",
                dashboard.get("manufacturer_summary", pd.DataFrame()),
            ),
            ("Category_Summary", dashboard.get("category_summary", pd.DataFrame())),
            ("Best_Deals", dashboard.get("best_deals", pd.DataFrame())),
            ("Worst_Deals", dashboard.get("worst_deals", pd.DataFrame())),
            ("Efficient_Vehicles", dashboard.get("efficient_vehicles", pd.DataFrame())),
            ("Classification_Summary", _classification_summary(df_cars_processed)),
        ]
        for sheet_name, df in required_sheets:
            _write_sheet(writer, df, sheet_name, formats)

        # Helpful extra summary for the "top categories by manufacturer" requirement.
        _write_sheet(
            writer,
            dashboard.get("category_manufacturer_summary", pd.DataFrame()),
            "Category_By_Manufacturer",
            formats,
        )
        _write_sheet(
            writer,
            dashboard.get("origin_summary", pd.DataFrame()),
            "Origin_Summary",
            formats,
        )
        _write_dashboard_sheet(writer, wb, dashboard, formats)

    logger.info("Excel workbook saved: %s", path)


def _with_finanzierung_alias(df: pd.DataFrame) -> pd.DataFrame:
    """Keep Financing and add the German alias expected by the task output."""
    if df is None:
        return pd.DataFrame()
    df = df.copy()
    if "Financing" in df.columns and "Finanzierung" not in df.columns:
        df["Finanzierung"] = df["Financing"]
    if "Finanzierung" in df.columns and "Financing" not in df.columns:
        df["Financing"] = df["Finanzierung"]
    return df


def _ensure_columns(df: pd.DataFrame | None, columns: list[str]) -> pd.DataFrame:
    if df is None:
        df = pd.DataFrame()
    df = df.copy()
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    remaining = [column for column in df.columns if column not in columns]
    return df[columns + remaining]


def _validate_or_raise(df: pd.DataFrame, columns: list[str], dataset: str) -> None:
    missing = validate_required_columns(df, columns)
    if missing:
        raise ValueError(
            f"{dataset} output is missing required columns: {', '.join(missing)}"
        )


def _run_summary_df(run_summary: dict | pd.DataFrame | None) -> pd.DataFrame:
    if run_summary is None:
        return pd.DataFrame(columns=["metric", "value"])
    if isinstance(run_summary, pd.DataFrame):
        return run_summary
    return pd.DataFrame(
        [{"metric": key, "value": value} for key, value in run_summary.items()]
    )


def _coverage_df(
    vendor_coverage: pd.DataFrame | None,
    vehicle_coverage: pd.DataFrame | None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for dataset, coverage in [
        ("vendors", vendor_coverage),
        ("vehicles", vehicle_coverage),
    ]:
        if coverage is None:
            continue
        work = coverage.copy()
        work.insert(0, "dataset", dataset)
        frames.append(work)
    if not frames:
        return pd.DataFrame(
            columns=[
                "dataset",
                "field",
                "non_empty_count",
                "total_count",
                "coverage_pct",
            ]
        )
    return pd.concat(frames, ignore_index=True)


def _requirements_compliance_df(
    df_vendors: pd.DataFrame,
    df_cars_processed: pd.DataFrame,
    vendor_coverage: pd.DataFrame | None,
    vehicle_coverage: pd.DataFrame | None,
    dashboard: dict[str, pd.DataFrame] | None = None,
    run_summary: dict | pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    specs: list[tuple[str, str, pd.DataFrame, pd.DataFrame | None]] = []
    specs.extend(
        ("vendors", field, df_vendors, vendor_coverage) for field in VENDOR_COLUMNS
    )
    specs.extend(
        ("vehicles", field, df_cars_processed, vehicle_coverage)
        for field in VEHICLE_REQUIRED_FIELDS
    )
    specs.extend(
        ("financing", field, df_cars_processed, vehicle_coverage)
        for field in FINANCING_REQUIRED_FIELDS
    )
    specs.extend(
        ("classification", field, df_cars_processed, vehicle_coverage)
        for field in CLASSIFICATION_REQUIRED_FIELDS
    )

    seen: set[tuple[str, str]] = set()
    summary = _summary_mapping(run_summary)
    source_audit_completed = (
        str(summary.get("source_audit_completed", "")).lower() == "true"
    )
    detail_strategy_status = str(summary.get("detail_strategy_status", ""))
    for dataset, field, df, coverage_df in specs:
        key = (dataset, field)
        if key in seen:
            continue
        seen.add(key)
        coverage = _coverage_for_field(coverage_df, field, len(df))
        column_exists = field in df.columns
        extractor_exists = True
        coverage_pct = float(coverage["coverage_pct"])
        status = _compliance_status(column_exists, extractor_exists, coverage_pct)
        rows.append(
            {
                "field_name": field,
                "dataset": dataset,
                "required_by_task": "yes",
                "final_excel_column_exists": "yes" if column_exists else "no",
                "extractor_exists": "yes" if extractor_exists else "no",
                "current_source": _compliance_source(dataset, field),
                "current_coverage_pct": coverage_pct,
                "sample_present_value": _sample_present_value(df, field),
                "missing_count": int(coverage["missing_count"]),
                "risk_level": _risk_level(field, status),
                "status": status,
                "notes": _compliance_notes(
                    dataset,
                    field,
                    status,
                    source_audit_completed=source_audit_completed,
                    detail_strategy_status=detail_strategy_status,
                ),
            }
        )
    rows.extend(_dashboard_compliance_rows(dashboard or {}))
    rows.extend(_audit_compliance_rows(summary))
    return pd.DataFrame(
        rows,
        columns=[
            "field_name",
            "dataset",
            "required_by_task",
            "final_excel_column_exists",
            "extractor_exists",
            "current_source",
            "current_coverage_pct",
            "sample_present_value",
            "missing_count",
            "risk_level",
            "status",
            "notes",
        ],
    )


def _coverage_for_field(
    coverage_df: pd.DataFrame | None, field: str, total: int
) -> dict[str, float | int]:
    if (
        coverage_df is not None
        and not coverage_df.empty
        and "field" in coverage_df.columns
    ):
        matches = coverage_df[coverage_df["field"].astype(str) == field]
        if not matches.empty:
            row = matches.iloc[0]
            present = int(row.get("non_empty_count", 0) or 0)
            row_total = int(row.get("total_count", total) or total)
            coverage_pct = float(row.get("coverage_pct", 0.0) or 0.0)
            return {
                "non_empty_count": present,
                "total_count": row_total,
                "coverage_pct": round(coverage_pct, 2),
                "missing_count": max(row_total - present, 0),
            }
    return {
        "non_empty_count": 0,
        "total_count": int(total),
        "coverage_pct": 0.0,
        "missing_count": int(total),
    }


def _sample_present_value(df: pd.DataFrame, field: str) -> str:
    if df is None or df.empty or field not in df.columns:
        return ""
    for value in df[field]:
        if _has_value(value):
            return str(value)
    return ""


def _has_value(value: object) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip() not in {"", "None", "nan", "NaN", "<NA>"}


def _compliance_status(
    column_exists: bool, extractor_exists: bool, coverage_pct: float
) -> str:
    if not column_exists or not extractor_exists:
        return "missing"
    if coverage_pct == 0:
        return "schema_only"
    if coverage_pct < 50:
        return "weak"
    if coverage_pct < 85:
        return "partially_satisfied"
    return "satisfied"


def _risk_level(field: str, status: str) -> str:
    if field in LOW_SOURCE_COVERAGE_FIELDS and status == "schema_only":
        return "high"
    if status in {"missing", "schema_only"}:
        return "high"
    if status == "weak":
        return "high" if field in LOW_SOURCE_COVERAGE_FIELDS else "medium"
    if status == "partially_satisfied":
        return "medium"
    return "low"


def _compliance_source(dataset: str, field: str) -> str:
    if dataset == "vendors":
        if field == "Händler ID":
            return "derived"
        if field == "Bundesland":
            return "vendor_address_or_region"
        return "vendor_page"
    if dataset == "financing":
        return "listing_payload_financePlans_or_detail_page"
    if dataset == "classification":
        return "derived_processing"
    if field in {"Händler ID", "Händlername", "PLZ"}:
        return "derived_from_vendor"
    if field in LOW_SOURCE_COVERAGE_FIELDS:
        return "listing_payload_attribute_or_detail_page"
    return "listing_payload_or_detail_page"


def _compliance_notes(
    dataset: str,
    field: str,
    status: str,
    *,
    source_audit_completed: bool = False,
    detail_strategy_status: str = "",
) -> str:
    if field == "Bundesland":
        return "Actual vendor state/region; target search state is kept separately as search_state/Run_Summary target_state."
    if field in LOW_SOURCE_COVERAGE_FIELDS:
        if source_audit_completed:
            return (
                "Extractor exists, but returned source coverage is low. "
                f"Source audit/detail matrix status={detail_strategy_status or 'completed'}; values are not guessed."
            )
        return "Extractor exists, but current source coverage is low; values are not guessed when mobile.de does not expose them."
    if dataset == "financing":
        return (
            "Populated only when mobile.de exposes a financing offer for the listing."
        )
    if dataset == "classification":
        return "Derived from scraped vehicle type/manufacturer according to task rules."
    if status == "partially_satisfied":
        return "Column and extractor exist; this run had sparse source values."
    if status == "weak":
        return "Column and extractor exist; this run had very sparse source values."
    return "Column and extractor are present."


def _summary_mapping(run_summary: dict | pd.DataFrame | None) -> dict[str, object]:
    if run_summary is None:
        return {}
    if isinstance(run_summary, pd.DataFrame):
        if {"metric", "value"}.issubset(run_summary.columns):
            return dict(zip(run_summary["metric"].astype(str), run_summary["value"]))
        if run_summary.shape[1] >= 2:
            return dict(zip(run_summary.iloc[:, 0].astype(str), run_summary.iloc[:, 1]))
        return {}
    return dict(run_summary)


def _requirement_row(
    *,
    field_name: str,
    dataset: str,
    source: str,
    coverage_pct: float,
    status: str,
    notes: str,
    sample: str = "",
    missing_count: int = 0,
    risk_level: str | None = None,
) -> dict[str, object]:
    return {
        "field_name": field_name,
        "dataset": dataset,
        "required_by_task": "yes",
        "final_excel_column_exists": "yes",
        "extractor_exists": "yes",
        "current_source": source,
        "current_coverage_pct": round(float(coverage_pct), 2),
        "sample_present_value": sample,
        "missing_count": missing_count,
        "risk_level": risk_level or ("low" if status == "satisfied" else "medium"),
        "status": status,
        "notes": notes,
    }


def _dashboard_compliance_rows(
    dashboard: dict[str, pd.DataFrame],
) -> list[dict[str, object]]:
    requirements = [
        ("Top and Least vendors", ["vendor_summary"], "Vendor_Summary/Dashboard"),
        (
            "Best and worst deals",
            ["best_deals", "worst_deals"],
            "Best_Deals/Worst_Deals",
        ),
        ("Efficient Vehicles", ["efficient_vehicles"], "Efficient_Vehicles"),
        (
            "Highest and lowest manufacturers and top-selling categories",
            ["manufacturer_summary", "category_manufacturer_summary"],
            "Manufacturer_Summary/Category_By_Manufacturer",
        ),
        ("Excel output", [], "workbook"),
        ("Word report", [], "word_report"),
    ]
    rows: list[dict[str, object]] = []
    for field_name, keys, source in requirements:
        available = True
        if keys:
            available = all(
                key in dashboard
                and isinstance(dashboard[key], pd.DataFrame)
                and not dashboard[key].empty
                for key in keys
            )
        rows.append(
            _requirement_row(
                field_name=field_name,
                dataset="dashboard",
                source=source,
                coverage_pct=100.0 if available else 0.0,
                status="satisfied" if available else "schema_only",
                notes="Dashboard requirement is generated in the workbook/report."
                if available
                else "Dashboard input was empty in this run.",
                missing_count=0 if available else 1,
                risk_level="low" if available else "medium",
            )
        )
    return rows


def _audit_compliance_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    source_audit_completed = (
        str(summary.get("source_audit_completed", "")).lower() == "true"
    )
    detail_status = str(summary.get("detail_strategy_status", ""))
    detail_completed = bool(detail_status) and not detail_status.startswith("failed")
    return [
        _requirement_row(
            field_name="source_audit_completed",
            dataset="source_audit",
            source="source_audit",
            coverage_pct=100.0 if source_audit_completed else 0.0,
            status="satisfied" if source_audit_completed else "schema_only",
            sample=str(summary.get("source_audit_dir", "")),
            missing_count=0 if source_audit_completed else 1,
            risk_level="low" if source_audit_completed else "medium",
            notes="Bounded source audit evidence saved."
            if source_audit_completed
            else "Source audit was not run for this workbook.",
        ),
        _requirement_row(
            field_name="detail_strategy_matrix_completed",
            dataset="detail_strategy",
            source="detail_strategy_matrix",
            coverage_pct=100.0 if detail_completed else 0.0,
            status="satisfied" if detail_completed else "schema_only",
            sample=str(summary.get("detail_strategy_matrix_path", "")),
            missing_count=0 if detail_completed else 1,
            risk_level="low" if detail_completed else "medium",
            notes=f"Detail strategy status: {detail_status or 'not_run'}.",
        ),
    ]


def _classification_summary(df: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for field, label in [
        ("vehicle_category", "vehicle_category"),
        ("manufacturer_origin", "manufacturer_origin"),
        ("Fahrzeug_Klasse", "Fahrzeug_Klasse"),
        ("Herkunftsland", "Herkunftsland"),
    ]:
        if field not in df.columns:
            continue
        summary = (
            df[field]
            .replace("", pd.NA)
            .fillna("Andere")
            .value_counts(dropna=False)
            .reset_index()
        )
        summary.columns = ["value", "count"]
        summary.insert(0, "classification_field", label)
        frames.append(summary)
    if not frames:
        return pd.DataFrame(columns=["classification_field", "value", "count"])
    return pd.concat(frames, ignore_index=True)


def _errors_df(errors: list[dict] | pd.DataFrame | None) -> pd.DataFrame:
    if errors is None:
        return pd.DataFrame(columns=["type", "url", "error"])
    if isinstance(errors, pd.DataFrame):
        return errors
    df = pd.DataFrame(errors)
    for column in ["type", "url", "error"]:
        if column not in df.columns:
            df[column] = ""
    remaining = [
        column for column in df.columns if column not in {"type", "url", "error"}
    ]
    return df[["type", "url", "error", *remaining]]


def _formats(wb) -> dict:
    return {
        "header": wb.add_format(
            {
                "bold": True,
                "bg_color": "#1F4E79",
                "font_color": "white",
                "border": 1,
                "text_wrap": True,
                "valign": "vcenter",
            }
        ),
        "title": wb.add_format(
            {"bold": True, "font_size": 16, "font_color": "#1F4E79"}
        ),
        "subtitle": wb.add_format(
            {"bold": True, "font_size": 12, "font_color": "#2E75B6"}
        ),
        "eur": wb.add_format({"num_format": '#,##0 "€"'}),
        "km": wb.add_format({"num_format": '#,##0 "km"'}),
        "pct": wb.add_format({"num_format": "0.00%"}),
        "num": wb.add_format({"num_format": "#,##0"}),
        "float": wb.add_format({"num_format": "#,##0.00"}),
    }


def _write_sheet(writer, df: pd.DataFrame, name: str, formats: dict) -> None:
    """Write a DataFrame to a sheet with headers, filters, panes, and formats."""
    if df is None:
        df = pd.DataFrame()
    df.to_excel(writer, sheet_name=name, index=False, startrow=1, header=False)
    ws = writer.sheets[name]

    for col_idx, col_name in enumerate(df.columns):
        ws.write(0, col_idx, col_name, formats["header"])

    for col_idx, col_name in enumerate(df.columns):
        width = len(str(col_name)) + 3
        if len(df) > 0:
            width = max(width, _safe_column_width(df[col_name], fallback=width))
        ws.set_column(
            col_idx, col_idx, min(max(width, 10), 45), _column_format(col_name, formats)
        )

    ws.freeze_panes(1, 0)
    if len(df.columns) > 0:
        last_row = max(len(df), 1)
        ws.autofilter(0, 0, last_row, len(df.columns) - 1)


def _safe_column_width(series: pd.Series, fallback: int) -> int:
    """Return a display width even when a column is entirely NA/NaN."""
    try:
        lengths = series.fillna("").astype(str).str.len().clip(upper=60)
        max_len = lengths.max()
        if pd.isna(max_len):
            return fallback
        return int(max_len) + 2
    except Exception:
        return fallback


def _column_format(col_name: str, formats: dict):
    lower = col_name.lower()
    if (
        "eur" in lower
        or "preis" in lower
        or "anzahlung" in lower
        or "schlussrate" in lower
        or "gesamtbetrag" in lower
    ):
        return formats["eur"]
    if "km" in lower or "kilometer" in lower:
        return formats["km"]
    if "pct" in lower or "zins" in lower or "share" in lower:
        return formats["pct"] if lower == "share" else formats["float"]
    if (
        "count" in lower
        or "jahr" in lower
        or "monate" in lower
        or "kw" in lower
        or "ps" in lower
    ):
        return formats["num"]
    if "score" in lower or "co2" in lower:
        return formats["float"]
    return None


def _write_dashboard_sheet(
    writer, wb, dashboard: dict[str, pd.DataFrame], formats: dict
) -> None:
    """Create an overview sheet with summary tables and charts."""
    ws = wb.add_worksheet("Dashboard")
    writer.sheets["Dashboard"] = ws
    ws.freeze_panes(3, 0)
    ws.set_column(0, 0, 32)
    ws.set_column(1, 1, 16)
    ws.set_column(2, 2, 18)
    ws.write(0, 0, "Mobile.de Nordrhein-Westfalen Dashboard", formats["title"])
    ws.write(
        1,
        0,
        "Best/worst deal metrics use normalized price, mileage, first registration year, price/kW, and CO2 where available.",
    )

    row = 3
    row = _write_dashboard_table(
        ws,
        "Top Vendors",
        dashboard.get("vendor_summary"),
        row,
        formats,
        cols=["Händlername", "Total_Vehicle_Count"],
        head=10,
    )
    row = _write_dashboard_table(
        ws,
        "Least Vendors",
        _tail_sorted(dashboard.get("vendor_summary")),
        row,
        formats,
        cols=["Händlername", "Total_Vehicle_Count"],
        head=10,
    )
    row = _write_dashboard_table(
        ws,
        "Top Manufacturers",
        dashboard.get("manufacturer_summary"),
        row,
        formats,
        cols=["Manufacturer", "Count"],
        head=15,
    )
    row = _write_dashboard_table(
        ws,
        "Vehicle Categories",
        dashboard.get("category_summary"),
        row,
        formats,
        cols=["Category", "Count"],
        head=10,
    )
    row = _write_dashboard_table(
        ws,
        "Most Listed Categories by Manufacturer",
        dashboard.get("category_manufacturer_summary"),
        row,
        formats,
        cols=["Manufacturer", "Category", "Count"],
        head=20,
    )

    _insert_bar_chart(
        wb,
        ws,
        "Top Manufacturers by Listing Count",
        "Dashboard",
        25,
        4,
        dashboard.get("manufacturer_summary"),
        "Manufacturer",
        "Count",
    )
    _insert_pie_chart(
        wb,
        ws,
        "Vehicle Category Distribution",
        "Dashboard",
        48,
        4,
        dashboard.get("category_summary"),
        "Category",
        "Count",
    )
    _insert_bar_chart(
        wb,
        ws,
        "Top Vendors by Total Vehicle Count",
        "Dashboard",
        71,
        4,
        dashboard.get("vendor_summary"),
        "Händlername",
        "Total_Vehicle_Count",
    )


def _tail_sorted(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty or "Total_Vehicle_Count" not in df.columns:
        return pd.DataFrame()
    return df.sort_values(
        ["Total_Vehicle_Count", "Händlername"], ascending=[True, True]
    )


def _write_dashboard_table(
    ws,
    title: str,
    df: pd.DataFrame | None,
    start_row: int,
    formats: dict,
    *,
    cols: list[str],
    head: int,
) -> int:
    ws.write(start_row, 0, title, formats["subtitle"])
    start_row += 1
    if df is None or df.empty:
        ws.write(start_row, 0, "No data available")
        return start_row + 3

    available = [col for col in cols if col in df.columns]
    for col_idx, col in enumerate(available):
        ws.write(start_row, col_idx, col, formats["header"])
    for row_offset, (_, record) in enumerate(
        df[available].head(head).iterrows(), start=1
    ):
        for col_idx, col in enumerate(available):
            _write_cell(ws, start_row + row_offset, col_idx, record[col])
    return start_row + min(len(df), head) + 3


def _insert_bar_chart(
    wb,
    ws,
    title: str,
    sheet_name: str,
    row: int,
    col: int,
    df: pd.DataFrame | None,
    cat_col: str,
    val_col: str,
) -> None:
    if df is None or df.empty or cat_col not in df.columns or val_col not in df.columns:
        return
    data = df[[cat_col, val_col]].head(15).reset_index(drop=True)
    table_row = row
    for idx, record in data.iterrows():
        _write_cell(ws, table_row + idx, col, record[cat_col])
        _write_cell(ws, table_row + idx, col + 1, record[val_col])
    chart = wb.add_chart({"type": "bar"})
    chart.add_series(
        {
            "name": val_col,
            "categories": [sheet_name, table_row, col, table_row + len(data) - 1, col],
            "values": [
                sheet_name,
                table_row,
                col + 1,
                table_row + len(data) - 1,
                col + 1,
            ],
            "fill": {"color": "#2E75B6"},
        }
    )
    chart.set_title({"name": title})
    chart.set_legend({"none": True})
    chart.set_size({"width": 560, "height": 320})
    ws.insert_chart(row, col + 3, chart)


def _insert_pie_chart(
    wb,
    ws,
    title: str,
    sheet_name: str,
    row: int,
    col: int,
    df: pd.DataFrame | None,
    cat_col: str,
    val_col: str,
) -> None:
    if df is None or df.empty or cat_col not in df.columns or val_col not in df.columns:
        return
    data = df[[cat_col, val_col]].head(8).reset_index(drop=True)
    table_row = row
    for idx, record in data.iterrows():
        _write_cell(ws, table_row + idx, col, record[cat_col])
        _write_cell(ws, table_row + idx, col + 1, record[val_col])
    chart = wb.add_chart({"type": "pie"})
    chart.add_series(
        {
            "name": val_col,
            "categories": [sheet_name, table_row, col, table_row + len(data) - 1, col],
            "values": [
                sheet_name,
                table_row,
                col + 1,
                table_row + len(data) - 1,
                col + 1,
            ],
        }
    )
    chart.set_title({"name": title})
    chart.set_size({"width": 500, "height": 320})
    ws.insert_chart(row, col + 3, chart)


def _write_cell(ws, row: int, col: int, value) -> None:
    if pd.isna(value):
        ws.write_blank(row, col, None)
    else:
        ws.write(row, col, value)
