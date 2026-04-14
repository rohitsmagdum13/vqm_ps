"""Module: utils/exceptions.py

Domain-specific exceptions for VQMS.

Every exception stores context fields as attributes so they
can be included in structured log output. All exceptions
inherit from VQMSError, which carries a correlation_id
for tracing through the pipeline.

Usage:
    from utils.exceptions import DuplicateQueryError

    raise DuplicateQueryError(
        message_id="AAMkAGI2...",
        correlation_id="abc-123",
    )
"""

from __future__ import annotations


class VQMSError(Exception):
    """Base exception for all VQMS domain errors.

    Every VQMS exception carries a correlation_id so the error
    can be traced back through the pipeline logs.
    """

    def __init__(self, message: str, *, correlation_id: str | None = None) -> None:
        super().__init__(message)
        self.correlation_id = correlation_id


class DuplicateQueryError(VQMSError):
    """Raised when an idempotency check finds an existing entry.

    This is expected behavior — the same email can arrive via
    both webhook and polling, and this error prevents double
    processing.
    """

    def __init__(
        self,
        message_id: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            f"Duplicate query detected: message_id={message_id}",
            correlation_id=correlation_id,
        )
        self.message_id = message_id


class VendorNotFoundError(VQMSError):
    """Raised when vendor resolution fails.

    In the email path, this means the sender email could not
    be matched to a Salesforce vendor via any of the 3 fallback
    methods (exact email, body extraction, fuzzy name match).
    """

    def __init__(
        self,
        identifier: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            f"Vendor not found: identifier={identifier}",
            correlation_id=correlation_id,
        )
        self.identifier = identifier


class KBSearchTimeoutError(VQMSError):
    """Raised when KB vector search exceeds the timeout threshold.

    When this happens, the pipeline routes to Path B (no KB match)
    rather than crashing.
    """

    def __init__(
        self,
        query_text: str,
        timeout_seconds: float,
        *,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            f"KB search timed out after {timeout_seconds}s",
            correlation_id=correlation_id,
        )
        self.query_text = query_text
        self.timeout_seconds = timeout_seconds


class QualityGateFailedError(VQMSError):
    """Raised when a draft fails quality validation after max re-drafts.

    The pipeline routes to human review when this happens —
    it never sends an unvalidated email.
    """

    def __init__(
        self,
        failed_checks: list[str],
        *,
        correlation_id: str | None = None,
    ) -> None:
        checks_str = ", ".join(failed_checks)
        super().__init__(
            f"Quality gate failed: {checks_str}",
            correlation_id=correlation_id,
        )
        self.failed_checks = failed_checks


class SLABreachedError(VQMSError):
    """Raised when an SLA timer exceeds a threshold.

    This triggers escalation events (70%, 85%, 95% thresholds)
    rather than stopping the pipeline.
    """

    def __init__(
        self,
        query_id: str,
        threshold_percent: int,
        *,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            f"SLA breached for query_id={query_id} at {threshold_percent}%",
            correlation_id=correlation_id,
        )
        self.query_id = query_id
        self.threshold_percent = threshold_percent


class BedrockTimeoutError(VQMSError):
    """Raised when an Amazon Bedrock LLM call exceeds the timeout.

    The pipeline retries with exponential backoff, then falls
    back to Path C (low confidence) if all retries fail.
    """

    def __init__(
        self,
        model_id: str,
        timeout_seconds: float,
        *,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            f"Bedrock timeout: model={model_id} after {timeout_seconds}s",
            correlation_id=correlation_id,
        )
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds


class GraphAPIError(VQMSError):
    """Raised when a Microsoft Graph API call fails.

    Includes the endpoint and HTTP status code for debugging.
    The pipeline retries with exponential backoff.
    """

    def __init__(
        self,
        endpoint: str,
        status_code: int,
        *,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            f"Graph API error: {endpoint} returned {status_code}",
            correlation_id=correlation_id,
        )
        self.endpoint = endpoint
        self.status_code = status_code


class LLMProviderError(VQMSError):
    """Raised when an LLM provider call fails after all retries.

    Used by both OpenAIConnector and LLMGateway when the provider
    is exhausted. Includes the provider name for diagnostics.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            f"LLM provider error [{provider}]: {message}",
            correlation_id=correlation_id,
        )
        self.provider = provider
