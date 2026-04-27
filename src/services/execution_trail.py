"""Module: services/execution_trail.py

Per-query pipeline-stage trail.

Every interesting moment in a query's lifecycle (intake, each LangGraph
node, every LLM call, admin actions, closure) writes one row to
``audit.action_log``. The Angular query-detail page reads them back
through GET /queries/{query_id}.trail and renders a live timeline so an
admin can see exactly where a query is sitting inside the pipeline.

The audit table schema fits this purpose 1:1
(see src/db/migrations/005_create_audit_tables.sql) — this service is
only a thin writer/reader on top of it.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from db.connection import PostgresConnector

logger = structlog.get_logger(__name__)


class ExecutionTrailService:
    """Append-only trail of pipeline events for a query.

    Designed to be infallible from the caller's perspective — a failed
    audit write is logged but never propagated. The pipeline must NEVER
    fail because the trail can't be persisted.
    """

    def __init__(self, postgres: PostgresConnector) -> None:
        self._postgres = postgres

    async def record_step(
        self,
        *,
        query_id: str | None,
        correlation_id: str,
        step_name: str,
        action: str,
        status: str,
        details: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        actor: str = "system",
    ) -> None:
        """Insert one row into ``audit.action_log``.

        Args:
            query_id: VQ-id; may be empty for events before id generation.
            correlation_id: UUIDv4 propagated through the request.
            step_name: Pipeline step (e.g. "kb_search", "delivery",
                "draft_approval"). Max 50 chars to fit the column.
            action: What happened ("execute", "passed", "approved").
                Max 100 chars.
            status: Outcome — "success", "failed", "skipped", etc.
                Max 20 chars.
            details: Arbitrary JSON-serialisable payload (confidence,
                model_id, tokens, ticket_id, ...). Stored as JSONB.
            duration_ms: How long the step took. Optional.
            actor: Who performed the action. Defaults to "system".
        """
        try:
            await self._postgres.execute(
                """
                INSERT INTO audit.action_log
                    (correlation_id, query_id, step_name, actor, action,
                     status, details, duration_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                """,
                correlation_id,
                query_id or None,
                step_name[:50],
                actor[:100],
                action[:100],
                status[:20],
                json.dumps(details or {}),
                int(duration_ms) if duration_ms is not None else None,
            )
        except Exception:
            # Trail writes are observability — losing one is acceptable;
            # propagating the error and breaking the pipeline is not.
            logger.warning(
                "Failed to write audit.action_log entry",
                step="execution_trail",
                query_id=query_id,
                step_name=step_name,
                action=action,
                correlation_id=correlation_id,
            )

    async def get_trail(self, query_id: str) -> list[dict]:
        """Return every audit row for ``query_id`` in chronological order.

        The existing ``idx_action_log_query`` index covers this filter.
        """
        rows = await self._postgres.fetch(
            """
            SELECT id, correlation_id, query_id, step_name, actor,
                   action, status, details, duration_ms, created_at
            FROM audit.action_log
            WHERE query_id = $1
            ORDER BY created_at ASC, id ASC
            """,
            query_id,
        )

        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": row["id"],
                    "correlation_id": row["correlation_id"],
                    "query_id": row["query_id"],
                    "step_name": row["step_name"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "status": row["status"],
                    "details": _coerce_jsonb(row.get("details")) or {},
                    "duration_ms": row.get("duration_ms"),
                    "created_at": str(row["created_at"]),
                }
            )
        return out


def _coerce_jsonb(value: Any) -> dict | None:
    """asyncpg returns JSONB as either a parsed dict or a JSON string.

    Normalise to dict-or-None so the route handler doesn't have to branch.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None
