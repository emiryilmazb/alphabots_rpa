"""
Checkpoint/resume support.

Saves and loads scraping progress so the pipeline can continue
after interruption without re-scraping already-processed items.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("mobile_de.checkpoints")


class CheckpointManager:
    """Manages checkpoint files for resume support."""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.checkpoint_dir / f"{name}.json"

    def save(self, name: str, data: Any) -> None:
        """Save checkpoint data to a JSON file."""
        path = self._path(name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("Checkpoint saved: %s (%d items)", name,
                      len(data) if isinstance(data, (list, dict)) else 1)

    def load(self, name: str) -> Any | None:
        """Load checkpoint data. Returns None if not found."""
        path = self._path(name)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Checkpoint loaded: %s (%d items)", name,
                     len(data) if isinstance(data, (list, dict)) else 1)
        return data

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def get_completed_set(self, name: str) -> set[str]:
        """Load a set of completed item identifiers."""
        data = self.load(name)
        if data is None:
            return set()
        return set(data)

    def add_completed(self, name: str, item_id: str) -> None:
        """Add an item to the completed set and save."""
        completed = self.get_completed_set(name)
        completed.add(item_id)
        self.save(name, list(completed))

    def clear(self, name: str) -> None:
        """Delete a checkpoint file."""
        path = self._path(name)
        if path.exists():
            path.unlink()
            logger.info("Checkpoint cleared: %s", name)

    def clear_all(self) -> None:
        """Delete all checkpoint files in the checkpoint directory."""
        for path in self.checkpoint_dir.glob("*.json"):
            path.unlink()
        logger.info("All checkpoints cleared in %s", self.checkpoint_dir)
