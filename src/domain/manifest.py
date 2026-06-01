from typing import Dict, Any, Optional
from datetime import datetime

def build_run_manifest(
    run_id: str,
    git_commit: str,
    state: str,
    browser_mode: str,
    detail_open_strategy: str,
    shard_index: int,
    shard_count: int,
    max_vendors: Optional[int],
    max_cars_per_vendor: Optional[int],
    config_summary: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "git_commit": git_commit,
        "state": state,
        "browser_mode": browser_mode,
        "detail_open_strategy": detail_open_strategy,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "max_vendors": max_vendors,
        "max_cars_per_vendor": max_cars_per_vendor,
        "started_at": datetime.utcnow().isoformat(),
        "config_summary": config_summary
    }
