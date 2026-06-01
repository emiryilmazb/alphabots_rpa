# Validation Report

## 1. Final Branch and Purpose
- **final branch:** `improvements`
- **production/deployable architecture:** Docker/Xvfb
- **host Chrome CDP:** optional local recovery/enrichment only
- **adaptive profile:** explicit command profile, not an implicit local browser dependency

## 2. Setup
- Python venv setup
- `pip install -r requirements.txt`
- Docker build/run basics
- no need to commit data/log outputs

## 3. Main Run Commands

Production/server command for the deployable Docker/Xvfb path:
```powershell
venv\Scripts\python.exe run_4shard.py --state nordrhein-westfalen --max-vendors 0 --max-cars-per-vendor 0 --max-pages 100 --shard-count 1 --clean --uc-wait-profile adaptive --uc-block-resources false
```

One shard is safest under current live-source blocking. Two shards can be used if the source remains stable. Four shards are for controlled validation/benchmarking, not a final high-detail run while blocking is active.

Conservative capped validation command:
```powershell
venv\Scripts\python.exe run_4shard.py --state nordrhein-westfalen --max-vendors 25 --max-cars-per-vendor 10 --max-pages 40 --shard-count 4 --clean --uc-wait-profile safe --uc-block-resources true
```

Adaptive capped validation example:
```powershell
venv\Scripts\python.exe run_4shard.py --state nordrhein-westfalen --max-vendors 25 --max-cars-per-vendor 10 --max-pages 40 --shard-count 4 --clean --uc-wait-profile adaptive --uc-block-resources true
```

Optional local CDP enrichment after a normal scrape:
```powershell
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\mobilede_detail_profile"
venv\Scripts\python.exe tools\enrich_vehicle_details.py --input-cars <cars_raw.json> --output-cars <cars_enriched.json> --cache-dir data\detail_cache\host_cdp_enrichment --methods cache,listing,host-chrome-cdp,manual-html --chrome-cdp-url http://127.0.0.1:9222 --max-vehicles 25 --sleep-seconds 12 --sleep-jitter-seconds 8 --stop-after-blocks 5 --max-block-rate 0.4 --resume true --retry-only-missing true
```

CDP is not required for EC2/ECS deployment and is never used unless explicitly selected.

## 4. Sharding
- 1 shard is safest under live-source blocking
- 2 shards can be used if the source remains stable
- 4-shard is recommended only for controlled validation/benchmarking on the tested 16GB Windows host
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
- no fake values are inserted; missing values are reported in Data_Coverage and Requirements_Compliance
- `Andere` is the approved fallback for task-defined classification values outside the requested origin/category lists

## 10. Final Verification Statement
Technical/detail fields are complete only when detail pages are successfully reached. Financing fields are extracted where available from the source. Schema completeness is guaranteed; source completeness is measured.
