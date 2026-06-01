import pytest
from unittest.mock import patch
from src.config import parse_args

def test_process_existing_flag():
    with patch("sys.argv", ["main.py", "--process-existing"]):
        config = parse_args()
        assert config.process_existing is True

def test_benchmark_flag():
    with patch("sys.argv", ["main.py", "--benchmark"]):
        config = parse_args()
        assert config.benchmark is True
