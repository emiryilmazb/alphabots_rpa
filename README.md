# Mobile.de NRW Vendor and Vehicle Scraper

Production-oriented Python project for the Alphabots developer task. The default target is:

```text
https://home.mobile.de/regional/nordrhein-westfalen/0.html
```

The pipeline discovers vendors from the mobile.de regional directory, extracts dealer/contact data and vehicle listing data, cleans and classifies records, and generates an Excel dashboard plus a Word methodology report.

## Features

- Playwright browser automation for JavaScript-rendered pages, consent handling, contact modals, and phone reveal buttons.
- BeautifulSoup parsing with robust fallbacks for rendered DOM, JSON-LD, and mobile.de Next.js payloads.
- Stable vendor IDs assigned after alphabetic sorting of normalized dealer URLs: `C0000001`, `C0000002`, etc.
- Checkpoint/resume support for dealers, vendors, vehicles, and completed vendor inventories.
- Polite delays, retry-aware navigation, duplicate vendor/vehicle filtering, and error logging.
- Raw CSV/JSON outputs after vendor and vehicle scraping.
- Dealer inventories are traversed across mobile.de vehicle categories such as Pkw, Motorrad, Wohnmobile, Lkw, Sattelzugmaschinen, Auflieger, Anhänger, Baumaschinen, Busse, Agrarfahrzeuge, and Stapler.
- Vehicle records are enriched from mobile.de structured `searchResults.listings` payloads, including finance-plan fields when exposed in the listing data.
- pandas cleaning, numeric parsing, vehicle type classification, and manufacturer country classification.
- Excel workbook with required sheets, filters, frozen headers, formats, summary tables, and charts.
- Word report covering methodology, preprocessing, dashboard metrics, assumptions, limitations, and key results.
- Compliance behavior: the scraper does not bypass CAPTCHA, login gates, or mobile.de access-denied protections. If blocked, it saves partial/empty outputs and records the limitation.

## Project Structure

```text
mobile_de_scraper/
|-- README.md
|-- requirements.txt
|-- pyproject.toml
|-- .env.example
|-- src/
|   |-- main.py
|   |-- config.py
|   |-- models.py
|   |-- scraper/
|   |   |-- browser.py
|   |   |-- regional_scraper.py
|   |   |-- vendor_scraper.py
|   |   |-- vehicle_scraper.py
|   |   `-- parsers.py
|   |-- processing/
|   |   |-- cleaning.py
|   |   |-- classification.py
|   |   `-- dashboard.py
|   |-- output/
|   |   |-- excel_writer.py
|   |   `-- word_report.py
|   `-- utils/
|       |-- logging_utils.py
|       |-- retry.py
|       `-- checkpoints.py
|-- data/
|   |-- raw/
|   |-- processed/
|   `-- output/
`-- tests/
    |-- test_classification.py
    |-- test_cleaning.py
    `-- test_parsers.py
```

## Setup

```bash
cd mobile_de_scraper
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

Small test run:

```bash
python -m src.main --state nordrhein-westfalen --max-vendors 2 --max-cars-per-vendor 3
```

Full NRW run. In this environment mobile.de blocks headless Chromium, so the default is visible browser mode:

```bash
python -m src.main --state nordrhein-westfalen
```

Explicit visible browser run:

```bash
python -m src.main --state nordrhein-westfalen --max-vendors 5 --max-cars-per-vendor 10 --headless false
```

Fresh run without old checkpoints:

```bash
python -m src.main --state nordrhein-westfalen --clear-checkpoints true --resume false
```

CLI options:

| Option | Default | Description |
|---|---:|---|
| `--state` | `nordrhein-westfalen` | German state slug |
| `--max-vendors` | `0` | Max vendors, where 0 means all |
| `--max-cars-per-vendor` | `0` | Max vehicles per vendor across all categories, where 0 means all |
| `--max-pages` | `0` | Max regional pages, where 0 means all |
| `--skip-vehicle-details` | `false` | Save dealer listing-card data and skip detail pages; default tries detail pages and falls back when blocked |
| `--traverse-vehicle-categories` | `true` | Visit known mobile.de vehicle categories for each vendor |
| `--max-detail-failures` | `2` | Disable detail-page requests after repeated blocked/5xx responses |
| `--headless` | `false` | Run Chromium headless when set to `true` |
| `--fallback-to-headed-on-block` | `true` | Restart once in visible mode if headless is denied by site protection |
| `--resume` | `true` | Resume from checkpoints |
| `--clear-checkpoints` | `false` | Delete existing checkpoints before scraping |
| `--min-delay` | `2.0` | Minimum polite delay in seconds |
| `--max-delay` | `5.0` | Maximum polite delay in seconds |

`.env.example` documents matching environment variables.

## Outputs

Raw and processed data:

```text
data/raw/vendors_raw.csv
data/raw/vendors_raw.json
data/raw/cars_raw.csv
data/raw/cars_raw.json
data/processed/cars_processed.csv
data/processed/cars_processed.json
data/output/errors.csv
data/output/errors.json
```

Final deliverables:

```text
data/output/mobile_de_nrw_dashboard.xlsx
data/output/mobile_de_nrw_report.docx
```

Required Excel sheets:

1. `Vendors_Raw`
2. `Cars_Raw`
3. `Cars_Processed`
4. `Vendor_Summary`
5. `Manufacturer_Summary`
6. `Category_Summary`
7. `Best_Deals`
8. `Worst_Deals`
9. `Efficient_Vehicles`
10. `Dashboard`

The workbook also includes `Category_By_Manufacturer` and `Origin_Summary` for additional dashboard context.

## Tests

```bash
python -m pytest tests -q
```

## Notes on Blocking

mobile.de may return `HTTP 403: access denied by site protection` to automated browsers, especially headless Chromium. This project records that condition in `data/output/errors.csv`, avoids bypass attempts, and can restart once in visible mode to collect legitimate deliverable data. Vehicle detail pages can also return temporary 5xx/site-protection responses; after the configured threshold, the scraper continues from structured dealer-listing payloads instead of inventing missing values.
