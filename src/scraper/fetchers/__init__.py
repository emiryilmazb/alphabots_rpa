"""Fetch strategy abstraction for static and browser-backed page loads."""

from src.scraper.fetchers.base import BaseFetcher, FetchResult, StaticValidation
from src.scraper.fetchers.curl_fetcher import CurlFetcher
from src.scraper.fetchers.host_chrome_cdp_fetcher import HostChromeCdpFetcher
from src.scraper.fetchers.playwright_fetcher import PlaywrightFetcher
from src.scraper.fetchers.strategy_manager import FetchStrategyManager
from src.scraper.fetchers.uc_popup_fetcher import (
    UcPopupFetcher,
    UcPopupResult,
    vehicle_id_from_url,
)

__all__ = [
    "BaseFetcher",
    "CurlFetcher",
    "FetchResult",
    "FetchStrategyManager",
    "HostChromeCdpFetcher",
    "PlaywrightFetcher",
    "StaticValidation",
]
