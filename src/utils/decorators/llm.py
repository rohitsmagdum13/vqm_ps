"""Module: utils/decorators/llm.py

@log_llm_call decorator for LLM factory functions.

Expects the wrapped function to return a dict containing:
tokens_in, tokens_out, cost_usd, model_id (added by the Bedrock connector).
Logs: model, prompt_id, tokens, cost, latency_ms.
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

import structlog

from utils.decorators.helpers import is_known_provider_error
from utils.log_types import LOG_TYPE_ERROR, LOG_TYPE_LLM

logger = structlog.get_logger(__name__)


def log_llm_call(func: Callable) -> Callable:
    """Log LLM call entry and exit with token/cost details.

    Expects the wrapped function to return a dict containing:
    tokens_in, tokens_out, cost_usd, model_id (added by the Bedrock
    connector). Logs: model, prompt_id, tokens, cost, latency_ms, and
    ``log_type="llm"`` on the happy path. Failure paths emit
    ``log_type="error"`` so a single filter catches every fault.
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = kwargs.get("correlation_id", "")
        func_name = func.__qualname__

        logger.info(
            "LLM call started",
            log_type=LOG_TYPE_LLM,
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000

            # Extract LLM-specific metrics from the result if it's a dict
            log_kwargs: dict[str, Any] = {
                "log_type": LOG_TYPE_LLM,
                "function": func_name,
                "correlation_id": correlation_id,
                "duration_ms": round(duration_ms, 2),
                "status": "success",
            }
            if isinstance(result, dict):
                log_kwargs["tokens_in"] = result.get("tokens_in", 0)
                log_kwargs["tokens_out"] = result.get("tokens_out", 0)
                log_kwargs["cost_usd"] = result.get("cost_usd", 0.0)
                log_kwargs["model_id"] = result.get("model_id", "unknown")

            logger.info("LLM call completed", **log_kwargs)
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            if is_known_provider_error(exc):
                # Clean one-line warning — no traceback. The LLM Gateway
                # will handle the fallback to the secondary provider.
                logger.warning(
                    "LLM call failed (known provider error)",
                    log_type=LOG_TYPE_ERROR,
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "LLM call failed",
                    log_type=LOG_TYPE_ERROR,
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    status="error",
                )
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper

    # LLM calls are always async in VQMS, but handle sync as a fallback
    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = kwargs.get("correlation_id", "")
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "LLM call completed",
                log_type=LOG_TYPE_LLM,
                function=func.__qualname__,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            if is_known_provider_error(exc):
                logger.warning(
                    "LLM call failed (known provider error)",
                    log_type=LOG_TYPE_ERROR,
                    function=func.__qualname__,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "LLM call failed",
                    log_type=LOG_TYPE_ERROR,
                    function=func.__qualname__,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    status="error",
                )
            raise

    return sync_wrapper
