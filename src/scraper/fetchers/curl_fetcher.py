"""curl_cffi-backed static HTML fetcher."""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any, Callable

from src.config import ScraperConfig
from src.scraper.browser import DEFAULT_USER_AGENT
from src.scraper.fetchers.base import FetchResult

logger = logging.getLogger("mobile_de.fetchers.curl")


class CurlFetcher:
    """Fetch static HTML with curl_cffi and browser-like headers."""

    def __init__(
        self,
        config: ScraperConfig,
        *,
        session_factory: Callable[..., Any] | None = None,
    ):
        self.config = config
        self._session_factory = session_factory
        self._semaphore = asyncio.Semaphore(config.curl_concurrency)

    async def fetch(self, url: str, *, attempt: int = 1) -> FetchResult:
        started = perf_counter()
        async with self._semaphore:
            try:
                session_factory = self._session_factory or self._default_session_factory
                async with session_factory() as session:
                    response = await session.get(
                        url,
                        allow_redirects=True,
                        timeout=45,
                    )
                elapsed = (perf_counter() - started) * 1000
                html = getattr(response, "text", "") or ""
                status_code = getattr(response, "status_code", None)
                final_url = str(getattr(response, "url", url) or url)
                if status_code is not None and int(status_code) >= 400:
                    return FetchResult(
                        url=url,
                        final_url=final_url,
                        status_code=int(status_code),
                        html=html,
                        strategy="curl_cffi",
                        attempt=attempt,
                        elapsed_ms=elapsed,
                        error_type="http_error",
                        error_message=f"HTTP {status_code}",
                    )
                return FetchResult(
                    url=url,
                    final_url=final_url,
                    status_code=int(status_code) if status_code is not None else None,
                    html=html,
                    strategy="curl_cffi",
                    attempt=attempt,
                    elapsed_ms=elapsed,
                )
            except Exception as exc:
                elapsed = (perf_counter() - started) * 1000
                logger.debug("curl_cffi fetch failed for %s: %s", url, exc)
                return FetchResult(
                    url=url,
                    strategy="curl_cffi",
                    attempt=attempt,
                    elapsed_ms=elapsed,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )

    @staticmethod
    def _default_session_factory():
        from curl_cffi.requests import AsyncSession

        return AsyncSession(
            impersonate="chrome120",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": DEFAULT_USER_AGENT,
            },
        )
