"""
Logging utilities for the scraper.

Configures both console and file logging with structured formatting.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """
    Set up the root logger with console and file handlers.

    Args:
        log_dir: Directory where log files are written.
        level: Logging level.

    Returns:
        Configured root logger.
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"scraper_{timestamp}.log"

    # Root logger
    logger = logging.getLogger("mobile_de")
    logger.setLevel(level)
    logger.propagate = False

    # Prevent duplicate handlers on re-init
    if logger.handlers:
        return logger

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console.setFormatter(console_fmt)
    logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-25s | %(funcName)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    logger.info("Logging initialized -> %s", log_file)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the mobile_de namespace."""
    return logging.getLogger(f"mobile_de.{name}")
