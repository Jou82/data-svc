"""
Retry com backoff para operações de banco (pooler / conexões ociosas).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import psycopg2

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_S = 0.25


def run_db_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = _DEFAULT_ATTEMPTS,
    base_delay_s: float = _DEFAULT_BASE_DELAY_S,
    operation: str = "db",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            delay = base_delay_s * (2 ** (attempt - 1))
            logger.warning(
                "db_retry operational_error op=%s attempt=%s/%s delay_s=%.2f err=%s",
                operation,
                attempt,
                max_attempts,
                delay,
                exc,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc
