"""Tests for Phase 1 output workbook/report compatibility."""

from __future__ import annotations

import openpyxl
import pandas as pd
from docx import Document

from src.output.excel_writer import generate_excel
from src.output.word_report import generate_word_report


def test_excel_includes_phase1_summary_sheets_and_finanzierung_alias(tmp_path):
    path = tmp_path / "dashboard.xlsx"
    vendors = pd.DataFrame(
        [{"Händler ID": "C0000001", "Händlername": "Demo Händler", "Mobile.de_Links": "https://home.mobile.de/DEMO"}]
    )
    cars = pd.DataFrame(
        [
            {
                "Händler ID": "C0000001",
                "Markes": "Volkswagen",
                "Models": "Golf",
                "Financing": "100 € mtl.",
                "Vehicle_URL": "https://suchen.mobile.de/fahrzeuge/details.html?id=1",
            }
        ]
    )
    dashboard = {
        "vendor_summary": pd.DataFrame(),
        "manufacturer_summary": pd.DataFrame(),
        "category_summary": pd.DataFrame(),
        "best_deals": pd.DataFrame(),
        "worst_deals": pd.DataFrame(),
        "efficient_vehicles": pd.DataFrame(),
    }

    generate_excel(
        path,
        vendors,
        cars,
        cars,
        dashboard,
        run_summary={"run_id": "test-run", "vendors": 1, "vehicles_raw": 1},
        vendor_coverage=pd.DataFrame(
            [{"field": "Händlername", "non_empty_count": 1, "total_count": 1, "coverage_pct": 100.0}]
        ),
        vehicle_coverage=pd.DataFrame(
            [{"field": "Financing", "non_empty_count": 1, "total_count": 1, "coverage_pct": 100.0}]
        ),
        errors=[{"type": "vehicle", "url": "https://example.test", "error": "boom"}],
    )

    workbook = openpyxl.load_workbook(path)
    assert {"Vendors", "Vehicles", "Run_Summary", "Data_Coverage", "Errors", "Classification_Summary"}.issubset(set(workbook.sheetnames))
    raw_headers = [cell.value for cell in workbook["Cars_Raw"][1]]
    assert "Financing" in raw_headers
    assert "Finanzierung" in raw_headers
    vehicle_headers = [cell.value for cell in workbook["Vehicles"][1]]
    assert "source_vehicle_url" in vehicle_headers
    assert "run_id" in vehicle_headers


def test_word_report_accepts_phase1_summary_inputs(tmp_path):
    path = tmp_path / "report.docx"
    generate_word_report(
        path,
        pd.DataFrame([{"Händler ID": "C0000001"}]),
        pd.DataFrame([{"Vehicle_URL": "https://example.test"}]),
        {},
        "nordrhein-westfalen",
        [],
        run_summary={"run_id": "test-run", "vendors": 1, "vehicles_raw": 1, "errors": 0},
        vendor_coverage=pd.DataFrame(
            [{"field": "Händler ID", "non_empty_count": 1, "total_count": 1, "coverage_pct": 100.0}]
        ),
        vehicle_coverage=pd.DataFrame(
            [{"field": "Vehicle_URL", "non_empty_count": 1, "total_count": 1, "coverage_pct": 100.0}]
        ),
    )

    document = Document(path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Data Completeness" in text
    assert "Schema completeness is guaranteed; source completeness is measured." in text
    assert "Manufacturer grouping follows the task-defined categories" in text
    assert "Unavailable source values are not guessed." in text
    assert "test-run" in text
