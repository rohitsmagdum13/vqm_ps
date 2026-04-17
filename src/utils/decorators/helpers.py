"""Module: utils/decorators/helpers.py

Shared helpers for the logging decorators.

Contains correlation_id extraction and known-error detection
used by multiple decorator modules.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

# Exceptions that indicate a known provider failure (e.g., Bedrock model
# unavailable, access denied). These are expected when the LLM Gateway
# falls back to a secondary provider, so we log a clean warning instead
# of dumping the full traceback.
_KNOWN_PROVIDER_ERRORS = (
    "BedrockTimeoutError",
    "LLMProviderError",
)


def is_known_provider_error(exc: Exception) -> bool:
    """Return True if this is an expected LLM provider error.

    Known provider errors get a clean one-line warning instead of a
    full traceback, because the LLM Gateway will handle the fallback.
    """
    if isinstance(exc, ClientError):
        return True
    return type(exc).__name__ in _KNOWN_PROVIDER_ERRORS


def extract_correlation_id(args: tuple, kwargs: dict) -> str:
    """Try to extract correlation_id from a FastAPI Request in args or kwargs."""
    # Check kwargs first
    if "correlation_id" in kwargs:
        return kwargs["correlation_id"]

    # Check for a Request object in args (FastAPI route handlers)
    for arg in args:
        if hasattr(arg, "headers"):
            return arg.headers.get("X-Correlation-ID", "")

    return ""
