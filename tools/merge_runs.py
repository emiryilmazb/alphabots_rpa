import argparse, os, shutil, glob, subprocess, json, sys

def merge() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', nargs='+', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    
    os.makedirs(args.output, exist_ok=True)
    raw_dir = os.path.join(args.output, "raw")
    os.makedirs(os.path.join(raw_dir, "vendors"), exist_ok=True)
    os.makedirs(os.path.join(raw_dir, "vehicles"), exist_ok=True)
    
    seen_vid = set()
    seen_url = set()
    merged_vendors = []
    merged_cars = []
    t_ven = 0
    t_veh = 0
    
    for run in args.runs:
        ven_raw = os.path.join(run, "raw", "vendors_raw.json")
        if os.path.exists(ven_raw):
            try:
                with open(ven_raw, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        vid = item.get('haendler_id')
                        if vid and vid not in seen_vid:
                            seen_vid.add(vid)
                            merged_vendors.append(item)
                            t_ven += 1
            except Exception as e:
                print(f"Error reading {ven_raw}: {e}", file=sys.stderr)
        
        for car_name in ["cars_raw.json", "vehicles_raw.json"]:
            car_raw = os.path.join(run, "raw", car_name)
            if os.path.exists(car_raw):
                try:
                    with open(car_raw, encoding='utf-8') as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            url = item.get('url')
                            if url and url not in seen_url:
                                seen_url.add(url)
                                merged_cars.append(item)
                                t_veh += 1
                except Exception as e:
                    print(f"Error reading {car_raw}: {e}", file=sys.stderr)
        
        for vf in glob.glob(os.path.join(run, "raw", "vendors", "*.json")):
            try:
                with open(vf, encoding='utf-8') as f:
                    item = json.load(f)
                vid = item.get('haendler_id')
                if vid and vid not in seen_vid:
                    seen_vid.add(vid)
                    merged_vendors.append(item)
                    shutil.copy(vf, os.path.join(raw_dir, "vendors", os.path.basename(vf)))
                    t_ven += 1
            except Exception: pass
            
        for cf in glob.glob(os.path.join(run, "raw", "vehicles", "*.json")):
            try:
                with open(cf, encoding='utf-8') as f:
                    item = json.load(f)
                url = item.get('url')
                if url and url not in seen_url:
                    seen_url.add(url)
                    merged_cars.append(item)
                    shutil.copy(cf, os.path.join(raw_dir, "vehicles", os.path.basename(cf)))
                    t_veh += 1
            except Exception: pass

    if t_ven == 0 and t_veh == 0:
        print("Error: Merged 0 vendors and 0 vehicles. No valid data found in provided runs.", file=sys.stderr)
        sys.exit(1)
        
    if merged_vendors:
        with open(os.path.join(raw_dir, "vendors_raw.json"), "w", encoding="utf-8") as f:
            json.dump(merged_vendors, f, indent=2, ensure_ascii=False)
    if merged_cars:
        with open(os.path.join(raw_dir, "cars_raw.json"), "w", encoding="utf-8") as f:
            json.dump(merged_cars, f, indent=2, ensure_ascii=False)

    out_docker = f"/app/data/merged/{os.path.basename(args.output)}/output"
    in_docker = f"/app/data/merged/{os.path.basename(args.output)}/raw"
    print(f"Merged {t_ven} vendors and {t_veh} vehicles.")
    subprocess.run(["docker", "compose", "run", "--rm", "scraper", "python", "-m", "src.main", "--state", "nordrhein-westfalen", "--pipeline-mode", "sqlite", "--process-existing", "--overwrite", "--input-dir", in_docker, "--output-dir", out_docker])

if __name__ == '__main__':
    merge()
