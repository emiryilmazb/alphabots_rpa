# POC and Professionalization Roadmap

## 1. Baseline Summary
- final branch: improvements
- stable commit: 597e15f
- recommended architecture: 4-shard Docker/Xvfb + uc-popup + resource blocking
- validation summary:
  - 34 regional pages
  - 1,140 unique vendors
  - 100-vendor / 780-vehicle validation
  - 93 tests passing
- final statement:
  “Schema completeness is guaranteed; source completeness is measured.”

## 2. Non-Negotiable Rules
- never modify improvements branch directly
- never commit generated data
- never run full uncapped without explicit approval
- every POC must be isolated and reversible
- every change must preserve test pass status
- every benchmark must be capped unless explicitly approved
- final submission commit is rollback baseline

## 3. Performance POCs
- investigate safe shard counts on stronger hardware/cloud
- retry 5/6/7/8 shard experiments on stronger hardware
- evaluate cloud/server VM run with higher RAM/CPU
- improve shard scheduling and balanced distribution
- avoid overloaded vendors causing shard imbalance
- add shard progress monitor
- add estimated time remaining per shard
- add retry/resume per shard
- add per-shard failure recovery
- investigate lighter detail fetch methods again only if isolated:
  - browser-context fetch
  - cookie-export + curl_cffi
  - CDP response capture
  - cached detail enrichment
- improve resource blocking without breaking DOM
- optional headless-like mode research, but Docker/Xvfb remains production path

- Expected benefit: Higher scalability and lower runtime.
- Risk: Bot detection and OOM issues.
- Validation method: Capped benchmarking.
- Rollback plan: Discard POC branch.

## 4. Data Completeness Improvements
- improve financing coverage reporting
- distinguish:
  - not available from source
  - parser missed
  - source changed after scrape
  - stale listing
- add field source metadata:
  - listing
  - detail
  - financePlans
  - derived
  - unavailable
- add field-level confidence
- add source URL / extraction timestamp columns
- improve vendor contact extraction:
  - 2nd phone
  - mobile phone
  - fax
  - email
  - homepage
- improve country/Bundesland validation
- improve vehicle type/category classification traceability
- improve manufacturer origin mapping traceability
- handle “not applicable” fields better in Data_Coverage
- avoid treating unavailable financing as parser failure
- source availability vs parser miss distinction

## 5. Code Professionalization / Refactor Ideas
- split overly large modules if any
- improve boundaries between:
  - discovery
  - vendor scraping
  - vehicle listing scraping
  - detail enrichment
  - preprocessing
  - output generation
  - sharding orchestration
- standardize config handling
- centralize environment variable parsing
- cleaner config/env handling
- add typed dataclasses/Pydantic models for:
  - shard config
  - run summary
  - detail fetch result
  - coverage result
  - merge result
- improve exception hierarchy:
  - BrowserError
  - DetailFetchError
  - SourceUnavailableError
  - MergeError
  - ShardError
- replace ad-hoc dictionaries with typed structures where practical
- standardize logging format
- logging/progress/ETA improvements
- improve retry/backoff utilities
- remove duplicated parsing logic
- isolate undetected_chromedriver-specific code behind interface
- make merge_runs.py testable and modular
- make run_4shard.py more production-grade
- add graceful shutdown handling
- add clear cleanup policy for Docker/Chrome/Xvfb
- sharding orchestration improvements

## 6. Testing Improvements
- integration tests for run_4shard.py using mocked commands
- run_4shard.py tests
- merge_runs.py tests with synthetic shard outputs
- regional pagination tests
- global Händler ID stability tests
- sharding distribution tests
- Data_Coverage regression tests
- Requirements_Compliance regression tests
- parser fixtures for detail fields:
  - CO₂
  - Baureihe
  - Ausstattungslinie
  - Anzahl der Fahrzeughalter
  - financing fields
- tests for “not available from source” vs empty parser bug
- tests for 0 = unlimited behavior
- tests for .gitignore safety / no generated data staged if feasible
- optional smoke-test workflow documentation

## 7. Documentation Improvements
- architecture diagram or textual architecture map
- final run quickstart
- troubleshooting guide:
  - Docker/Xvfb
  - UC popup
  - Chrome/chromedriver
  - database lock
  - shard failure
  - merge failure
- performance table:
  - single container
  - 2 shard
  - 4 shard
  - 8 shard failed reason
- source completeness explanation
- data coverage interpretation guide
- how to rerun process-existing
- how to inspect output Excel/Word
- how to resume/retry failed shards
- submission checklist

## 8. Operational Improvements
- run monitor script
- shard health checks
- per-shard logs summary
- automatic failure detection
- automatic retry of failed shard
- safe stop command
- cleanup command
- resource usage logging:
  - RAM
  - CPU
  - disk
  - Docker container stats
- ETA calculation
- notification when run completes

## 9. Risk Register
- mobile.de layout changes
  - impact: High
  - mitigation: CSS fallback selectors
  - detection method: Extractor test suites
- UC/chromedriver version mismatch
  - impact: Medium
  - mitigation: Version pinning
  - detection method: Browser init error logs
- Docker Desktop resource limits
  - impact: High
  - mitigation: 4-shard max validation
  - detection method: Resource monitoring
- RAM pressure
  - impact: High
  - mitigation: Resource blocking flag
  - detection method: Container stats
- Windows file locking
  - impact: High
  - mitigation: Isolated SQLite paths per shard
  - detection method: SQLite busy exceptions
- financing source unavailability
  - impact: Low
  - mitigation: Explicit reporting logic
  - detection method: Coverage analysis
- stale listings
  - impact: Medium
  - mitigation: Safe skipping
  - detection method: 404/503 monitoring
- data coverage misinterpretation
  - impact: High
  - mitigation: Clear final statement documentation
  - detection method: Report review
- accidental generated data commit
  - impact: Medium
  - mitigation: Strict gitignore
  - detection method: Pre-commit review
- overclaiming source completeness
  - impact: High
  - mitigation: Strict wording compliance
  - detection method: Manual text review
- risk and rollback plan
  - impact: High
  - mitigation: Rollback to 597e15f
  - detection method: Regression tests

## 10. Suggested Next POC Order
1. Read-only code architecture audit
2. run_4shard.py professionalization
3. merge_runs.py tests
4. coverage/source metadata improvements
5. progress monitor
6. cloud/stronger machine shard benchmark
7. optional alternative detail fetch research

## Phase A Implementation Notes
- Added exception hierarchy
- Added typed result models
- Added manifest foundation
- No scraper behavior changed
- Next planned step: parser fixture safety net before splitting parsers.py

## Phase B Parser Safety Net Notes
- Added synthetic HTML fixtures.
- Added parser fixture regression tests.
- Protected current behavior before splitting parsers.py.
- Known gap: "Türen" is not currently recognized as alias for "Anzahl der Türen".
- Future improvement: add normalized label alias mapping for doors after parser refactor safety net is complete.
- Next safe step: merge_runs.py synthetic tests or run_4shard.py orchestration tests.

## Phase C Sharding and Merge Safety Net Notes
- Synthetic shard fixtures added.
- merge_runs.py dedup behavior tested.
- run_4shard.py command construction tested with mocks.
- No Docker or live scraping used in tests.
- Future improvement: make merge output regeneration more modular if still difficult to test.

## Phase D Parser Modularization Notes
- parser structure map completed
- first low-risk helper extraction (normalization helpers) completed
- parsers.py remains backward-compatible
- current public entry points preserved
- no parser behavior changed
- next step: extract financing parser or vehicle detail parser only after fixture coverage is expanded


## Phase D.3 Vendor Parser Extraction Notes
* vendor parser functions extracted to `parser_modules/vendor.py`
* shared JSON helpers extracted to `parser_modules/common.py` if applicable
* `parsers.py` remains backward-compatible
* no vendor behavior changed
* existing vendor parser tests pass
* known vendor/contact gaps if discovered
* next safe target: vehicle listing parser extraction
* vehicle detail technical parser remains postponed


## Phase D.4 Vehicle Listing Parser Extraction Notes
* vehicle listing parser functions extracted to `parser_modules/vehicle_listing.py`
* `parsers.py` remains backward-compatible
* no vehicle listing behavior changed
* existing listing/category tests pass
* known listing parser gaps if discovered
* next safe target: category parser separation if still mixed, or small detail-label helper extraction
* vehicle detail technical parser remains postponed


## Rejected POC: 0.2s UC Popup Interaction Wait
- Date/context: tested after parser modularization on `poc/performance-and-professionalization-v2`
- Change tested: `time.sleep(1)` -> `time.sleep(0.2)` in `src/scraper/fetchers/uc_popup_fetcher.py`
- Single-container result:
  - 5-vendor capped benchmark
  - run_id: `20260528T191807Z-4b9c4659`
  - 20 vehicles
  - 107.01 seconds
  - 5.35 sec/vehicle
  - 20 detail successes
  - 0 detail failures
- 4-shard result:
  - failed / stalled
  - Docker/Xvfb parallel environment showed `Failed to load vehicle page` warnings
  - no merged output produced
  - patch reverted
- Decision:
  - Reject 0.2s wait for production/4-shard mode
  - Keep stable 1.0s interaction wait
  - Single-container speedup is not enough if 4-shard stability fails
- Future idea:
  - If optimizing again, use adaptive wait/readiness checks instead of fixed 0.2s sleep
  - Validate any timing optimization under 4-shard mode before accepting it


## Phase E Category Traversal Notes
* category parsing vs category traversal distinction: Parsing HTML chips/labels safely isolated in `parser_modules/vehicle_listing.py`; Traversal decision engine remains inside `vehicle_scraper.py` (`_category_sequence_from_current_page`, `collect_vehicle_entries`).
* tests added or verified: `tests/test_category_traversal.py` already thoroughly verifies discovered/all/off modes, `max-cars-per-vendor` behavior, skipped logging, and fallback behaviors. Label regressions (e.g. SemiTrailerTruck) verified via existing parser tests.
* whether pure traversal helper was extracted: No. Decided against extraction to avoid unnecessary risk. Traversal logic heavily depends on class state (`self.category_metadata`, `self.last_category_report`) and browser coordination.
* no behavior changed: Confirmed.
* known category traversal risks: Tight coupling between parsing raw HTML content and controlling `max_cars_per_vendor` loop limits inside the scraper class.
* next safe step: adaptive wait POC design or small detail-label helper extraction


## Phase E Category Traversal Notes
* category parsing vs category traversal distinction: parsing is cleanly isolated in `parser_modules/vehicle_listing.py` (`parse_vehicle_category_options`). Traversal control (`discovered/all/off`) and the `max-cars-per-vendor` halts reside securely in `vehicle_scraper.py` (`_category_sequence_from_current_page`, `collect_vehicle_entries`).
* tests added or verified: Existing `tests/test_category_traversal.py` is comprehensive. It thoroughly verifies discovered/all/off modes, `max-cars-per-vendor` fallback logging, and missing category scenarios.
* whether pure traversal helper was extracted: No. Category flow logic is deeply coupled to scraper state (`self.category_metadata`, `self.last_category_report`) and browser navigation. Safest choice is to leave it integrated.
* no behavior changed: Confirmed.
* known category traversal risks: Tight coupling between parsing raw HTML content and controlling loop limits inside the scraper class.
* next safe step: adaptive wait POC design or small detail-label helper extraction.


## Phase F Adaptive Wait POC Design Notes
* fixed 0.2s wait was rejected because it caused instability in 4-shard Docker/Xvfb validation.
* adaptive readiness-check approach is preferred over fixed `time.sleep()`.
* no runtime code changed yet; design phase only.
* implementation should happen only after test helpers are designed.
* 4-shard validation is mandatory before accepting.
