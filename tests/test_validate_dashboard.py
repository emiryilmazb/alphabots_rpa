import pandas as pd
import pytest
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tools.validate_dashboard import validate_dashboard

def test_validate_dashboard_success(tmp_path):
    excel_path = tmp_path / 'test_dashboard.xlsx'
    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame({'id': range(25)}).to_excel(writer, sheet_name='Vendors', index=False)
        pd.DataFrame({
            'id': range(190), 
            'vehicle_category': ['PKW']*189 + ['Andere'],
            'manufacturer_origin': ['Deutschland']*189 + ['Andere']
        }).to_excel(writer, sheet_name='Vehicles', index=False)
        pd.DataFrame({'metric': ['a'], 'val': [1]}).to_excel(writer, sheet_name='Run_Summary', index=False)
        pd.DataFrame({'field': ['a'], 'cov': [1]}).to_excel(writer, sheet_name='Data_Coverage', index=False)
        pd.DataFrame({'req': ['a'], 'comp': [1]}).to_excel(writer, sheet_name='Requirements_Compliance', index=False)
        
    assert validate_dashboard(str(excel_path), 25, 190) is True

def test_validate_dashboard_missing_sheet(tmp_path):
    excel_path = tmp_path / 'test_dashboard.xlsx'
    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame({'id': range(25)}).to_excel(writer, sheet_name='Vendors', index=False)
        pd.DataFrame({
            'id': range(190), 
            'vehicle_category': ['PKW']*190,
            'manufacturer_origin': ['Deutschland']*190
        }).to_excel(writer, sheet_name='Vehicles', index=False)
        # Missing Run_Summary
        pd.DataFrame({'field': ['a'], 'cov': [1]}).to_excel(writer, sheet_name='Data_Coverage', index=False)
        pd.DataFrame({'req': ['a'], 'comp': [1]}).to_excel(writer, sheet_name='Requirements_Compliance', index=False)
        
    assert validate_dashboard(str(excel_path), 25, 190) is False

def test_validate_dashboard_literal_unknown(tmp_path):
    excel_path = tmp_path / 'test_dashboard.xlsx'
    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame({'id': range(25)}).to_excel(writer, sheet_name='Vendors', index=False)
        pd.DataFrame({
            'id': range(190), 
            'vehicle_category': ['Unknown']*190,
            'manufacturer_origin': ['Deutschland']*190
        }).to_excel(writer, sheet_name='Vehicles', index=False)
        pd.DataFrame({'metric': ['a'], 'val': [1]}).to_excel(writer, sheet_name='Run_Summary', index=False)
        pd.DataFrame({'field': ['a'], 'cov': [1]}).to_excel(writer, sheet_name='Data_Coverage', index=False)
        pd.DataFrame({'req': ['a'], 'comp': [1]}).to_excel(writer, sheet_name='Requirements_Compliance', index=False)
        
    assert validate_dashboard(str(excel_path), 25, 190) is False

def test_validate_dashboard_row_counts(tmp_path):
    excel_path = tmp_path / 'test_dashboard.xlsx'
    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame({'id': range(24)}).to_excel(writer, sheet_name='Vendors', index=False)
        pd.DataFrame({
            'id': range(100), 
            'vehicle_category': ['PKW']*100,
            'manufacturer_origin': ['Deutschland']*100
        }).to_excel(writer, sheet_name='Vehicles', index=False)
        pd.DataFrame({'metric': ['a'], 'val': [1]}).to_excel(writer, sheet_name='Run_Summary', index=False)
        pd.DataFrame({'field': ['a'], 'cov': [1]}).to_excel(writer, sheet_name='Data_Coverage', index=False)
        pd.DataFrame({'req': ['a'], 'comp': [1]}).to_excel(writer, sheet_name='Requirements_Compliance', index=False)
        
    assert validate_dashboard(str(excel_path), 25, 190) is False
