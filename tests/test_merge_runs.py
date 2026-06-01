import os
import sys
import json
from unittest.mock import patch
import pytest
from tools.merge_runs import merge


def test_merge_clean(tmp_path):
    out_dir = str(tmp_path / "merged")
    s0 = "tests/fixtures/shards/shard0"
    s1 = "tests/fixtures/shards/shard1"
    with patch.object(
        sys, "argv", ["merge_runs.py", "--runs", s0, s1, "--output", out_dir]
    ):
        with patch("subprocess.run") as mock_run:
            merge()

    ven_dir = os.path.join(out_dir, "raw", "vendors")
    veh_dir = os.path.join(out_dir, "raw", "vehicles")
    assert len(os.listdir(ven_dir)) == 4
    assert len(os.listdir(veh_dir)) == 4

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "docker" in call_args
    assert "--process-existing" in call_args
    assert "--overwrite" in call_args


def test_merge_duplicate(tmp_path):
    out_dir = str(tmp_path / "merged")
    s0 = "tests/fixtures/shards/shard0"
    s_dup = "tests/fixtures/shards/shard_duplicate"
    with patch.object(
        sys, "argv", ["merge_runs.py", "--runs", s0, s_dup, "--output", out_dir]
    ):
        with patch("subprocess.run") as mock_run:
            merge()

    ven_dir = os.path.join(out_dir, "raw", "vendors")
    veh_dir = os.path.join(out_dir, "raw", "vehicles")
    assert len(os.listdir(ven_dir)) == 2
    assert len(os.listdir(veh_dir)) == 2


def test_merge_new_format(tmp_path):
    s0 = tmp_path / "shard0"
    s1 = tmp_path / "shard1"
    out_dir = str(tmp_path / "merged")

    for s in [s0, s1]:
        d = s / "raw"
        d.mkdir(parents=True)

    with open(s0 / "raw" / "vendors_raw.json", "w", encoding="utf-8") as f:
        json.dump([{"haendler_id": "C01"}, {"haendler_id": "C02"}], f)
    with open(s0 / "raw" / "cars_raw.json", "w", encoding="utf-8") as f:
        json.dump([{"url": "U01"}, {"url": "U02"}], f)

    with open(s1 / "raw" / "vendors_raw.json", "w", encoding="utf-8") as f:
        json.dump([{"haendler_id": "C02"}, {"haendler_id": "C03"}], f)
    with open(s1 / "raw" / "cars_raw.json", "w", encoding="utf-8") as f:
        json.dump([{"url": "U02"}, {"url": "U03"}], f)

    with patch.object(
        sys, "argv", ["merge_runs.py", "--runs", str(s0), str(s1), "--output", out_dir]
    ):
        with patch("subprocess.run") as mock_run:
            merge()

    ven_out = os.path.join(out_dir, "raw", "vendors_raw.json")
    car_out = os.path.join(out_dir, "raw", "cars_raw.json")
    assert os.path.exists(ven_out)
    assert os.path.exists(car_out)

    v_data = json.load(open(ven_out))
    c_data = json.load(open(car_out))
    assert len(v_data) == 3
    assert len(c_data) == 3


def test_merge_empty_fails(tmp_path):
    out_dir = str(tmp_path / "merged")
    s0 = tmp_path / "empty_shard"
    s0.mkdir(parents=True)

    with patch.object(
        sys, "argv", ["merge_runs.py", "--runs", str(s0), "--output", out_dir]
    ):
        with pytest.raises(SystemExit) as e:
            merge()
    assert e.value.code == 1


def test_merge_dict_shaped_json(tmp_path):
    import json
    import os
    import subprocess
    import sys

    run_dir = tmp_path / "run1"
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True)
    vendors_dict = {
        "V1": {"haendler_id": "V1", "name": "Vendor 1"},
        "V2": {"name": "Vendor 2"},
    }
    with open(raw_dir / "vendors_raw.json", "w", encoding="utf-8") as f:
        json.dump(vendors_dict, f)
    cars_dict = {"U1": {"url": "U1", "title": "Car 1"}, "U2": {"title": "Car 2"}}
    with open(raw_dir / "cars_raw.json", "w", encoding="utf-8") as f:
        json.dump(cars_dict, f)

    # unsupported shape test
    run_dir2 = tmp_path / "run2"
    raw_dir2 = run_dir2 / "raw"
    raw_dir2.mkdir(parents=True)
    with open(raw_dir2 / "vendors_raw.json", "w", encoding="utf-8") as f:
        json.dump("not a dict or list", f)
    with open(raw_dir2 / "cars_raw.json", "w", encoding="utf-8") as f:
        json.dump(12345, f)

    out_dir = tmp_path / "out"
    res = subprocess.run(
        [
            sys.executable,
            "tools/merge_runs.py",
            "--runs",
            str(run_dir),
            str(run_dir2),
            "--output",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert "Unsupported JSON shape" in res.stderr
    assert os.path.exists(out_dir / "raw" / "vendors_raw.json")
    with open(out_dir / "raw" / "vendors_raw.json", encoding="utf-8") as f:
        merged_v = json.load(f)
    assert len(merged_v) == 2
    assert any(v.get("haendler_id") == "V1" for v in merged_v)

    with open(out_dir / "raw" / "cars_raw.json", encoding="utf-8") as f:
        merged_c = json.load(f)
    assert len(merged_c) == 2
    assert any(c.get("url") == "U1" for c in merged_c)
