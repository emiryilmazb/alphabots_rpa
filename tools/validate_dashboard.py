from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import (  # noqa: E402
    FINANCING_REQUIRED_FIELDS,
    VEHICLE_REQUIRED_FIELDS,
    VENDOR_COLUMNS,
)

REQUIRED_CONTROL_SHEETS = [
    "Vendors",
    "Run_Summary",
    "Data_Coverage",
    "Requirements_Compliance",
    "Dashboard",
    "Errors",
]
VEHICLE_SHEET_CANDIDATES = ["Vehicles", "Cars_Processed", "Cars_Raw", "Cars"]
CLASSIFICATION_COLUMNS = ["vehicle_category", "manufacturer_origin"]
DISALLOWED_CLASSIFICATION_VALUES = {"unknown", "other"}


def validate_dashboard(
    excel_path: str,
    min_vendors: int = 1,
    min_vehicles: int = 1,
    *,
    expected_vendors: int | None = None,
    expected_vehicles: int | None = None,
) -> bool:
    path = Path(excel_path)
    if not path.exists():
        print(f"Error: Excel file not found at {path}")
        return False

    print(f"Validating dashboard: {path}")
    try:
        xls = pd.ExcelFile(path)
    except Exception as exc:
        print(f"Error opening Excel file: {exc}")
        return False

    sheets = xls.sheet_names
    print(f"Found sheets: {sheets}")

    all_passed = True
    missing_sheets = [
        sheet for sheet in REQUIRED_CONTROL_SHEETS if sheet not in sheets]
    if missing_sheets:
        print(f"Error: Missing required sheets: {missing_sheets}")
        all_passed = False

    vehicle_sheet = next(
        (name for name in VEHICLE_SHEET_CANDIDATES if name in sheets), ""
    )
    if not vehicle_sheet:
        print(
            f"Error: No vehicle sheet found (looked for {', '.join(VEHICLE_SHEET_CANDIDATES)})"
        )
        all_passed = False

    if not all_passed:
        return False

    vendors_df = pd.read_excel(xls, sheet_name="Vendors")
    vehicles_df = pd.read_excel(xls, sheet_name=vehicle_sheet)
    run_summary_df = pd.read_excel(xls, sheet_name="Run_Summary")
    data_coverage_df = pd.read_excel(xls, sheet_name="Data_Coverage")
    req_comp_df = pd.read_excel(xls, sheet_name="Requirements_Compliance")

    all_passed &= _validate_rows(
        "Vendors",
        len(vendors_df),
        minimum=min_vendors,
        expected=expected_vendors,
    )
    all_passed &= _validate_rows(
        vehicle_sheet,
        len(vehicles_df),
        minimum=min_vehicles,
        expected=expected_vehicles,
    )
    all_passed &= _validate_non_empty("Run_Summary", run_summary_df)
    all_passed &= _validate_non_empty("Data_Coverage", data_coverage_df)
    all_passed &= _validate_non_empty("Requirements_Compliance", req_comp_df)

    all_passed &= _validate_columns("Vendors", vendors_df, VENDOR_COLUMNS)
    vehicle_required = list(
        dict.fromkeys([*VEHICLE_REQUIRED_FIELDS, *FINANCING_REQUIRED_FIELDS])
    )
    all_passed &= _validate_columns(
        vehicle_sheet, vehicles_df, vehicle_required)
    all_passed &= _validate_columns(
        vehicle_sheet, vehicles_df, CLASSIFICATION_COLUMNS)
    all_passed &= _validate_classifications(vehicles_df)

    if all_passed:
        print(
            "Excel structure, required columns, row thresholds, and classification values are valid."
        )
    return bool(all_passed)


def _validate_rows(
    name: str, count: int, *, minimum: int, expected: int | None
) -> bool:
    if expected is not None and count != expected:
        print(
            f"Error: Expected exactly {expected} rows in {name}, got {count}")
        return False
    if count < minimum:
        print(
            f"Error: Expected at least {minimum} rows in {name}, got {count}")
        return False
    print(f"{name} row count: {count} (OK)")
    return True


def _validate_non_empty(name: str, df: pd.DataFrame) -> bool:
    if len(df) <= 0:
        print(f"Error: {name} is empty")
        return False
    print(f"{name} row count: {len(df)} (OK)")
    return True


def _validate_columns(name: str, df: pd.DataFrame, required: list[str]) -> bool:
    missing = [column for column in required if column not in df.columns]
    if missing:
        print(f"Error: {name} missing required columns: {missing}")
        return False
    print(f"{name} required columns present ({len(required)} checked)")
    return True


def _validate_classifications(vehicles_df: pd.DataFrame) -> bool:
    all_passed = True
    for column in CLASSIFICATION_COLUMNS:
        if column not in vehicles_df.columns:
            continue
        values = vehicles_df[column].dropna().astype(str).str.strip()
        lowered = {value.lower() for value in values}
        bad_values = sorted(DISALLOWED_CLASSIFICATION_VALUES & lowered)
        if bad_values:
            print(
                f"Error: Found disallowed literal classification values in {column}: {bad_values}"
            )
            all_passed = False
        if "Andere" in set(values):
            print(f"Verified 'Andere' fallback can appear in {column} (OK)")
    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "excel_path",
        nargs="?",
        default="output/mobile_de_nrw_dashboard.xlsx",
        help="Path to the dashboard Excel file",
    )
    parser.add_argument(
        "--min-vendors", type=int, default=1, help="Minimum accepted vendor rows"
    )
    parser.add_argument(
        "--min-vehicles", type=int, default=1, help="Minimum accepted vehicle rows"
    )
    parser.add_argument(
        "--expected-vendors",
        type=int,
        default=None,
        help="Optional exact vendor row count",
    )
    parser.add_argument(
        "--expected-vehicles",
        type=int,
        default=None,
        help="Optional exact vehicle row count",
    )
    parser.add_argument(
        "--vendors", type=int, dest="expected_vendors", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--vehicles", type=int, dest="expected_vehicles", help=argparse.SUPPRESS
    )
    args = parser.parse_args()

    if validate_dashboard(
        args.excel_path,
        min_vendors=args.min_vendors,
        min_vehicles=args.min_vehicles,
        expected_vendors=args.expected_vendors,
        expected_vehicles=args.expected_vehicles,
    ):
        print("\nValidation PASSED.")
        sys.exit(0)
    print("\nValidation FAILED.")
    sys.exit(1)
