$ErrorActionPreference = "Stop"
Write-Host "Starting Shard 0..."
$job0 = Start-Job { Set-Location $env:WORKING_DIR; docker compose run --rm -e BROWSER_MODE=xvfb scraper python -m src.main --state nordrhein-westfalen --pipeline-mode sqlite --browser-mode xvfb --fetch-strategy auto --detail-policy missing-required --detail-open-strategy uc-popup --detail-max-retries 1 --max-vendors 25 --max-cars-per-vendor 10 --vendor-concurrency 1 --vehicle-detail-concurrency 1 --benchmark --clean-run false --uc-block-resources true --vendor-shard-index 0 --vendor-shard-count 2 } -Environment @{WORKING_DIR=(Get-Location).Path}
Start-Sleep -Seconds 10
Write-Host "Starting Shard 1..."
$job1 = Start-Job { Set-Location $env:WORKING_DIR; docker compose run --rm -e BROWSER_MODE=xvfb scraper python -m src.main --state nordrhein-westfalen --pipeline-mode sqlite --browser-mode xvfb --fetch-strategy auto --detail-policy missing-required --detail-open-strategy uc-popup --detail-max-retries 1 --max-vendors 25 --max-cars-per-vendor 10 --vendor-concurrency 1 --vehicle-detail-concurrency 1 --benchmark --clean-run false --uc-block-resources true --vendor-shard-index 1 --vendor-shard-count 2 } -Environment @{WORKING_DIR=(Get-Location).Path}
Wait-Job $job0, $job1
$runs = Get-ChildItem -Path data/runs -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 2
$run1 = $runs[0].FullName; $run2 = $runs[1].FullName
$mergeId = "merged_" + (Get-Date -Format "yyyyMMddTHHmmssZ")
venv\Scripts\python.exe tools/merge_runs.py --runs $run1 $run2 --output "data/merged/$mergeId"
Write-Host "All done!"
