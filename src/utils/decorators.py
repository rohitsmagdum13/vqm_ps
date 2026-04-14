"""Module: utils/decorators.py

Logging decorators for VQMS.

Four decorators that eliminate boilerplate logging across the codebase.
Each handles both sync and async functions transparently. All use
structlog directly with keyword arguments (no extra={} dicts).

Usage:
    @log_api_call
    async def submit_query(request: Request):
        ...

    @log_service_call
    async def fetch_vendor(vendor_id: str, *, correlation_id: str):
        ...
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable

import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger(__name__)

# Exceptions that indicate a known provider failure (e.g., Bedrock model
# unavailable, access denied). These are expected when the LLM Gateway
# falls back to a secondary provider, so we log a clean warning instead
# of dumping the full traceback.
_KNOWN_PROVIDER_ERRORS = (
    "BedrockTimeoutError",
    "LLMProviderError",
)


def _is_known_provider_error(exc: Exception) -> bool:
    """Return True if this is an expected LLM provider error.

    Known provider errors get a clean one-line warning instead of a
    full traceback, because the LLM Gateway will handle the fallback.
    """
    if isinstance(exc, ClientError):
        return True
    return type(exc).__name__ in _KNOWN_PROVIDER_ERRORS


def log_api_call(func: Callable) -> Callable:
    """Log FastAPI route handler entry and exit.

    Extracts correlation_id from the first Request argument's headers
    (if present). Logs: method, path, correlation_id, status, duration_ms.
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        # Try to extract correlation_id from Request object
        correlation_id = _extract_correlation_id(args, kwargs)
        func_name = func.__qualname__

        logger.info(
            "API call started",
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "API call completed",
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
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="error",
            )
            raise

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = _extract_correlation_id(args, kwargs)
        func_name = func.__qualname__

        logger.info(
            "API call started",
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "API call completed",
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
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="error",
            )
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def log_service_call(func: Callable) -> Callable:
    """Log service/connector method entry and exit.

    Logs: function name, key arguments, correlation_id, duration_ms.
    Looks for correlation_id in kwargs.
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = kwargs.get("correlation_id", "")
        func_name = func.__qualname__

        logger.info(
            "Service call started",
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Service call completed",
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            if _is_known_provider_error(exc):
                # Clean one-line warning — no traceback. The LLM Gateway
                # will handle the fallback to the secondary provider.
                logger.warning(
                    "Service call failed (known provider error)",
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "Service call failed",
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
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Service call completed",
                function=func_name,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            if _is_known_provider_error(exc):
                logger.warning(
                    "Service call failed (known provider error)",
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "Service call failed",
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    status="error",
                )
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def log_llm_call(func: Callable) -> Callable:
    """Log LLM call entry and exit with token/cost details.

    Expects the wrapped function to return a dict containing:
    tokens_in, tokens_out, cost_usd, model_id (added by the Bedrock connector).
    Logs: model, prompt_id, tokens, cost, latency_ms.
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        correlation_id = kwargs.get("correlation_id", "")
        func_name = func.__qualname__

        logger.info(
            "LLM call started",
            function=func_name,
            correlation_id=correlation_id,
        )
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000

            # Extract LLM-specific metrics from the result if it's a dict
            log_kwargs: dict[str, Any] = {
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
            if _is_known_provider_error(exc):
                # Clean one-line warning — no traceback. The LLM Gateway
                # will handle the fallback to the secondary provider.
                logger.warning(
                    "LLM call failed (known provider error)",
                    function=func_name,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "LLM call failed",
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
                function=func.__qualname__,
                correlation_id=correlation_id,
                duration_ms=round(duration_ms, 2),
                status="success",
            )
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            if _is_known_provider_error(exc):
                logger.warning(
                    "LLM call failed (known provider error)",
                    function=func.__qualname__,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            else:
                logger.exception(
                    "LLM call failed",
                    function=func.__qualname__,
                    correlation_id=correlation_id,
                    duration_ms=round(duration_ms, 2),
                    status="error",
                )
            raise

    return sync_wrapper


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


def _extract_correlation_id(args: tuple, kwargs: dict) -> str:
    """Try to extract correlation_id from a FastAPI Request in args or kwargs."""
    # Check kwargs first
    if "correlation_id" in kwargs:
        return kwargs["correlation_id"]

    # Check for a Request object in args (FastAPI route handlers)
    for arg in args:
        if hasattr(arg, "headers"):
            return arg.headers.get("X-Correlation-ID", "")

    return ""
