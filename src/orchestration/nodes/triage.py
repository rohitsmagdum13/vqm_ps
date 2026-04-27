"""Module: orchestration/nodes/triage.py

Triage Node — Path C entry point in the VQMS pipeline.

When the Query Analysis Agent produces a confidence score below
the threshold (0.85), the ConfidenceCheckNode sets processing_path
to "C" and the graph routes here. This node:

1. Builds a TriagePackage with the analysis, original query, and
   suggested routing so the reviewer has full context.
2. Persists the package to workflow.triage_packages with a unique
   callback_token the API layer uses to resume the workflow.
3. Publishes a HumanReviewRequired event for the audit trail.
4. Updates workflow.case_execution.status to PAUSED so dashboards
   and downstream consumers know the workflow stopped here.

The graph terminates at END after this node — the workflow stays
paused until a reviewer submits a ReviewerDecision through the
TriageService.

Corresponds to Steps 8C.1 and 8C.2 in the VQMS Architecture Document.
"""

from __future__ import annotations

import uuid

import orjson
import structlog

from config.settings import Settings
from events.eventbridge import EventBridgeConnector
from models.workflow import PipelineState
from utils.helpers import TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)


class TriageNode:
    """Builds and persists a TriagePackage when confidence is low.

    This is the Path C entry point. Workflow pauses after this
    node runs — the reviewer resumes it via POST /triage/{id}/review.
    """

    def __init__(
        self,
        postgres: object,  # PostgresConnector
        eventbridge: EventBridgeConnector | None,
        settings: Settings,
    ) -> None:
        """Initialize with connectors.

        Args:
            postgres: PostgreSQL connector for persisting packages.
            eventbridge: EventBridge connector for HumanReviewRequired event.
                Optional — if None, event publishing is skipped with a warning.
            settings: Application settings.
        """
        self._postgres = postgres
        self._eventbridge = eventbridge
        self._settings = settings

    async def execute(self, state: PipelineState) -> PipelineState:
        """Build a triage package and persist it for human review.

        Args:
            state: Current pipeline state. Must contain analysis_result
                and unified_payload; routing_decision is optional
                because Path C triggers before the routing node runs.

        Returns:
            Partial PipelineState update with triage_package, status=PAUSED.
        """
        correlation_id = state.get("correlation_id", "")
        query_id = state.get("query_id", "")
        analysis_result = state.get("analysis_result") or {}
        unified_payload = state.get("unified_payload") or {}
        suggested_routing = state.get("routing_decision")  # None for Path C
        suggested_draft = state.get("draft_response")  # None for Path C

        callback_token = str(uuid.uuid4())
        created_at = TimeHelper.ist_now()

        logger.info(
            "Triage package creation started",
            step="triage",
            query_id=query_id,
            confidence_score=analysis_result.get("confidence_score"),
            correlation_id=correlation_id,
        )

        # Build a dict-shaped triage package. We don't instantiate the
        # TriagePackage Pydantic model here because:
        #  - the state already carries dicts for analysis_result / payload
        #  - re-validating adds no safety (inputs come from trusted nodes)
        #  - the API layer hands the stored JSONB back to the reviewer as-is
        package_data = {
            "query_id": query_id,
            "correlation_id": correlation_id,
            "callback_token": callback_token,
            "original_query": unified_payload,
            "analysis_result": analysis_result,
            "confidence_breakdown": self._build_confidence_breakdown(analysis_result),
            "suggested_routing": suggested_routing,
            "suggested_draft": suggested_draft,
            "created_at": created_at.isoformat(),
        }

        # Persist the package [CRITICAL]
        # If this fails, the reviewer has nothing to review — raise so SQS
        # retries. workflow.case_execution stays in its pre-triage status
        # (ANALYZING) so the next retry can re-run triage cleanly.
        await self._postgres.execute(
            """
            INSERT INTO workflow.triage_packages
            (query_id, correlation_id, callback_token, package_data,
             status, original_confidence, suggested_category, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (query_id) DO NOTHING
            """,
            query_id,
            correlation_id,
            callback_token,
            orjson.dumps(package_data).decode("utf-8"),
            "PENDING",
            float(analysis_result.get("confidence_score", 0.0)),
            analysis_result.get("suggested_category"),
            created_at,
        )

        # Update case_execution so dashboards and routing know the
        # workflow is paused. Safe if the row doesn't exist yet —
        # the UPDATE just affects zero rows.
        await self._postgres.execute(
            """
            UPDATE workflow.case_execution
            SET status = $1, processing_path = $2, updated_at = $3
            WHERE query_id = $4
            """,
            "PAUSED",
            "C",
            created_at,
            query_id,
        )

        # HumanReviewRequired event [NON-CRITICAL]
        if self._eventbridge is not None:
            try:
                await self._eventbridge.publish_event(
                    "HumanReviewRequired",
                    {
                        "query_id": query_id,
                        "callback_token": callback_token,
                        "confidence_score": analysis_result.get("confidence_score"),
                        "suggested_category": analysis_result.get("suggested_category"),
                    },
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "EventBridge publish failed — continuing",
                    step="triage",
                    query_id=query_id,
                    correlation_id=correlation_id,
                )
        else:
            logger.warning(
                "EventBridge unavailable — HumanReviewRequired not published",
                step="triage",
                query_id=query_id,
                correlation_id=correlation_id,
            )

        logger.info(
            "Triage package persisted — workflow paused",
            step="triage",
            query_id=query_id,
            callback_token=callback_token,
            correlation_id=correlation_id,
        )

        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="triage",
            action="package_created",
            status="success",
            details={
                "processing_path": "C",
                "callback_token": callback_token,
                "confidence_score": analysis_result.get("confidence_score"),
                "suggested_category": analysis_result.get("suggested_category"),
            },
        )

        return {
            "triage_package": package_data,
            "status": "PAUSED",
            "updated_at": created_at.isoformat(),
        }

    def _build_confidence_breakdown(self, analysis_result: dict) -> dict:
        """Decompose the analysis result into reviewer-facing confidence signals.

        The Query Analysis Agent returns one aggregate confidence_score,
        but the reviewer benefits from seeing which dimensions pulled the
        score down. This is a simple derivation in dev mode — later phases
        can replace it with per-dimension scores from the LLM.
        """
        confidence_score = float(analysis_result.get("confidence_score", 0.0))
        entities = analysis_result.get("extracted_entities") or {}
        multi_issue = bool(analysis_result.get("multi_issue_detected", False))

        # Simple heuristics: any missing entity or multi-issue detection
        # lowers confidence in that dimension so the reviewer can see why.
        entity_confidence = confidence_score if entities else max(0.0, confidence_score - 0.2)
        intent_confidence = confidence_score
        issue_confidence = max(0.0, confidence_score - 0.15) if multi_issue else confidence_score

        return {
            "overall": confidence_score,
            "intent_classification": round(intent_confidence, 3),
            "entity_extraction": round(entity_confidence, 3),
            "single_issue_detection": round(issue_confidence, 3),
            "threshold": self._settings.agent_confidence_threshold,
        }
