# Mobile.de NRW Scraper

Python RPA/web-scraping solution for the Alphabots GmbH developer task. The default target is the public mobile.de regional dealer directory for Nordrhein-Westfalen:

```text
https://home.mobile.de/regional/nordrhein-westfalen/0.html
```

The scraper collects dealer data, vehicle listing data, financing data where exposed by mobile.de, classifications, dashboard tables, an Excel workbook, and a Word report. Technical/detail fields are complete only when detail pages are successfully reached. Financing fields are extracted where available from the source. Schema completeness is guaranteed; source completeness is measured. Required output columns are always created, unavailable source values are left empty, and coverage/error sheets explain what was available in the source pages.

## Project Overview

- Uses `curl_cffi` for static fetches where reliable and Playwright for rendered pages.
- Supports local headed execution, Docker/Xvfb server execution, and strict headless mode as a technical option.
- Uses a SQLite-backed producer-consumer pipeline for bounded vendor and vehicle work.
- Traverses dealer inventory categories and enforces vendor/car caps for controlled benchmarks.
- Extracts rich listing-card data from mobile.de Next.js payloads, including many financing fields from listing payloads.
- Offers an optional `uc-popup` detail enrichment strategy for small, controlled runs that need fields only visible on real mobile.de detail pages.
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

## Execution Modes

Local headed mode is useful for development and manual validation. It opens a visible Playwright browser and has been used for capped benchmark validation.

Docker/Xvfb mode is the recommended server-compatible mode. It runs a headed browser under a virtual framebuffer and avoids strict-headless site behavior while still running in Docker/server environments.

Strict headless mode remains available via `--browser-mode headless`, but it is not the recommended production path for this target because mobile.de currently blocks strict headless in this environment.

## UC Popup Detail Strategy

`--detail-open-strategy uc-popup` is an optional enrichment strategy for fields that are often missing from listing payloads: CO₂-Emissionen, Baureihe, Ausstattungslinie, Anzahl der Fahrzeughalter, Hubraum, Türen, Schadstoffklasse, Farbe, and Sitzplätze. It is intended for small missing-detail runs, not broad benchmarks.

The default stable pipeline remains listing-first. UC popup is only used when `--detail-open-strategy uc-popup` is explicitly passed. It requires:

- `undetected_chromedriver`
- `selenium`
- `setuptools` on Python 3.12 runtimes because the current UC package imports `distutils`
- a local Google Chrome installation

The strategy opens the current vendor/category page, collects live mobile.de detail links from the rendered page or listing payload, matches the current vehicle by URL or vehicle id, opens the matched detail in a new tab, switches to the new tab, classifies the resulting page, and only merges detail values into empty listing fields. Existing listing values are not overwritten. If the live link is stale, unavailable, redirects home, opens an error page, or the popup cannot be captured, the scraper records the reason and keeps the listing fallback row.

Run UC popup with `--vehicle-detail-concurrency 1`. The output metrics include `detail_open_strategy`, `popup_opened_count`, `popup_captured_count`, `popup_capture_failed_count`, `wrong_tab_capture_count`, `real_detail_page_loaded_count`, `detail_home_redirect_count`, `detail_error_page_count`, `stale_redirect_count`, `uc_popup_success_count`, `uc_popup_failed_count`, and `detail_target_fields_extracted_count`.

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
| `--detail-open-strategy` | `auto` | `auto`, `listing-only`, `playwright-direct`, `playwright-click`, or `uc-popup`; legacy aliases are accepted |
| `--source-audit` | `false` | Save tiny-sample raw source artifacts, network logs, and detail strategy matrix evidence |
| `--source-audit-only` | `false` | Run only source audit/matrix and skip normal exports |
| `--source-audit-max-vendors` | `2` | Max vendors inspected by source audit |
| `--source-audit-max-vehicles` | `5` | Max vehicle detail URLs tested by source audit |
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
data/runs/<run_id>/source_audit/source_audit_summary.json
data/runs/<run_id>/source_audit/detail_strategy_matrix.json
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
- source audit and detail strategy matrix results when `--source-audit` is used
- classification methodology
- dashboard findings
- run summary
- known limitations

It includes the exact statement:

```text
Technical/detail fields are complete only when detail pages are successfully reached. Financing fields are extracted where available from the source. Schema completeness is guaranteed; source completeness is measured.
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

- `satisfied`: column/extractor exist and coverage is at least 85%
- `partially_satisfied`: column/extractor exist and coverage is 50-84%
- `weak`: column/extractor exist and coverage is 1-49%
- `schema_only`: column/extractor exist but current coverage is 0%
- `missing`: required column or extractor is absent

## Source Audit

`--source-audit` is a bounded evidence mode for the detail-dependent fields. It saves returned public source artifacts under `data/runs/<run_id>/source_audit/`, including vendor/category HTML, Next.js payloads, listing-card payloads, visible card text, detail attempt HTML/screenshots/headers, network response indexes, discovered API endpoints, and a detail strategy matrix.

The matrix tests direct URL, persistent context, same-context, category navigation, listing click, modifier click, delayed click, warmup click, and small browser-channel variations on a tiny sample. A strategy is only counted as useful when it extracts real source values for the target fields; filter labels or search facets are rejected.

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

Some vehicle detail fields such as CO₂-Emissionen, Baureihe, Ausstattungslinie, and Anzahl der Fahrzeughalter can still show low source coverage because mobile.de does not expose them in every listing payload and detail access can fail. These values are not guessed and are reported transparently in Data_Coverage and Requirements_Compliance.

Targeted source audit found that some listing payloads expose previous-owner count as `attr.pvo`; the parser maps this real source value to `Anzahl der Fahrzeughalter`. The optional UC popup strategy can increase measured coverage for CO₂-Emissionen, Baureihe, and Ausstattungslinie when mobile.de returns a real detail page for a live listing.

UC popup is slower than listing extraction and should be run with detail concurrency 1. If the dependency stack is unavailable, the run records `uc_dependency_missing` with the message `uc-popup strategy requires undetected_chromedriver and local Chrome.` and preserves listing fallback output.

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
- source audit evidence present when `--source-audit` is used
- `Errors` present
- No literal `Unknown`/`Other` in final classifications
- Detail limitations documented

## Tests

```powershell
venv\Scripts\python.exe -m pytest tests/ -v --tb=short
```
