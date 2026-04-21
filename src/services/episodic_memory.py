"""Module: services/episodic_memory.py

Episodic Memory Writer — Phase 6 Workstream D.

Writes one row to `memory.episodic_memory` per case closure so the
context-loading node can surface the vendor's last 5 interactions
as conversation history on future queries.

Read side lives in:
    src/orchestration/nodes/context_loading.py :: _load_episodic_memory

Design notes:
  * Dev-mode summary is deterministic (template string). When we add
    an LLM-summarization pass later, we swap _build_summary's body to
    call the gateway — the call signature stays the same.
  * Non-critical: any failure is logged and swallowed. A missing
    memory row only means next-query context misses one prior case,
    which is better than rolling back the closure.
"""

from __future__ import annotations

import structlog

from config.settings import Settings
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)


class EpisodicMemoryWriter:
    """Persists a closure summary into `memory.episodic_memory`.

    One instance is created at app startup and reused. Depends only
    on the PostgresConnector; the LLM gateway is threaded through as
    an optional future hook but unused in dev mode.
    """

    def __init__(
        self,
        postgres: object,  # PostgresConnector
        settings: Settings,
        llm_gateway: object | None = None,
    ) -> None:
        """Initialize with the required connectors.

        Args:
            postgres: PostgreSQL connector.
            settings: Application settings.
            llm_gateway: Reserved for LLM-summarization. Unused in dev.
        """
        self._postgres = postgres
        self._settings = settings
        self._llm_gateway = llm_gateway

    async def save_closure(
        self,
        *,
        query_id: str,
        correlation_id: str = "",
        reason: str = "VENDOR_CONFIRMED",
    ) -> str | None:
        """Insert an episodic memory row for a closed case.

        Args:
            query_id: VQMS query ID being closed.
            correlation_id: Tracing ID for logs.
            reason: Why the case closed (VENDOR_CONFIRMED / AUTO_CLOSED /
                REOPENED). Stored in the `outcome` column so analytics
                can split "customer-confirmed" vs. "assumed-resolved".

        Returns:
            The generated memory_id on success, None on failure.
        """
        case_row = await self._fetch_case(query_id, correlation_id)
        if case_row is None:
            return None

        vendor_id = case_row.get("vendor_id") or "UNKNOWN"
        processing_path = case_row.get("processing_path") or "A"
        analysis_result = self._safe_dict(case_row.get("analysis_result"))
        intent = (
            analysis_result.get("intent_classification")
            or "general_inquiry"
        )

        summary = self._build_summary(
            vendor_id=vendor_id,
            intent=intent,
            processing_path=processing_path,
            reason=reason,
        )
        memory_id = f"MEM-{IdGenerator.generate_correlation_id()}"
        now = TimeHelper.ist_now()

        try:
            await self._postgres.execute(
                """
                INSERT INTO memory.episodic_memory (
                    memory_id, vendor_id, query_id, intent,
                    resolution_path, outcome, resolved_at, summary,
                    created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                memory_id,
                vendor_id,
                query_id,
                intent,
                processing_path,
                reason,
                now,
                summary,
                now,
            )
        except Exception:
            logger.warning(
                "Failed to write episodic memory — continuing (non-critical)",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return None

        logger.info(
            "Episodic memory saved",
            memory_id=memory_id,
            query_id=query_id,
            vendor_id=vendor_id,
            outcome=reason,
            correlation_id=correlation_id,
        )
        return memory_id

    async def _fetch_case(
        self, query_id: str, correlation_id: str
    ) -> dict | None:
        """Load the case_execution row we need to build the summary."""
        try:
            row = await self._postgres.fetchrow(
                """
                SELECT query_id, vendor_id, processing_path,
                       analysis_result, created_at
                FROM workflow.case_execution
                WHERE query_id = $1
                """,
                query_id,
            )
        except Exception:
            logger.warning(
                "Failed to load case_execution for episodic memory",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return None

        if row is None:
            logger.warning(
                "No case_execution row — skipping episodic memory",
                query_id=query_id,
                correlation_id=correlation_id,
            )
        return row

    @staticmethod
    def _build_summary(
        *,
        vendor_id: str,
        intent: str,
        processing_path: str,
        reason: str,
    ) -> str:
        """Deterministic one-line summary for dev mode.

        Kept short (<200 chars) because context_loading includes up to
        five of these in the next query's prompt.
        """
        path_label = {
            "A": "AI-resolved",
            "B": "team-resolved",
            "C": "human-reviewed",
        }.get(processing_path, "resolved")
        return (
            f"{intent} for {vendor_id}: {path_label} — closed as {reason}"
        )

    @staticmethod
    def _safe_dict(value: object) -> dict:
        """Defensively unwrap JSONB fields that may be dict / str / bytes."""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            try:
                import orjson

                return orjson.loads(value)
            except Exception:
                return {}
        if isinstance(value, str):
            try:
                import orjson

                return orjson.loads(value)
            except Exception:
                return {}
        return {}
