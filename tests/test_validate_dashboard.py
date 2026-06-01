import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models import FINANCING_REQUIRED_FIELDS, VEHICLE_REQUIRED_FIELDS, VENDOR_COLUMNS
from tools.validate_dashboard import validate_dashboard


def _write_workbook(
    excel_path,
    *,
    vendor_rows=25,
    vehicle_rows=186,
    missing_sheet="",
    missing_vendor_column="",
    missing_vehicle_column="",
    vehicle_category="PKW",
    manufacturer_origin="Deutschland",
):
    vendor_columns = [column for column in VENDOR_COLUMNS if column != missing_vendor_column]
    vehicle_columns = [
        column
        for column in dict.fromkeys([*VEHICLE_REQUIRED_FIELDS, *FINANCING_REQUIRED_FIELDS])
        if column != missing_vehicle_column
    ]
    vehicle_data = {column: ["value"] * vehicle_rows for column in vehicle_columns}
    vehicle_data["vehicle_category"] = [vehicle_category] * vehicle_rows
    vehicle_data["manufacturer_origin"] = [manufacturer_origin] * vehicle_rows

    with pd.ExcelWriter(excel_path) as writer:
        if missing_sheet != "Vendors":
            pd.DataFrame({column: ["value"] * vendor_rows for column in vendor_columns}).to_excel(
                writer,
                sheet_name="Vendors",
                index=False,
            )
        if missing_sheet != "Vehicles":
            pd.DataFrame(vehicle_data).to_excel(writer, sheet_name="Vehicles", index=False)
        if missing_sheet != "Run_Summary":
            pd.DataFrame({"metric": ["a"], "value": [1]}).to_excel(writer, sheet_name="Run_Summary", index=False)
        if missing_sheet != "Data_Coverage":
            pd.DataFrame({"field": ["a"], "coverage_pct": [100]}).to_excel(
                writer,
                sheet_name="Data_Coverage",
                index=False,
            )
        if missing_sheet != "Requirements_Compliance":
            pd.DataFrame({"field_name": ["a"], "status": ["satisfied"]}).to_excel(
                writer,
                sheet_name="Requirements_Compliance",
                index=False,
            )
        if missing_sheet != "Dashboard":
            pd.DataFrame({"metric": ["a"], "value": [1]}).to_excel(writer, sheet_name="Dashboard", index=False)
        if missing_sheet != "Errors":
            pd.DataFrame(columns=["stage", "url", "error"]).to_excel(writer, sheet_name="Errors", index=False)


def test_validate_dashboard_186_vehicles_passes_without_exact_count(tmp_path):
    excel_path = tmp_path / "test_dashboard.xlsx"
    _write_workbook(excel_path, vehicle_rows=186)

    assert validate_dashboard(str(excel_path)) is True


def test_validate_dashboard_minimum_counts_pass(tmp_path):
    excel_path = tmp_path / "test_dashboard.xlsx"
    _write_workbook(excel_path, vehicle_rows=186)

    assert validate_dashboard(str(excel_path), min_vendors=25, min_vehicles=180) is True


def test_validate_dashboard_exact_expected_vehicle_count_fails_only_when_requested(tmp_path):
    excel_path = tmp_path / "test_dashboard.xlsx"
    _write_workbook(excel_path, vehicle_rows=186)

    assert validate_dashboard(str(excel_path), min_vendors=25, min_vehicles=180) is True
    assert (
        validate_dashboard(
            str(excel_path),
            min_vendors=25,
            min_vehicles=180,
            expected_vehicles=190,
        )
        is False
    )


def test_validate_dashboard_missing_sheet_fails(tmp_path):
    excel_path = tmp_path / "test_dashboard.xlsx"
    _write_workbook(excel_path, missing_sheet="Run_Summary")

    assert validate_dashboard(str(excel_path)) is False


def test_validate_dashboard_missing_required_vendor_column_fails(tmp_path):
    excel_path = tmp_path / "test_dashboard.xlsx"
    _write_workbook(excel_path, missing_vendor_column="Händlername")

    assert validate_dashboard(str(excel_path)) is False


def test_validate_dashboard_missing_required_vehicle_column_fails(tmp_path):
    excel_path = tmp_path / "test_dashboard.xlsx"
    _write_workbook(excel_path, missing_vehicle_column="Markes")

    assert validate_dashboard(str(excel_path)) is False


def test_validate_dashboard_literal_unknown_or_other_fails(tmp_path):
    unknown_path = tmp_path / "unknown_dashboard.xlsx"
    other_path = tmp_path / "other_dashboard.xlsx"
    _write_workbook(unknown_path, vehicle_category="Unknown")
    _write_workbook(other_path, manufacturer_origin="Other")

    assert validate_dashboard(str(unknown_path)) is False
    assert validate_dashboard(str(other_path)) is False


def test_validate_dashboard_allows_andere_classification(tmp_path):
    excel_path = tmp_path / "test_dashboard.xlsx"
    _write_workbook(excel_path, vehicle_category="Andere", manufacturer_origin="Andere")

    assert validate_dashboard(str(excel_path)) is True
