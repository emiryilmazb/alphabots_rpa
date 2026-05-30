# Validation Report

## 1. Final Branch and Purpose
- **final branch:** `improvements`
- **production/default behavior:** stable safe profile
- **adaptive profile:** opt-in only

## 2. Setup
- Python venv setup
- `pip install -r requirements.txt`
- Docker build/run basics
- no need to commit data/log outputs

## 3. Main Run Commands

Stable default/safe profile example:
```powershell
venv\Scripts\python.exe run_4shard.py --state nordrhein-westfalen --max-vendors 25 --max-cars-per-vendor 10 --max-pages 40 --shard-count 4 --clean --uc-wait-profile safe --uc-block-resources true
```

Full uncapped command should be documented cautiously, not recommended for casual validation:
```powershell
venv\Scripts\python.exe run_4shard.py --state nordrhein-westfalen --max-vendors 0 --max-cars-per-vendor 0 --shard-count 4 --clean --uc-wait-profile safe --uc-block-resources true
```

Adaptive opt-in example:
```powershell
venv\Scripts\python.exe run_4shard.py --state nordrhein-westfalen --max-vendors 25 --max-cars-per-vendor 10 --max-pages 40 --shard-count 4 --clean --uc-wait-profile adaptive --uc-block-resources true
```

Make clear:
- adaptive is experimental/opt-in
- adaptive is not default
- default remains safe

## 4. Sharding
- 4-shard is recommended for the tested 16GB Windows host
- 8-shard failed due to host resource limits
- 5/6/7 shard experiments showed diminishing returns / instability risk
- isolated data roots prevent SQLite locks
- global Händler ID prevents duplicates

## 5. Regional discovery / max pages
- regional pagination supports `--max-pages`
- `--max-pages` is recommended for capped validation runs
- regional runaway guard exists:
  - consecutive empty/no-new-dealer guard
  - consecutive Playwright fallback guard
- full discovery previously found around 1,140 NRW vendors, but live source changes can vary
- avoid interpreting live source variability as parser failure

## 6. Merge/output
- `tools/merge_runs.py` merges shard outputs
- supports:
  - list-shaped raw JSON
  - dict-shaped raw JSON
  - `vendors_raw.json`
  - `cars_raw.json`
  - alternate vehicle keys like `Vehicle_URL`, `source_vehicle_url`
- output Excel and Word are generated under merged output folder
- Run_Summary, Data_Coverage, Requirements_Compliance are Excel sheets, not necessarily standalone files

## 7. Dashboard validation
- document `tools/validate_dashboard.py`
- it validates workbook sheets and row counts
- it should check:
  - Vendors
  - Vehicles / Cars_Processed as applicable
  - Run_Summary
  - Data_Coverage
  - Requirements_Compliance
  - Errors if expected
  - vehicle_category
  - manufacturer_origin
  - no literal Unknown/Other in final classifications
  - Andere fallback allowed

## 8. Test status
- final tests: 137 passed / 0 failed
- compileall passed
- pip check passed

## 9. Limitations
- financing fields are source-dependent
- technical/detail fields are complete only when detail pages are reached
- live mobile.de behavior can change
- scraping can be blocked or rate-limited
- adaptive profile can improve live detail loading but remains opt-in
- 4-shard recommended, higher shard counts not guaranteed on 16GB Windows host

## 10. Final Verification Statement
Technical/detail fields are complete only when detail pages are successfully reached. Financing fields are extracted where available from the source. Schema completeness is guaranteed; source completeness is measured.
