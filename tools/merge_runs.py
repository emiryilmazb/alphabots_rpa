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
    seen_vid = set(); seen_url = set(); t_ven = 0; t_veh = 0
    for run in args.runs:
        for vf in glob.glob(os.path.join(run, "raw", "vendors", "*.json")):
            vid = json.load(open(vf, encoding='utf-8')).get('haendler_id')
            if vid and vid not in seen_vid:
                seen_vid.add(vid)
                shutil.copy(vf, os.path.join(raw_dir, "vendors", os.path.basename(vf)))
                t_ven += 1
        for cf in glob.glob(os.path.join(run, "raw", "vehicles", "*.json")):
            url = json.load(open(cf, encoding='utf-8')).get('url')
            if url and url not in seen_url:
                seen_url.add(url)
                shutil.copy(cf, os.path.join(raw_dir, "vehicles", os.path.basename(cf)))
                t_veh += 1
    out_docker = f"/app/data/merged/{os.path.basename(args.output)}/output"
    in_docker = f"/app/data/merged/{os.path.basename(args.output)}/raw"
    print(f"Merged {t_ven} vendors and {t_veh} vehicles.")
    subprocess.run(["docker", "compose", "run", "--rm", "scraper", "python", "-m", "src.main", "--state", "nordrhein-westfalen", "--pipeline-mode", "sqlite", "--process-existing", "--input-dir", in_docker, "--output-dir", out_docker])
if __name__ == '__main__':
    merge()
