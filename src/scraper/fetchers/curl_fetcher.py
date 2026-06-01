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

    _curl_cffi_available: bool | None = None  # None = not yet checked

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
        # Short-circuit if curl_cffi was already found unavailable
        if CurlFetcher._curl_cffi_available is False and self._session_factory is None:
            return FetchResult(
                url=url,
                strategy="curl_cffi",
                attempt=attempt,
                elapsed_ms=0,
                error_type="ModuleNotFoundError",
                error_message="curl_cffi unavailable (checked once at startup)",
            )

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
                # Mark as available on first success
                if CurlFetcher._curl_cffi_available is None:
                    CurlFetcher._curl_cffi_available = True
                    logger.info("curl_cffi is available (v%s); using for static fetches.", self._get_version())

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
            except ModuleNotFoundError:
                elapsed = (perf_counter() - started) * 1000
                if CurlFetcher._curl_cffi_available is None:
                    CurlFetcher._curl_cffi_available = False
                    logger.warning(
                        "curl_cffi unavailable; static fast fetch disabled; "
                        "Playwright-only mode will be slower."
                    )
                return FetchResult(
                    url=url,
                    strategy="curl_cffi",
                    attempt=attempt,
                    elapsed_ms=elapsed,
                    error_type="ModuleNotFoundError",
                    error_message="curl_cffi unavailable (checked once at startup)",
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
    def _get_version() -> str:
        try:
            import curl_cffi
            return getattr(curl_cffi, "__version__", "unknown")
        except Exception:
            return "unknown"

    @staticmethod
    def _default_session_factory():
        try:
            from curl_cffi.requests import AsyncSession
        except ImportError:
            if not globals().get('_CURL_WARNING_SHOWN'):
                logger.warning('curl_cffi unavailable; static fast fetch disabled; Playwright-only mode will be slower.')
                globals()['_CURL_WARNING_SHOWN'] = True
            raise ImportError('No module named \'curl_cffi\'')

        return AsyncSession(
            impersonate="chrome120",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": DEFAULT_USER_AGENT,
            },
        )
