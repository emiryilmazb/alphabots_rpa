# Mobile.de NRW Scraper

Python RPA/web-scraping solution for the Alphabots GmbH developer task. The default target is the public mobile.de regional dealer directory for Nordrhein-Westfalen:

```text
https://home.mobile.de/regional/nordrhein-westfalen/0.html
```

The scraper collects dealer data, vehicle listing data, financing data where exposed by mobile.de, classifications, dashboard tables, an Excel workbook, and a Word report. Schema completeness is guaranteed; source completeness is measured. Required output columns are always created, unavailable source values are left empty, and coverage/error sheets explain what was available in the source pages.

## Project Overview

- Uses `curl_cffi` for static fetches where reliable and Playwright for rendered pages.
- Supports local headed execution, Docker/Xvfb server execution, and strict headless mode as a technical option.
- Uses a SQLite-backed producer-consumer pipeline for bounded vendor and vehicle work.
- Traverses dealer inventory categories and enforces vendor/car caps for controlled benchmarks.
- Extracts rich listing-card data from mobile.de Next.js payloads, including many financing fields from listing payloads.
- Generates raw exports, processed exports, Excel dashboard workbook, Word methodology/report document, and structured error records.

Strict headless is technically supported but currently blocked by mobile.de in this environment. Docker/Xvfb is the recommended server-compatible execution mode.

## Setup

Windows/local setup:

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install
```

Linux without Docker:

```bash
python -m pip install -r requirements.txt
python -m playwright install-deps
python -m playwright install
```

Docker setup:

```powershell
docker compose build scraper
```

## Recommended Commands

Local small test:

```powershell
venv\Scripts\python.exe -m src.main --state nordrhein-westfalen --pipeline-mode sqlite --browser-mode headed --fetch-strategy auto --detail-policy missing-required --detail-max-retries 1 --max-vendors 5 --max-cars-per-vendor 5 --vendor-concurrency 1 --vehicle-detail-concurrency 2 --benchmark
```

Docker/Xvfb server mode:

```powershell
docker compose run --rm -e BROWSER_MODE=xvfb scraper python -m src.main --state nordrhein-westfalen --pipeline-mode sqlite --browser-mode xvfb --fetch-strategy auto --detail-policy missing-required --detail-max-retries 1 --max-vendors 10 --max-cars-per-vendor 5 --vendor-concurrency 1 --vehicle-detail-concurrency 1 --benchmark
```

Final larger run, only if approved:

```powershell
docker compose run --rm -e BROWSER_MODE=xvfb scraper python -m src.main --state nordrhein-westfalen --pipeline-mode sqlite --browser-mode xvfb --fetch-strategy auto --detail-policy missing-required --detail-max-retries 1 --vendor-concurrency 1 --vehicle-detail-concurrency 1 --benchmark
```

Do not use the final larger command as a smoke test. Run capped benchmarks first and inspect the output quality.

## Execution Modes

Local headed mode is useful for development and manual validation. It opens a visible Playwright browser and has been used for capped benchmark validation.

Docker/Xvfb mode is the recommended server-compatible mode. It runs a headed browser under a virtual framebuffer and avoids strict-headless site behavior while still running in Docker/server environments.

Strict headless mode remains available via `--browser-mode headless`, but it is not the recommended production path for this target because mobile.de currently blocks strict headless in this environment.

## CLI Options

| Option | Default | Purpose |
|---|---:|---|
| `--state` | `nordrhein-westfalen` | German state slug |
| `--start-url` | empty | Optional regional URL/template; `{page}` is supported |
| `--pipeline-mode` | `sqlite` | Use `sqlite` for final/capped runs |
| `--browser` | `chromium` | `chromium`, `chrome`, or `firefox` |
| `--browser-mode` | `headed` | `headless`, `headed`, or `xvfb` |
| `--fetch-strategy` | `auto` | `auto`, `curl`, or `playwright` |
| `--detail-policy` | `missing-required` | `always`, `missing-required`, `financing-only`, or `never` |
| `--max-vendors` | `0` | Vendor cap; `0` means uncapped |
| `--max-cars-per-vendor` | `0` | Vehicle cap per vendor; `0` means uncapped |
| `--vendor-concurrency` | `1` | Vendor worker count |
| `--vehicle-detail-concurrency` | `1` | Detail worker count |
| `--detail-max-retries` | `1` | Detail-page retry count |
| `--benchmark` | `false` | Write benchmark summary |
| `--clean-run` | `false` | Clear checkpoints/state and disable resume |
| `--output-dir` | empty | Optional output directory override |

## Output Files

When existing root data/state files are present and `--overwrite` is not used, the run writes to a new folder:

```text
data/runs/<run_id>/
```

Key files:

```text
data/runs/<run_id>/raw/vendors_raw.csv
data/runs/<run_id>/raw/vendors_raw.json
data/runs/<run_id>/raw/cars_raw.csv
data/runs/<run_id>/raw/cars_raw.json
data/runs/<run_id>/processed/cars_processed.csv
data/runs/<run_id>/processed/cars_processed.json
data/runs/<run_id>/output/mobile_de_nrw_dashboard.xlsx
data/runs/<run_id>/output/mobile_de_nrw_report.docx
data/runs/<run_id>/output/errors.csv
data/runs/<run_id>/output/errors.json
data/runs/<run_id>/output/benchmark_summary.json
```

Root `data/raw`, `data/state`, and `data/output` are not overwritten during guarded run-folder execution.

## Excel Workbook

The Excel workbook contains the required raw, processed, summary, coverage, error, compliance, and dashboard outputs.

Expected sheets:

- `Vendors`
- `Vehicles`
- `Vendors_Raw`
- `Cars_Raw`
- `Cars_Processed`
- `Run_Summary`
- `Data_Coverage`
- `Requirements_Compliance`
- `Errors`
- `Vendor_Summary`
- `Manufacturer_Summary`
- `Category_Summary`
- `Best_Deals`
- `Worst_Deals`
- `Efficient_Vehicles`
- `Classification_Summary`
- `Category_By_Manufacturer`
- `Origin_Summary`
- `Dashboard`

## Word Report

The Word report documents:

- extraction methodology
- Docker/Xvfb server-compatible execution
- strict headless limitation
- detail-page/source limitation
- classification methodology
- dashboard findings
- run summary
- known limitations

It includes the exact statement:

```text
Schema completeness is guaranteed; source completeness is measured.
```

## Data_Coverage

`Data_Coverage` reports per-field non-empty counts, total row counts, and coverage percentages. It is the primary measurement of source completeness for each vendor and vehicle field. Missing values are not guessed or fabricated.

## Requirements_Compliance

`Requirements_Compliance` reports one row per required task field with:

- `field_name`
- `dataset`
- `required_by_task`
- `final_excel_column_exists`
- `extractor_exists`
- `current_source`
- `current_coverage_pct`
- `sample_present_value`
- `missing_count`
- `risk_level`
- `status`
- `notes`

Status values:

- `satisfied`: column/extractor exist and source coverage is acceptable in the run
- `partially_satisfied`: column/extractor exist but source values are sparse
- `schema_only`: column/extractor exist but current coverage is 0%
- `missing`: required column or extractor is absent

## Classification

Vehicle categories are mapped to:

- `PKW`
- `Motorrad`
- `Freizeitfahrzeuge`
- `LKW`
- `Andere`

Manufacturer origins are mapped to:

- `Deutschland`
- `Italien`
- `Korea`
- `Japan`
- `Frankreich`
- `Andere`

The final classification uses the task-defined values. Literal `Unknown`/`Other` should not appear in final classification columns.

## Known Limitations

Some vehicle detail fields such as CO₂-Emissionen, Baureihe, Ausstattungslinie, and Anzahl der Fahrzeughalter showed low source coverage because mobile.de detail pages returned site-side 403/503 responses. These values are not guessed and are reported transparently in Data_Coverage and Requirements_Compliance.

Financing fields are populated only when mobile.de exposes a financing offer in the listing payload or detail source. Dealer homepage, second phone, mobile phone, and fax fields can be sparse because not every dealer publishes those values.

Regional search state and actual vendor location are kept separate:

- `Bundesland`: actual vendor state/region when available or derivable from a German PLZ
- `Land`: actual vendor country
- `search_state`: searched/assigned state, such as `Nordrhein-Westfalen`

The project is not 1:1 source-complete because mobile.de does not expose every requested value in every accessible source and detail pages may be blocked. The deliverable is complete structurally and reports measured source limitations.

## Final Validation Checklist

- `pytest` passed
- Docker build passed
- Docker/Xvfb smoke passed
- Excel generated
- Word generated
- `Requirements_Compliance` present
- `Data_Coverage` present
- `Errors` present
- No literal `Unknown`/`Other` in final classifications
- Detail limitations documented

## Tests

```powershell
venv\Scripts\python.exe -m pytest tests/ -v --tb=short
```
