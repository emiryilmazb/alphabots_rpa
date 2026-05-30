import argparse
import sys
import pandas as pd
from pathlib import Path

def validate_dashboard(excel_path: str, expected_vendors: int = 25, expected_vehicles: int = 190):
    path = Path(excel_path)
    if not path.exists():
        print(f"Error: Excel file not found at {path}")
        return False
    
    print(f"Validating dashboard: {path}")
    try:
        xls = pd.ExcelFile(path)
    except Exception as e:
        print(f"Error opening Excel file: {e}")
        return False
        
    sheets = xls.sheet_names
    print(f"Found sheets: {sheets}")
    
    required_sheets = ["Vendors", "Run_Summary", "Data_Coverage", "Requirements_Compliance"]
    missing = [s for s in required_sheets if s not in sheets]
    
    vehicle_sheet = None
    for name in ["Vehicles", "Cars_Processed", "Cars"]:
        if name in sheets:
            vehicle_sheet = name
            break
            
    if not vehicle_sheet:
        print("Error: No vehicle sheet found (looked for Vehicles, Cars_Processed, Cars)")
        return False
        
    if missing:
        print(f"Error: Missing required sheets: {missing}")
        return False
        
    print("Excel sheet validation is the source of truth for Run_Summary, Data_Coverage, and Requirements_Compliance.")
    print("No standalone JSON/CSV files are required unless explicitly exported later.")
        
    all_passed = True
    
    vendors_df = pd.read_excel(xls, sheet_name="Vendors")
    if len(vendors_df) != expected_vendors:
        print(f"Error: Expected {expected_vendors} Vendors, got {len(vendors_df)}")
        all_passed = False
    else:
        print(f"Vendors row count: {len(vendors_df)} (OK)")
        
    vehicles_df = pd.read_excel(xls, sheet_name=vehicle_sheet)
    if len(vehicles_df) != expected_vehicles:
        print(f"Error: Expected {expected_vehicles} Vehicles, got {len(vehicles_df)}")
        all_passed = False
    else:
        print(f"Vehicles row count: {len(vehicles_df)} (OK)")
        
    run_summary_df = pd.read_excel(xls, sheet_name="Run_Summary")
    if len(run_summary_df) <= 0:
        print("Error: Run_Summary is empty")
        all_passed = False
    else:
        print(f"Run_Summary row count: {len(run_summary_df)} (OK)")
        
    data_coverage_df = pd.read_excel(xls, sheet_name="Data_Coverage")
    if len(data_coverage_df) <= 0:
        print("Error: Data_Coverage is empty")
        all_passed = False
    else:
        print(f"Data_Coverage row count: {len(data_coverage_df)} (OK)")
        
    req_comp_df = pd.read_excel(xls, sheet_name="Requirements_Compliance")
    if len(req_comp_df) <= 0:
        print("Error: Requirements_Compliance is empty")
        all_passed = False
    else:
        print(f"Requirements_Compliance row count: {len(req_comp_df)} (OK)")
        
    columns = vehicles_df.columns.tolist()
    if "vehicle_category" not in columns:
        print("Error: vehicle_category column missing")
        all_passed = False
    else:
        print("vehicle_category column present")
        
    if "manufacturer_origin" not in columns:
        print("Error: manufacturer_origin column missing")
        all_passed = False
    else:
        print("manufacturer_origin column present")
        
    if "vehicle_category" in columns:
        cats = vehicles_df["vehicle_category"].dropna().astype(str).unique().tolist()
        for bad in ["Unknown", "Other"]:
            if bad in cats:
                print(f"Error: Found literal '{bad}' in vehicle_category")
                all_passed = False
    if "manufacturer_origin" in columns:
        origins = vehicles_df["manufacturer_origin"].dropna().astype(str).unique().tolist()
        for bad in ["Unknown", "Other"]:
            if bad in origins:
                print(f"Error: Found literal '{bad}' in manufacturer_origin")
                all_passed = False
        if "Andere" in origins:
            print("Verified 'Andere' fallback can appear in origins (OK)")
        else:
            print("Note: 'Andere' fallback did not appear in this specific dataset.")
        
    return all_passed

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("excel_path", nargs="?", default="output/mobile_de_nrw_dashboard.xlsx", help="Path to the dashboard Excel file")
    parser.add_argument("--vendors", type=int, default=25, help="Expected vendor count")
    parser.add_argument("--vehicles", type=int, default=190, help="Expected vehicle count")
    args = parser.parse_args()
    
    if validate_dashboard(args.excel_path, args.vendors, args.vehicles):
        print("\nValidation PASSED.")
        sys.exit(0)
    else:
        print("\nValidation FAILED.")
        sys.exit(1)
