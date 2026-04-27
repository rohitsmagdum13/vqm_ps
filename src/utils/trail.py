"""Module: utils/trail.py

Pipeline trail helper — one-line wrapper around ExecutionTrailService.

Pipeline nodes call ``record_node()`` at the end of their execute()
to write one row to ``audit.action_log``. Those rows power the
``GET /queries/{id}/trail`` endpoint and the live timeline on the
admin query-detail page.

The helper is awaited so rows land in the order nodes complete (the
underlying ``ExecutionTrailService.record_step`` already swallows DB
errors, so a bad audit write can never break the pipeline). When the
trail service isn't configured (tests, scripts), the call is a no-op.
"""

from __future__ import annotations

from typing import Any

from utils.context import get_trail_service


async def record_node(
    *,
    query_id: str | None,
    correlation_id: str,
    step_name: str,
    status: str = "success",
    action: str = "execute",
    details: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    actor: str = "system",
) -> None:
    """Append one row to ``audit.action_log`` for a pipeline step.

    Args:
        query_id: VQ-id; may be empty for events before id generation.
        correlation_id: UUIDv4 propagated through the request.
        step_name: Pipeline step (matches the keys the frontend humanises:
            ``intake``, ``context_loading``, ``query_analysis``,
            ``confidence_check``, ``routing``, ``kb_search``,
            ``path_decision``, ``resolution``, ``acknowledgment``,
            ``resolution_from_notes``, ``quality_gate``, ``delivery``,
            ``triage``, ``draft_approval``, ``closure``).
        status: Outcome — ``success``, ``failed``, ``skipped``.
        action: What happened. Defaults to ``execute``; nodes may pass
            a more specific verb (``passed``, ``redirected_path_c``).
        details: Arbitrary JSON-serialisable payload (confidence,
            ticket_id, etc.). Stored as JSONB.
        duration_ms: Optional step latency.
        actor: Who performed the action. Defaults to ``system``.
    """
    trail = get_trail_service()
    if trail is None:
        # Observability not configured (tests, scripts) — drop silently.
        return
    await trail.record_step(
        query_id=query_id,
        correlation_id=correlation_id,
        step_name=step_name,
        action=action,
        status=status,
        details=details or {},
        duration_ms=duration_ms,
        actor=actor,
    )
