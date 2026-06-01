"""
Retry decorator with exponential backoff for flaky network operations.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Callable, Type

logger = logging.getLogger("mobile_de.retry")


def async_retry(
    max_retries: int = 3,
    delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
):
    """
    Async retry decorator with exponential backoff.

    Args:
        max_retries: Number of retry attempts.
        delay: Initial delay between retries (seconds).
        backoff: Multiplier applied to delay after each retry.
        exceptions: Tuple of exception types to catch and retry.
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        logger.warning(
                            "Attempt %d/%d for %s failed: %s. Retrying in %.1fs.",
                            attempt,
                            max_retries,
                            func.__name__,
                            e,
                            current_delay,
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            "All %d attempts for %s failed. Last error: %s",
                            max_retries,
                            func.__name__,
                            e,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
