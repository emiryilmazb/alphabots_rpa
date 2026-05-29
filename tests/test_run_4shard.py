import os, sys
from unittest.mock import patch, MagicMock
import run_4shard

def test_cli_parsing_and_command_construction():
    test_args = [
        'run_4shard.py',
        '--state', 'test-state',
        '--max-vendors', '0',
        '--max-cars-per-vendor', '0',
        '--shard-count', '2',
        '--clean'
    ]
    with patch.object(sys, 'argv', test_args):
        with patch('subprocess.Popen') as mock_popen, patch('subprocess.run') as mock_run:
            mock_process = MagicMock()
            mock_popen.return_value = mock_process
            
            mock_run_result = MagicMock()
            mock_run_result.returncode = 0
            mock_run.return_value = mock_run_result
            
            with patch('glob.glob', return_value=['fake_run_dir']):
                with patch('os.path.getmtime', return_value=1.0):
                    run_4shard.main()
                
    cleanup_calls = [c[0][0] for c in mock_run.call_args_list if isinstance(c[0][0], str) and "docker rm" in c[0][0]]
    assert len(cleanup_calls) > 0
    
    assert mock_popen.call_count == 2
    
    cmd0 = mock_popen.call_args_list[0][0][0][2]
    cmd1 = mock_popen.call_args_list[1][0][0][2]
    
    for cmd in [cmd0, cmd1]:
        assert "uc-popup" in cmd
        assert "xvfb" in cmd
        assert "UC_BLOCK_RESOURCES=true" in cmd
        assert "--max-vendors 0" in cmd
        assert "--max-cars-per-vendor 0" in cmd
        
    assert "VENDOR_SHARD_INDEX=0" in cmd0
    assert "VENDOR_SHARD_INDEX=1" in cmd1
    assert "mobilede_shard_0" in cmd0
    assert "mobilede_shard_1" in cmd1
    assert "shard_0:/app/data" in cmd0.replace('\\', '/')
    assert "shard_1:/app/data" in cmd1.replace('\\', '/')

def test_merge_sequencing():
    test_args = ['run_4shard.py', '--shard-count', '2']
    with patch.object(sys, 'argv', test_args):
        with patch('subprocess.Popen') as mock_popen, patch('subprocess.run') as mock_run:
            # Simulate only 1 shard returning a run directory
            with patch('glob.glob', side_effect=[['fake_dir_0'], []]):
                with patch('os.path.getmtime', return_value=1.0):
                    run_4shard.main()
                
    merge_calls = [c for c in mock_run.call_args_list if isinstance(c[0][0], list) and "tools/merge_runs.py" in c[0][0]]
    assert len(merge_calls) == 0