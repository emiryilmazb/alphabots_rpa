import os, subprocess, time, glob, sys, argparse

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="nordrhein-westfalen")
    parser.add_argument("--max-vendors", type=int, default=100)
    parser.add_argument("--max-cars-per-vendor", type=int, default=10)
    parser.add_argument("--shard-count", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output-root", default="data_shards")
    parser.add_argument("--clean", action="store_true", default=True)
    parser.add_argument("--uc-wait-profile", default="safe")
    parser.add_argument("--uc-block-resources", default="false")
    parser.add_argument("--merge-output", default="data/merged/final_sharded_run")
    args = parser.parse_args()

    if args.shard_count >= 8 and not args.force:
        print("ERROR: 8-shard failed on this host due to RAM limits. Use --force to override.")
        sys.exit(1)

    base = os.getcwd()
    if args.clean:
        subprocess.run("docker rm -f $(docker ps -aq)", shell=True, capture_output=True)
        subprocess.run("taskkill /F /IM chromedriver.exe /T", shell=True, capture_output=True)

    procs = []
    t0 = time.time()
    for i in range(args.shard_count):
        shard_data = os.path.join(args.output_root, f"shard_{i}")
        shard_logs = os.path.join("logs_shards", f"shard_{i}")
        os.makedirs(shard_data, exist_ok=True)
        os.makedirs(shard_logs, exist_ok=True)

        cmd = (f'docker compose -p mobilede_shard_{i} run --rm '
               f'-v "{base}\\{shard_data}:/app/data" -v "{base}\\{shard_logs}:/app/logs" '
               f'-e VENDOR_SHARD_INDEX={i} -e VENDOR_SHARD_COUNT={args.shard_count} '
               f'-e UC_BLOCK_RESOURCES=true -e BROWSER_MODE=xvfb scraper python -m src.main '
        f'--uc-wait-profile {args.uc_wait_profile} '
        f'--uc-block-resources {args.uc_block_resources} '
               f'--state {args.state} --pipeline-mode sqlite --browser-mode xvfb '
               f'--fetch-strategy auto --detail-policy missing-required --detail-open-strategy uc-popup '
               f'--detail-max-retries 1 --max-vendors {args.max_vendors} --max-cars-per-vendor {args.max_cars_per_vendor} '
               f'--vendor-concurrency 1 --vehicle-detail-concurrency 1 --benchmark --clean-run true')
        procs.append(subprocess.Popen(["powershell", "-Command", cmd]))

    for p in procs: p.wait()
    wall_clock = time.time() - t0

    run_dirs = []
    for i in range(args.shard_count):
        shard_data = os.path.join(args.output_root, f"shard_{i}")
        rs = sorted(glob.glob(os.path.join(shard_data, "runs", "*")), key=os.path.getmtime, reverse=True)
        if rs: run_dirs.append(rs[0])

    venv_python = os.path.join(base, "venv", "Scripts", "python.exe")
    if len(run_dirs) == args.shard_count:
        p_merge = subprocess.run([venv_python, "tools/merge_runs.py", "--runs"] + run_dirs + ["--output", args.merge_output])
        print("Merge successful." if p_merge.returncode == 0 else "Merge failed.")
    
    print(f"Merge output folder: {args.merge_output}")

if __name__ == "__main__":
    main()
