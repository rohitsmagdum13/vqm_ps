"""Module: utils/decorators/policy.py

@log_policy_decision decorator for confidence checks and routing decisions.

Expects the wrapped function to return a dict with a 'decision'
key describing the outcome (e.g., "path_a", "path_c", "route_to_team_x").
Logs: threshold, actual_value, decision, correlation_id.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


def log_policy_decision(func: Callable) -> Callable:
    """Log confidence checks and routing decisions.

    Expects the wrapped function to return a dict with a 'decision'
    key describing the outcome (e.g., "path_a", "path_c", "route_to_team_x").
    Logs: threshold, actual_value, decision, correlation_id.
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = kwargs.get("correlation_id", "")
        func_name = func.__qualname__

        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000

            log_kwargs: dict[str, Any] = {
                "function": func_name,
                "correlation_id": correlation_id,
                "duration_ms": round(duration_ms, 2),
                "status": "success",
            }
            if isinstance(result, dict):
                log_kwargs["decision"] = result.get("decision", "unknown")
                log_kwargs["threshold"] = result.get("threshold")
                log_kwargs["actual_value"] = result.get("actual_value")

            logger.info("Policy decision made", **log_kwargs)
            return result
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "Policy decision failed",
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="error",
            )
            raise

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = kwargs.get("correlation_id", "")
        func_name = func.__qualname__

        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000

            log_kwargs: dict[str, Any] = {
                "function": func_name,
                "correlation_id": correlation_id,
                "duration_ms": round(duration_ms, 2),
                "status": "success",
            }
            if isinstance(result, dict):
                log_kwargs["decision"] = result.get("decision", "unknown")
                log_kwargs["threshold"] = result.get("threshold")
                log_kwargs["actual_value"] = result.get("actual_value")

            logger.info("Policy decision made", **log_kwargs)
            return result
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "Policy decision failed",
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="error",
            )
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
