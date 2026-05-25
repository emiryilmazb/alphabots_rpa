"""Fetch strategy abstraction for static and browser-backed page loads."""

from src.scraper.fetchers.base import BaseFetcher, FetchResult, StaticValidation
from src.scraper.fetchers.curl_fetcher import CurlFetcher
from src.scraper.fetchers.playwright_fetcher import PlaywrightFetcher
from src.scraper.fetchers.strategy_manager import FetchStrategyManager

__all__ = [
    "BaseFetcher",
    "CurlFetcher",
    "FetchResult",
    "FetchStrategyManager",
    "PlaywrightFetcher",
    "StaticValidation",
]
