"""Module: services/triage.py

Human review (Path C) service for VQMS.

Provides the operations the triage API routes need:
- List pending triage packages (reviewer queue dashboard).
- Fetch a single package's full detail.
- Submit a ReviewerDecision, which resumes the paused workflow
  with corrected analysis data.

Resume design:
  When a reviewer submits corrections, we merge them into the
  stored analysis_result, flip the confidence_score to 1.0 (human
  validated), and re-enqueue the unified payload to the query-intake
  SQS queue. The next pipeline execution skips triage because
  confidence is now >= threshold.

This keeps the resume path aligned with the standard pipeline —
corrected queries flow through routing / KB search / path decision
like any other query, no parallel resume logic needed.

Corresponds to Steps 8C.2 and 8C.3 in the VQMS Architecture Document.
"""

from __future__ import annotations

import orjson
import structlog

from config.settings import Settings
from events.eventbridge import EventBridgeConnector
from models.triage import ReviewerDecision, TriagePackage, TriageQueueItem
from queues.sqs import SQSConnector
from utils.decorators import log_service_call
from utils.exceptions import VQMSError
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


class TriagePackageNotFoundError(VQMSError):
    """Raised when the requested triage package does not exist."""

    def __init__(self, query_id: str, *, correlation_id: str | None = None) -> None:
        super().__init__(
            f"Triage package not found: query_id={query_id}",
            correlation_id=correlation_id,
        )
        self.query_id = query_id


class TriageAlreadyReviewedError(VQMSError):
    """Raised when a reviewer tries to review a package that was already closed."""

    def __init__(self, query_id: str, *, correlation_id: str | None = None) -> None:
        super().__init__(
            f"Triage package already reviewed: query_id={query_id}",
            correlation_id=correlation_id,
        )
        self.query_id = query_id


class TriageService:
    """Coordinates triage queue reads and reviewer decision submission.

    Routes call this service; the service handles persistence,
    event publishing, and SQS re-enqueue for workflow resume.
    """

    def __init__(
        self,
        postgres: object,  # PostgresConnector
        sqs: SQSConnector | None,
        eventbridge: EventBridgeConnector | None,
        settings: Settings,
    ) -> None:
        """Initialize with the required connectors.

        Args:
            postgres: PostgreSQL connector for triage tables.
            sqs: SQS connector used to re-enqueue after review.
                Optional — if None, resume falls back to DB-only
                which lets a background worker pick up the case.
            eventbridge: EventBridge connector for the
                HumanReviewCompleted event. Optional.
            settings: Application settings (SQS queue URL, etc.).
        """
        self._postgres = postgres
        self._sqs = sqs
        self._eventbridge = eventbridge
        self._settings = settings

    @log_service_call
    async def list_pending(
        self,
        *,
        limit: int = 50,
        correlation_id: str = "",
    ) -> list[TriageQueueItem]:
        """List pending triage packages ordered by oldest first.

        The reviewer queue shows oldest first so older low-confidence
        cases don't starve behind a flood of new ones.

        Args:
            limit: Maximum packages to return (1-200).
            correlation_id: Tracing ID for logging.

        Returns:
            List of TriageQueueItem — one per pending package.
        """
        safe_limit = max(1, min(limit, 200))

        # Pull package_data alongside the summary columns so we can surface
        # subject / vendor_id / ai_intent without a per-row /triage/{id} hit
        # from the queue page.
        rows = await self._postgres.fetch(
            """
            SELECT query_id, correlation_id, original_confidence,
                   suggested_category, status, created_at, package_data
            FROM workflow.triage_packages
            WHERE status = $1
            ORDER BY created_at ASC
            LIMIT $2
            """,
            "PENDING",
            safe_limit,
        )

        items: list[TriageQueueItem] = []
        for row in rows:
            # package_data is JSONB. We only read it — failure to decode
            # shouldn't kill the whole list response, so swallow per-row
            # errors and surface the row with display fields blank.
            try:
                package_data = self._decode_jsonb(row.get("package_data"))
            except Exception:
                package_data = {}

            original_query = package_data.get("original_query") or {}
            analysis_result = package_data.get("analysis_result") or {}

            items.append(
                TriageQueueItem(
                    query_id=row["query_id"],
                    correlation_id=row["correlation_id"],
                    original_confidence=float(row["original_confidence"]),
                    suggested_category=row.get("suggested_category"),
                    status=row["status"],
                    created_at=row["created_at"],
                    subject=original_query.get("subject"),
                    vendor_id=original_query.get("vendor_id"),
                    ai_intent=analysis_result.get("intent_classification"),
                )
            )

        logger.info(
            "Triage queue listed",
            count=len(items),
            limit=safe_limit,
            correlation_id=correlation_id,
        )
        return items

    @log_service_call
    async def get_package(
        self,
        query_id: str,
        *,
        correlation_id: str = "",
    ) -> TriagePackage:
        """Fetch the full triage package for a query.

        Args:
            query_id: VQMS query ID.
            correlation_id: Tracing ID for logging.

        Returns:
            TriagePackage with all fields the reviewer needs.

        Raises:
            TriagePackageNotFoundError: If no package exists for query_id.
        """
        row = await self._postgres.fetchrow(
            """
            SELECT query_id, correlation_id, package_data, status, created_at
            FROM workflow.triage_packages
            WHERE query_id = $1
            """,
            query_id,
        )

        if row is None:
            raise TriagePackageNotFoundError(query_id, correlation_id=correlation_id)

        package_data = self._decode_jsonb(row["package_data"])
        return TriagePackage(**package_data)

    @log_service_call
    async def submit_decision(
        self,
        query_id: str,
        decision: ReviewerDecision,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Record a reviewer's corrections and resume the paused workflow.

        Steps:
            1. Load the triage package and verify it's PENDING.
            2. Insert a row into workflow.reviewer_decisions.
            3. Mark the triage package REVIEWED.
            4. Merge corrections into analysis_result (confidence = 1.0).
            5. Update workflow.case_execution with corrected analysis.
            6. Re-enqueue the unified payload to SQS so the pipeline
               re-runs from context loading with corrected data.
            7. Publish HumanReviewCompleted event.

        Args:
            query_id: VQMS query ID being reviewed.
            decision: The reviewer's corrections.
            correlation_id: Tracing ID for logging.

        Returns:
            Dict with status, query_id, and resume_method fields.

        Raises:
            TriagePackageNotFoundError: If no package exists for query_id.
            TriageAlreadyReviewedError: If package is already REVIEWED.
        """
        row = await self._postgres.fetchrow(
            """
            SELECT query_id, correlation_id, package_data, status
            FROM workflow.triage_packages
            WHERE query_id = $1
            """,
            query_id,
        )
        if row is None:
            raise TriagePackageNotFoundError(query_id, correlation_id=correlation_id)
        if row["status"] != "PENDING":
            raise TriageAlreadyReviewedError(query_id, correlation_id=correlation_id)

        package_data = self._decode_jsonb(row["package_data"])
        now = TimeHelper.ist_now()

        # Persist the decision row so we always have a reviewer audit trail,
        # even if re-enqueue fails and the workflow never actually resumes.
        await self._postgres.execute(
            """
            INSERT INTO workflow.reviewer_decisions
            (query_id, reviewer_id, decision_data, corrected_intent,
             corrected_vendor_id, confidence_override, reviewer_notes, decided_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            query_id,
            decision.reviewer_id,
            orjson.dumps(decision.model_dump(mode="json")).decode("utf-8"),
            decision.corrected_intent,
            decision.corrected_vendor_id,
            decision.confidence_override,
            decision.reviewer_notes,
            now,
        )

        # Flip package status so subsequent calls see this row as closed
        await self._postgres.execute(
            """
            UPDATE workflow.triage_packages
            SET status = $1, reviewed_at = $2, reviewed_by = $3
            WHERE query_id = $4
            """,
            "REVIEWED",
            now,
            decision.reviewer_id,
            query_id,
        )

        # Merge corrections into the stored analysis so downstream nodes see
        # the reviewer's call instead of the original low-confidence output.
        corrected_analysis = self._apply_corrections(
            package_data.get("analysis_result") or {},
            decision,
        )

        # Update case_execution so the pipeline (and dashboards) pick up the
        # corrected analysis and know the workflow is resuming.
        await self._postgres.execute(
            """
            UPDATE workflow.case_execution
            SET status = $1,
                analysis_result = $2,
                vendor_id = COALESCE($3, vendor_id),
                updated_at = $4
            WHERE query_id = $5
            """,
            "REVIEWED",
            orjson.dumps(corrected_analysis).decode("utf-8"),
            decision.corrected_vendor_id,
            now,
            query_id,
        )

        # Re-enqueue to SQS so the standard pipeline runs again.
        # The consumer reads unified_payload; we attach corrected_analysis
        # so the Query Analysis node can short-circuit if it wants to.
        resume_method = await self._reenqueue(
            query_id=query_id,
            correlation_id=correlation_id,
            package_data=package_data,
            corrected_analysis=corrected_analysis,
            decision=decision,
        )

        # HumanReviewCompleted event [NON-CRITICAL]
        if self._eventbridge is not None:
            try:
                await self._eventbridge.publish_event(
                    "HumanReviewCompleted",
                    {
                        "query_id": query_id,
                        "reviewer_id": decision.reviewer_id,
                        "corrected_intent": decision.corrected_intent,
                        "corrected_vendor_id": decision.corrected_vendor_id,
                    },
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "EventBridge publish failed — continuing",
                    query_id=query_id,
                    correlation_id=correlation_id,
                )

        logger.info(
            "Triage decision submitted — workflow resuming",
            query_id=query_id,
            reviewer_id=decision.reviewer_id,
            resume_method=resume_method,
            correlation_id=correlation_id,
        )

        return {
            "status": "REVIEWED",
            "query_id": query_id,
            "resume_method": resume_method,
        }

    async def _reenqueue(
        self,
        *,
        query_id: str,
        correlation_id: str,
        package_data: dict,
        corrected_analysis: dict,
        decision: ReviewerDecision,
    ) -> str:
        """Re-enqueue the unified payload to SQS so the pipeline resumes.

        Returns the resume method label for logging / response.
        "sqs" means the queue accepted it; "db_only" means we fell back
        to leaving the corrected analysis in case_execution for a
        background worker to pick up.
        """
        if self._sqs is None:
            return "db_only"

        queue_url = self._settings.sqs_query_intake_queue_url
        if not queue_url:
            logger.warning(
                "SQS queue URL not configured — resume is DB-only",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return "db_only"

        resume_message = {
            **(package_data.get("original_query") or {}),
            "correlation_id": correlation_id or package_data.get("correlation_id", ""),
            "resume_context": {
                "from_triage": True,
                "corrected_analysis": corrected_analysis,
                "reviewer_id": decision.reviewer_id,
            },
        }

        try:
            await self._sqs.send_message(
                queue_url,
                resume_message,
                correlation_id=correlation_id,
            )
            return "sqs"
        except Exception:
            logger.warning(
                "SQS re-enqueue failed — falling back to DB-only resume",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return "db_only"

    def _apply_corrections(
        self,
        original_analysis: dict,
        decision: ReviewerDecision,
    ) -> dict:
        """Merge reviewer corrections into a copy of the analysis result.

        Immutability: we build a new dict instead of mutating the original.
        Confidence jumps to 1.0 (or the reviewer's override) because a
        human has validated the decision.
        """
        corrected = dict(original_analysis)

        if decision.corrected_intent is not None:
            corrected["intent_classification"] = decision.corrected_intent

        if decision.confidence_override is not None:
            corrected["confidence_score"] = decision.confidence_override
        else:
            # Human-validated → confidence is effectively 1.0
            corrected["confidence_score"] = 1.0

        corrected["human_validated"] = True
        corrected["reviewer_id"] = decision.reviewer_id
        return corrected

    @staticmethod
    def _decode_jsonb(value: object) -> dict:
        """Decode a JSONB column value to a dict.

        asyncpg returns JSONB as a Python dict already when codecs are
        configured; in test mocks or unconfigured pools it can come back
        as a str or bytes. Handle all three safely.
        """
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            return orjson.loads(value)
        if isinstance(value, str):
            return orjson.loads(value)
        # Fallback: assume already-parsed JSON-compatible object
        return dict(value) if value is not None else {}
