import os, sys, json
from unittest.mock import patch, MagicMock
import pytest
from tools.merge_runs import merge

def test_merge_clean(tmp_path):
    out_dir = str(tmp_path / "merged")
    s0 = "tests/fixtures/shards/shard0"
    s1 = "tests/fixtures/shards/shard1"
    with patch.object(sys, 'argv', ['merge_runs.py', '--runs', s0, s1, '--output', out_dir]):
        with patch('subprocess.run') as mock_run:
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
    with patch.object(sys, 'argv', ['merge_runs.py', '--runs', s0, s_dup, '--output', out_dir]):
        with patch('subprocess.run') as mock_run:
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

    with patch.object(sys, 'argv', ['merge_runs.py', '--runs', str(s0), str(s1), '--output', out_dir]):
        with patch('subprocess.run') as mock_run:
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
    
    with patch.object(sys, 'argv', ['merge_runs.py', '--runs', str(s0), '--output', out_dir]):
        with pytest.raises(SystemExit) as e:
            merge()
    assert e.value.code == 1
