from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class DetailFetchStatus:
    success: bool = False
    blocked: bool = False
    redirected: bool = False
    error_message: Optional[str] = None


@dataclass
class DetailFetchResult:
    status: DetailFetchStatus
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ShardRunResult:
    shard_index: int
    total_vendors: int = 0
    total_vehicles: int = 0
    success: bool = True


@dataclass
class MergeRunResult:
    total_merged_vendors: int = 0
    total_merged_vehicles: int = 0
    output_path: str = ""


@dataclass
class CoverageFieldResult:
    field_name: str
    coverage_percentage: float = 0.0


@dataclass
class RunManifest:
    run_id: str
    git_commit: str
    state: str
    browser_mode: str
    shard_index: int = 0
    shard_count: int = 1
