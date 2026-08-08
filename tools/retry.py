"""Retry wrapper for flaky tool calls (transient network or IO errors)."""

from __future__ import annotations

import time
from typing import Any, Callable


def with_retry(
    func: Callable[[], Any],
    attempts: int = 3,
    backoff: float = 0.2,
    errors: type[BaseException] | tuple[type[BaseException], ...] = Exception,
) -> tuple[Any, int]:
    """Run ``func`` with exponential backoff.

    Returns ``(result, attempts_used)``. The last failure is re-raised, so
    callers can fall back to degraded behaviour.
    """

    if attempts < 1:
        raise ValueError("attempts must be positive")

    for attempt in range(1, attempts + 1):
        try:
            return func(), attempt
        except errors:
            if attempt == attempts:
                raise
            time.sleep(backoff * 2 ** (attempt - 1))
    raise RuntimeError("unreachable")
