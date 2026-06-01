from __future__ import annotations
import json
import logging
import re
from typing import Any
from typing import Iterator
from src.scraper.parser_modules.normalization import clean_text

logger = logging.getLogger(__name__)


def extract_next_payloads(html: str) -> list[Any]:
    """
    Extract JSON payloads pushed through ``self.__next_f.push`` scripts.

    mobile.de dealer pages put important structured data (dealerData,
    listingId, legalData, result counts) in these payloads. The outer script is
    JavaScript, but the push argument itself is a JSON array; the second array
    element is often another JSON value prefixed by an internal id like ``29:``.
    """
    payloads: list[Any] = []
    scripts = re.findall(
        r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I)
    for script in scripts:
        script = script.strip()
        if not script.startswith("self.__next_f.push("):
            continue
        inner = script[len("self.__next_f.push("):]
        if inner.endswith(");"):
            inner = inner[:-2]
        elif inner.endswith(")"):
            inner = inner[:-1]
        try:
            outer = json.loads(inner)
        except json.JSONDecodeError:
            continue
        payloads.append(outer)
        if isinstance(outer, list) and len(outer) > 1 and isinstance(outer[1], str):
            text = outer[1]
            _, sep, value = text.partition(":")
            candidate = value if sep and value[:1] in "[{" else text
            if candidate[:1] in "[{":
                try:
                    payloads.append(json.loads(candidate))
                except json.JSONDecodeError:
                    pass
    return payloads


def walk_json(value: Any) -> Iterator[Any]:
    """Yield every nested JSON-like value."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def iter_dicts(value: Any) -> Iterator[dict[str, Any]]:
    for item in walk_json(value):
        if isinstance(item, dict):
            yield item


def _none_if_placeholder(value: Any) -> str:
    text = clean_text(value)
    return "" if text in {"$undefined", "undefined", "None", "null"} else text


def _first_present(*values: Any) -> str:
    for value in values:
        cleaned = _none_if_placeholder(value)
        if cleaned:
            return cleaned
    return ""
