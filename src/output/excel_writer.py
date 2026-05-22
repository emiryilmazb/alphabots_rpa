"""Excel workbook generation with formatted raw, processed, and dashboard sheets."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("mobile_de.excel")


def generate_excel(
    path: Path,
    df_vendors: pd.DataFrame,
    df_cars_raw: pd.DataFrame,
    df_cars_processed: pd.DataFrame,
    dashboard: dict[str, pd.DataFrame],
) -> None:
    """Write the required multi-sheet Excel workbook."""
    logger.info("Generating Excel workbook: %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(str(path), engine="xlsxwriter") as writer:
        wb = writer.book
        formats = _formats(wb)

        required_sheets = [
            ("Vendors_Raw", df_vendors),
            ("Cars_Raw", df_cars_raw),
            ("Cars_Processed", df_cars_processed),
            ("Vendor_Summary", dashboard.get("vendor_summary", pd.DataFrame())),
            ("Manufacturer_Summary", dashboard.get("manufacturer_summary", pd.DataFrame())),
            ("Category_Summary", dashboard.get("category_summary", pd.DataFrame())),
            ("Best_Deals", dashboard.get("best_deals", pd.DataFrame())),
            ("Worst_Deals", dashboard.get("worst_deals", pd.DataFrame())),
            ("Efficient_Vehicles", dashboard.get("efficient_vehicles", pd.DataFrame())),
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
        _write_sheet(writer, dashboard.get("origin_summary", pd.DataFrame()), "Origin_Summary", formats)
        _write_dashboard_sheet(writer, wb, dashboard, formats)

    logger.info("Excel workbook saved: %s", path)


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
        "title": wb.add_format({"bold": True, "font_size": 16, "font_color": "#1F4E79"}),
        "subtitle": wb.add_format({"bold": True, "font_size": 12, "font_color": "#2E75B6"}),
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
        ws.set_column(col_idx, col_idx, min(max(width, 10), 45), _column_format(col_name, formats))

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
    if "eur" in lower or "preis" in lower or "anzahlung" in lower or "schlussrate" in lower or "gesamtbetrag" in lower:
        return formats["eur"]
    if "km" in lower or "kilometer" in lower:
        return formats["km"]
    if "pct" in lower or "zins" in lower or "share" in lower:
        return formats["pct"] if lower == "share" else formats["float"]
    if "count" in lower or "jahr" in lower or "monate" in lower or "kw" in lower or "ps" in lower:
        return formats["num"]
    if "score" in lower or "co2" in lower:
        return formats["float"]
    return None


def _write_dashboard_sheet(writer, wb, dashboard: dict[str, pd.DataFrame], formats: dict) -> None:
    """Create an overview sheet with summary tables and charts."""
    ws = wb.add_worksheet("Dashboard")
    writer.sheets["Dashboard"] = ws
    ws.freeze_panes(3, 0)
    ws.set_column(0, 0, 32)
    ws.set_column(1, 1, 16)
    ws.set_column(2, 2, 18)
    ws.write(0, 0, "Mobile.de Nordrhein-Westfalen Dashboard", formats["title"])
    ws.write(1, 0, "Best/worst deal metrics use normalized price, mileage, first registration year, price/kW, and CO2 where available.")

    row = 3
    row = _write_dashboard_table(ws, "Top Vendors", dashboard.get("vendor_summary"), row, formats, cols=["Händlername", "Total_Vehicle_Count"], head=10)
    row = _write_dashboard_table(ws, "Least Vendors", _tail_sorted(dashboard.get("vendor_summary")), row, formats, cols=["Händlername", "Total_Vehicle_Count"], head=10)
    row = _write_dashboard_table(ws, "Top Manufacturers", dashboard.get("manufacturer_summary"), row, formats, cols=["Manufacturer", "Count"], head=15)
    row = _write_dashboard_table(ws, "Vehicle Categories", dashboard.get("category_summary"), row, formats, cols=["Category", "Count"], head=10)
    row = _write_dashboard_table(
        ws,
        "Most Listed Categories by Manufacturer",
        dashboard.get("category_manufacturer_summary"),
        row,
        formats,
        cols=["Manufacturer", "Category", "Count"],
        head=20,
    )

    _insert_bar_chart(wb, ws, "Top Manufacturers by Listing Count", "Dashboard", 25, 4, dashboard.get("manufacturer_summary"), "Manufacturer", "Count")
    _insert_pie_chart(wb, ws, "Vehicle Category Distribution", "Dashboard", 48, 4, dashboard.get("category_summary"), "Category", "Count")
    _insert_bar_chart(wb, ws, "Top Vendors by Total Vehicle Count", "Dashboard", 71, 4, dashboard.get("vendor_summary"), "Händlername", "Total_Vehicle_Count")


def _tail_sorted(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty or "Total_Vehicle_Count" not in df.columns:
        return pd.DataFrame()
    return df.sort_values(["Total_Vehicle_Count", "Händlername"], ascending=[True, True])


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
    for row_offset, (_, record) in enumerate(df[available].head(head).iterrows(), start=1):
        for col_idx, col in enumerate(available):
            _write_cell(ws, start_row + row_offset, col_idx, record[col])
    return start_row + min(len(df), head) + 3


def _insert_bar_chart(wb, ws, title: str, sheet_name: str, row: int, col: int, df: pd.DataFrame | None, cat_col: str, val_col: str) -> None:
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
            "values": [sheet_name, table_row, col + 1, table_row + len(data) - 1, col + 1],
            "fill": {"color": "#2E75B6"},
        }
    )
    chart.set_title({"name": title})
    chart.set_legend({"none": True})
    chart.set_size({"width": 560, "height": 320})
    ws.insert_chart(row, col + 3, chart)


def _insert_pie_chart(wb, ws, title: str, sheet_name: str, row: int, col: int, df: pd.DataFrame | None, cat_col: str, val_col: str) -> None:
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
            "values": [sheet_name, table_row, col + 1, table_row + len(data) - 1, col + 1],
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
