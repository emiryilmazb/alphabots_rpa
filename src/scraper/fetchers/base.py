"""Base types for page fetchers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass
class FetchResult:
    """Result metadata for one page fetch attempt."""

    url: str
    final_url: str = ""
    status_code: int | None = None
    html: str = ""
    strategy: str = ""
    browser: str = ""
    attempt: int = 1
    elapsed_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
    screenshot_path: str = ""
    html_dump_path: str = ""
    fetched_at: str = ""
    fallback_reason: str = ""
    classification: str = ""
    detail_status: str = ""
    failure_reason: str = ""
    visible_text_path: str = ""
    extracted_fields_path: str = ""

    def __post_init__(self) -> None:
        if not self.final_url:
            self.final_url = self.url
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()

    @property
    def ok(self) -> bool:
        return not self.error_type and bool(self.html) and (
            self.status_code is None or 200 <= self.status_code < 400
        )


@dataclass
class StaticValidation:
    """Validation outcome for deciding whether static HTML is sufficient."""

    ok: bool
    reason: str = ""


class BaseFetcher(Protocol):
    """Common fetcher interface."""

    async def fetch(self, url: str, *, attempt: int = 1) -> FetchResult:
        """Fetch a URL and return a structured result."""
