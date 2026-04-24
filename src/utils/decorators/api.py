"""Module: utils/decorators/api.py

@log_api_call decorator for FastAPI route handlers.

Extracts correlation_id from the first Request argument's headers
(if present). Logs: method, path, correlation_id, status, duration_ms.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

import structlog

from utils.decorators.helpers import extract_correlation_id
from utils.log_types import LOG_TYPE_ACCESS, LOG_TYPE_ERROR

logger = structlog.get_logger(__name__)


def log_api_call(func: Callable) -> Callable:
    """Log FastAPI route handler entry and exit.

    Extracts correlation_id from the first Request argument's headers
    (if present). Logs: method, path, correlation_id, status,
    duration_ms, and ``log_type="access"`` on the happy path
    (``log_type="error"`` on exception so one CloudWatch filter
    catches all failures).
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = extract_correlation_id(args, kwargs)
        func_name = func.__qualname__

        logger.info(
            "API call started",
            log_type=LOG_TYPE_ACCESS,
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "API call completed",
                log_type=LOG_TYPE_ACCESS,
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "API call failed",
                log_type=LOG_TYPE_ERROR,
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="error",
            )
            raise

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = extract_correlation_id(args, kwargs)
        func_name = func.__qualname__

        logger.info(
            "API call started",
            log_type=LOG_TYPE_ACCESS,
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "API call completed",
                log_type=LOG_TYPE_ACCESS,
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "API call failed",
                log_type=LOG_TYPE_ERROR,
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="error",
            )
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
