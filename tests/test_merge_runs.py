import os, sys
from unittest.mock import patch, MagicMock
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

def test_merge_duplicate(tmp_path):
    out_dir = str(tmp_path / "merged")
    s0 = "tests/fixtures/shards/shard0"
    s_dup = "tests/fixtures/shards/shard_duplicate"
    with patch.object(sys, 'argv', ['merge_runs.py', '--runs', s0, s_dup, '--output', out_dir]):
        with patch('subprocess.run') as mock_run:
            merge()
    
    ven_dir = os.path.join(out_dir, "raw", "vendors")
    veh_dir = os.path.join(out_dir, "raw", "vehicles")
    # Duplicate vendor C0000001 and URL A are deduplicated.
    assert len(os.listdir(ven_dir)) == 2
    assert len(os.listdir(veh_dir)) == 2
