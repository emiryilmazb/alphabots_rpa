SEARCH_BASE = "https://suchen.mobile.de"
import re
from typing import Any
from urllib.parse import urlparse, urlunparse


def clean_text(value: Any) -> str:
    """Normalize whitespace while preserving German characters."""
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_dealer_url(url: str) -> str:
    """Normalize a mobile.de dealer URL to a stable, query-free homepage URL."""
    if not url:
        return ""
    url = url.strip().strip('"').strip("'")
    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("/"):
        url = urljoin(HOME_BASE, url)
    elif not url.startswith("http"):
        url = f"{HOME_BASE}/{url.lstrip('/')}"

    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != "home.mobile.de":
        return url
    parts = [part for part in parsed.path.split("/") if part]
    path = f"/{parts[0].upper()}" if len(parts) == 1 else parsed.path.rstrip("/")
    return urlunparse(("https", "home.mobile.de", path, "", "", ""))


def normalize_vehicle_url(url: str) -> str:
    """Normalize a vehicle URL or listing id to an absolute detail URL."""
    url = clean_text(url)
    if not url:
        return ""
    if url.isdigit():
        return f"{SEARCH_BASE}/fahrzeuge/details.html?id={url}"
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(SEARCH_BASE, url)
    if not url.startswith("http"):
        return f"https://{url}"
    return url


def dealer_identifier(url: str) -> str:
    """Return the stable slug/customer id part from a dealer URL."""
    parsed = urlparse(normalize_dealer_url(url))
    return parsed.path.strip("/").split("/")[0]
