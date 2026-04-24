"""Module: utils/decorators/service.py

@log_service_call decorator for service and connector methods.

Logs: function name, key arguments, correlation_id, duration_ms.
Looks for correlation_id in kwargs.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

import structlog

from utils.decorators.helpers import is_known_provider_error
from utils.log_types import LOG_TYPE_ERROR, infer_integration_or_service

logger = structlog.get_logger(__name__)


def log_service_call(func: Callable) -> Callable:
    """Log service/connector method entry and exit.

    Logs: function name, key arguments, correlation_id, duration_ms,
    log_type.

    Emits ``log_type="integration"`` for functions defined under the
    adapter / connector layers (``adapters.*``, ``queues.*``,
    ``storage.*``, ``events.*``, ``db.*``) and ``log_type="service"``
    otherwise. Call sites never need to think about this — the
    decorator inspects ``func.__module__`` at wrap time.

    Error paths emit ``log_type="error"`` regardless, so a single
    CloudWatch filter on ``{ $.log_type = "error" }`` catches every
    failure across both categories.
    """
    # Resolve the log_type once at decoration time so we don't re-run
    # the string prefix check on every call.
    module_name = getattr(func, "__module__", "") or ""
    call_log_type = infer_integration_or_service(module_name)

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = kwargs.get("correlation_id", "")
        func_name = func.__qualname__

        logger.info(
            "Service call started",
            log_type=call_log_type,
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Service call completed",
                log_type=call_log_type,
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            if is_known_provider_error(exc):
                # Clean one-line warning — no traceback. The LLM Gateway
                # will handle the fallback to the secondary provider.
                logger.warning(
                    "Service call failed (known provider error)",
                    log_type=LOG_TYPE_ERROR,
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "Service call failed",
                    log_type=LOG_TYPE_ERROR,
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

        logger.info(
            "Service call started",
            log_type=call_log_type,
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Service call completed",
                log_type=call_log_type,
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            if is_known_provider_error(exc):
                logger.warning(
                    "Service call failed (known provider error)",
                    log_type=LOG_TYPE_ERROR,
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "Service call failed",
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
