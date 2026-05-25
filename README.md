# Mobile.de NRW Scraper

Professional Python RPA/web-scraping solution for the Alphabots GmbH developer task.
The default scope is the public mobile.de regional directory for Nordrhein-Westfalen:

```text
https://home.mobile.de/regional/nordrhein-westfalen/0.html
```

Schema completeness is guaranteed; source completeness is measured. All required
output columns are created consistently, unavailable source values are left empty,
and coverage/error sheets explain what was actually available in the source pages.

## Features

- Local, strict headless, Firefox/Chrome, Docker, and Docker/Xvfb execution paths.
- Playwright browser automation for rendered pages, consent controls, contact sections, and dynamic dealer inventory pages.
- `curl_cffi` fast static fetcher where safe, with Playwright fallback for dynamic pages.
- Legacy sequential mode plus SQLite-backed producer-consumer pipeline mode.
- Bounded vendor and vehicle detail concurrency; no shared Playwright page across concurrent workers.
- Stable Händler IDs in `C0000001` format, persisted across SQLite resume runs.
- Batched checkpoints/state storage; full CSV/JSON exports happen at the end, not after every vehicle.
- Debug HTML and screenshots when enabled.
- Required Excel workbook and Word report with run summary, data coverage, errors, classification, and dashboard findings.

## Architecture

```text
Regional discovery
  -> vendor jobs / vendors table
  -> vendor workers collect dealer info and listing cards
  -> vehicle jobs
  -> bounded vehicle detail workers
  -> single SQLite writer
  -> final raw CSV/JSON, processed CSV/JSON, Excel, Word
```

Key modules:

- `src/config.py`: CLI/env configuration.
- `src/scraper/browser.py`: hardened Playwright lifecycle, browser modes, debug artifacts.
- `src/scraper/fetchers/`: `FetchResult`, curl fetcher, Playwright fetcher, strategy manager.
- `src/scraper/state_store.py`: SQLite run, vendor, vehicle job, vehicle, and error state.
- `src/scraper/pipeline.py`: bounded producer-consumer pipeline.
- `src/processing/`: cleaning, classification, dashboard scoring.
- `src/output/`: Excel workbook and Word report generation.

## Installation

```bash
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install
```

On Linux without Docker:

```bash
python -m playwright install-deps
python -m playwright install
```

## Local Runs

Small smoke run:

```bash
python -m src.main --state nordrhein-westfalen --max-vendors 2 --max-cars-per-vendor 3
```

Strict headless:

```bash
python -m src.main --state nordrhein-westfalen --browser-mode headless --max-vendors 10
```

Firefox headless:

```bash
python -m src.main --state nordrhein-westfalen --browser firefox --browser-mode headless --max-vendors 10
```

Visible local browser:

```bash
python -m src.main --state nordrhein-westfalen --browser-mode headed --max-vendors 10
```

SQLite producer-consumer pipeline:

```bash
python -m src.main --state nordrhein-westfalen --pipeline-mode sqlite --vendor-concurrency 2 --vehicle-detail-concurrency 3 --max-vendors 10
```

Clean run:

```bash
python -m src.main --state nordrhein-westfalen --clean-run true
```

## Docker / Cloud

The Docker image version is tied to the Playwright package version in `requirements.txt`.

Strict headless Docker:

```bash
docker compose up --build
```

Docker with Xvfb fallback:

```bash
BROWSER_MODE=xvfb HEADLESS=false docker compose up --build
```

Linux Xvfb without Docker:

```bash
xvfb-run -a python -m src.main --state nordrhein-westfalen --browser-mode xvfb --max-vendors 10
```

Strict headless is supported where the website serves the page normally. If a page is
unavailable or returns access denied, the run records the failure reason and continues
with measurable coverage where possible. Docker/Xvfb is the recommended server fallback
when strict headless rendering is unreliable.

## CLI Options

| Option | Default | Purpose |
|---|---:|---|
| `--state` | `nordrhein-westfalen` | German state slug |
| `--start-url` | empty | Optional regional URL/template; `{page}` is supported |
| `--max-vendors` | `0` | Vendor limit, 0 means unlimited |
| `--max-cars-per-vendor` | `0` | Vehicle limit per vendor, 0 means unlimited |
| `--max-vehicles-per-vendor` | empty | Alias for `--max-cars-per-vendor` |
| `--max-pages` | `0` | Regional page limit |
| `--browser` | `chromium` | `chromium`, `chrome`, or `firefox` |
| `--browser-mode` | `headed` | `headless`, `headed`, or `xvfb` |
| `--headless` | empty | Backward-compatible shortcut |
| `--fetch-strategy` | `auto` | `auto`, `curl`, or `playwright` |
| `--detail-policy` | `missing-required` | `always`, `missing-required`, `financing-only`, or `never` |
| `--pipeline-mode` | `legacy` | `legacy` or SQLite `sqlite` |
| `--regional-concurrency` | `1` | Regional producer setting |
| `--vendor-concurrency` | `1` | SQLite vendor workers |
| `--vehicle-listing-concurrency` | `1` | Listing traversal setting |
| `--vehicle-detail-concurrency` | `1` | SQLite vehicle detail workers |
| `--curl-concurrency` | `4` | curl fetch concurrency |
| `--playwright-concurrency` | `3` | Playwright fetch concurrency setting |
| `--checkpoint-every` | `50` | Legacy JSON checkpoint batch size |
| `--flush-every` | `100` | Durable writer batch setting |
| `--resume` | `true` | Resume checkpoints/state |
| `--clean-run` | `false` | Clear checkpoints/state and disable resume |
| `--force-resume` | `false` | Allow SQLite resume after config hash mismatch |
| `--output-dir` | `data/output` | Final output directory |
| `--debug` | `false` | Enable debug behavior |
| `--save-debug-artifacts` | `false` | Save failure HTML/screenshots |
| `--user-data-dir` | empty | Optional persistent Playwright profile directory |
| `--storage-state` | empty | Optional Playwright storage state JSON |
| `--min-delay` / `--max-delay` | `2.0` / `5.0` | Polite delay range |
| `--max-retries` | `3` | Navigation/fetch retry count |

## Output Files

```text
data/raw/vendors_raw.csv
data/raw/vendors_raw.json
data/raw/cars_raw.csv
data/raw/cars_raw.json
data/processed/cars_processed.csv
data/processed/cars_processed.json
data/output/errors.csv
data/output/errors.json
data/output/mobile_de_nrw_dashboard.xlsx
data/output/mobile_de_nrw_report.docx
```

Excel sheets include:

- `Vendors`
- `Vehicles`
- `Vendors_Raw`
- `Cars_Raw`
- `Cars_Processed`
- `Run_Summary`
- `Data_Coverage`
- `Errors`
- `Dashboard`
- `Vendor_Summary`
- `Manufacturer_Summary`
- `Category_Summary`
- `Best_Deals`
- `Worst_Deals`
- `Efficient_Vehicles`
- `Classification_Summary`
- `Category_By_Manufacturer`
- `Origin_Summary`

## Required Schema

Vendor output always includes the required task columns: `Händler ID`,
`Händlername`, `Standort`, `PLZ`, `Städte`, `Bundesland`, `Land`, phone/fax/email
fields, `Hauptseite`, `Mobile.de_Links`, and `Anzahl der Fahrzeuge`.

Vehicle output always includes the required task columns: dealer identifiers,
make/model/type/status/registration/mileage/fuel/CO2/price/power/seats/gearbox,
emissions class, color, series, trim, displacement, doors, owners, `Finanzierung`,
`Financing`, bank/intermediary, financing amounts/rates, duration, and traceability
columns such as `source_vendor_url`, `source_vehicle_url`, `fetch_strategy`,
`fetch_status`, `parse_status`, `vehicle_data_source`, `scraped_at`, and `run_id`.

## Classification Rules

Vehicle categories are exactly:

- `PKW`
- `Motorrad`
- `Freizeitfahrzeuge`
- `LKW`
- `Andere`

Classification metadata columns include `raw_vehicle_type`,
`normalized_vehicle_type`, `vehicle_category`,
`vehicle_category_confidence`, and `vehicle_category_rule`.

Manufacturer origins are exactly:

- `Deutschland`
- `Italien`
- `Korea`
- `Japan`
- `Frankreich`
- `Andere`

Manufacturer grouping follows the task-defined categories, not historical/legal
corporate-origin definitions. For example, Ford and Volvo are assigned to
Deutschland because they are listed under Deutschland in the assignment.

## Dashboard Methodology

The dashboard reports top/least vendors, best/worst deal candidates, efficient
vehicles, manufacturer summaries, origin summaries, and top category/manufacturer
combinations. Ranking is heuristic and explainable: score columns expose price,
mileage, age, CO2, performance/price-per-kW, confidence, and the number of fields
available. Missing values are not fabricated; rows with too little information are
excluded from ranked tables or receive lower confidence.

## Limitations

The scraper uses responsible browser automation and does not require authentication
or private endpoints. If a page is unavailable, the run records the failure reason
and continues with measurable coverage where possible. Financing, email, phone, and
detail-page technical fields only appear when the public source exposes them.

For production-grade contractual data access, an authorized API/data partnership
would be preferable. This assignment focuses on publicly visible website extraction
as requested.

## Tests

```bash
python -m pytest -q
```

