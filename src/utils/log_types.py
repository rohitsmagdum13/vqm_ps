"""Module: utils/log_types.py

Log-type taxonomy for VQMS.

Every structured log line emitted by application code should include a
``log_type`` field taking one of the constants below. The field drives:

- CloudWatch subscription filters — routes each category into its own
  log group with a retention policy appropriate for that category
  (e.g. audit = 7 years, service = 14 days).
- Metric filters — ``$.log_type = "llm"`` with extracted ``cost_usd``
  feeds the LLM-spend dashboard without any code changes.
- Local log filtering — ``grep '"log_type":"security"' vqms.log`` is
  instantly useful.
- Alerting — distinct thresholds on security vs. application errors.

This file is the single source of truth. Never hardcode the string
values at call sites; import the constants. That way a rename or a new
category is a one-file change.

Utility helper:
    >>> from utils.log_types import infer_integration_or_service
    >>> infer_integration_or_service("adapters.salesforce.client")
    'integration'
    >>> infer_integration_or_service("services.email_intake.service")
    'service'
"""

from __future__ import annotations

# Lifecycle events for the process itself — startup, shutdown, config load,
# scheduler ticks. Not tied to any request.
LOG_TYPE_APPLICATION = "application"

# Internal service/method entry-exit via @log_service_call. The default
# bucket for anything that isn't an outbound integration.
LOG_TYPE_SERVICE = "service"

# HTTP request/response lines emitted by @log_api_call or FastAPI
# middleware — method, path, status, duration.
LOG_TYPE_ACCESS = "access"

# Outbound calls to external systems: Salesforce, Graph API, ServiceNow,
# Bedrock, OpenAI, S3, SQS, EventBridge, Postgres. Recognised by the
# ``tool=<name>`` field also being present.
LOG_TYPE_INTEGRATION = "integration"

# Compliance-grade state transitions. Also persisted to
# audit.action_log in the DB; this log line is the real-time copy for
# CloudWatch alerting.
LOG_TYPE_AUDIT = "audit"

# AuthN/AuthZ events: login success/failure, JWT validation, blacklist,
# permission denials, suspicious patterns.
LOG_TYPE_SECURITY = "security"

# Domain events meaningful to the business: EmailParsed, TicketCreated,
# SLAWarning70, Path A selected, etc. Typically published to
# EventBridge too — this is the log-file mirror.
LOG_TYPE_BUSINESS = "business"

# Handled or unhandled exceptions. ``logger.exception`` emits this.
LOG_TYPE_ERROR = "error"

# Quantitative metrics pulled out as their own line for CloudWatch
# metric filters — duration_ms, tokens_in, cost_usd, etc.
LOG_TYPE_PERF = "performance"

# LLM-specific: prompt_id, model, temperature, tokens_in/out, cost_usd,
# confidence. Fed by @log_llm_call.
LOG_TYPE_LLM = "llm"

# Policy/routing decisions: confidence threshold checks, Path A/B/C
# selection. Fed by @log_policy_decision.
LOG_TYPE_POLICY = "policy"

# Verbose dev-only lines. LOG_LEVEL=DEBUG only, never shipped to
# CloudWatch in prod.
LOG_TYPE_DEBUG = "debug"


# Module prefixes we treat as "integration" instead of "service" when
# a @log_service_call is inferred. Keep this list aligned with the
# 5-layer architecture from CLAUDE.md — anything in an adapter layer
# or infrastructure connector should flag as integration.
_INTEGRATION_MODULE_PREFIXES: tuple[str, ...] = (
    "adapters.",
    "queues.",
    "storage.",
    "events.",
    "db.",
)


def infer_integration_or_service(module_name: str) -> str:
    """Decide whether a function lives in the integration layer.

    The @log_service_call decorator uses this to auto-pick between
    ``integration`` and ``service`` so individual call sites don't
    have to specify. A function in ``adapters.salesforce.client``
    is integration; a function in ``services.email_intake.service``
    is service.

    Args:
        module_name: The function's ``__module__`` (e.g. the string
            ``"adapters.salesforce.vendor_lookup"``).

    Returns:
        ``LOG_TYPE_INTEGRATION`` if the module is in an integration
        layer, otherwise ``LOG_TYPE_SERVICE``.
    """
    normalized = (module_name or "").lstrip(".")
    for prefix in _INTEGRATION_MODULE_PREFIXES:
        if normalized.startswith(prefix):
            return LOG_TYPE_INTEGRATION
    return LOG_TYPE_SERVICE


__all__ = [
    "LOG_TYPE_APPLICATION",
    "LOG_TYPE_SERVICE",
    "LOG_TYPE_ACCESS",
    "LOG_TYPE_INTEGRATION",
    "LOG_TYPE_AUDIT",
    "LOG_TYPE_SECURITY",
    "LOG_TYPE_BUSINESS",
    "LOG_TYPE_ERROR",
    "LOG_TYPE_PERF",
    "LOG_TYPE_LLM",
    "LOG_TYPE_POLICY",
    "LOG_TYPE_DEBUG",
    "infer_integration_or_service",
]
