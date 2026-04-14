"""Module: orchestration/nodes/path_decision.py

Path Decision Node — Decision Point 2 in the VQMS pipeline.

Based on KB search results, routes to Path A (AI resolution)
or Path B (human team investigation). Reached ONLY if confidence
check passed (>= 0.85).

- Path A: KB match >= 0.80 with specific facts → AI drafts resolution
- Path B: No sufficient KB match → AI drafts acknowledgment, human investigates

Corresponds to Decision Point 2 in the VQMS Architecture Document.
"""

from __future__ import annotations

import structlog

from config.settings import Settings
from models.workflow import PipelineState
from models.ticket import RoutingDecision, SLATarget
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# Minimum content length to consider a KB match as having "specific facts"
# Short snippets are likely generic boilerplate, not actionable content
MIN_CONTENT_LENGTH = 100


class PathDecisionNode:
    """Decides between Path A and Path B based on KB results.

    Path A: KB has relevant articles with specific facts.
    Path B: KB lacks relevant articles — human team must investigate.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with KB match threshold from settings.

        Args:
            settings: Application settings (kb_match_threshold = 0.80).
        """
        self._threshold = settings.kb_match_threshold

    async def execute(self, state: PipelineState) -> PipelineState:
        """Determine processing path based on KB search results.

        Args:
            state: Current pipeline state with kb_search_result.

        Returns:
            Updated state with processing_path ("A" or "B").
        """
        correlation_id = state.get("correlation_id", "")
        kb_result = state.get("kb_search_result", {})
        has_sufficient = kb_result.get("has_sufficient_match", False)

        # Check if the top match has enough content for a resolution
        matches = kb_result.get("matches", [])
        has_specific_facts = False
        if matches:
            top_match = matches[0]
            content_length = len(top_match.get("content_snippet", ""))
            has_specific_facts = content_length >= MIN_CONTENT_LENGTH

        if has_sufficient and has_specific_facts:
            # Path A: AI can resolve using KB articles
            logger.info(
                "Path A selected — KB match found with specific facts",
                step="path_decision",
                decision="path_a",
                best_score=kb_result.get("best_match_score"),
                matches_count=len(matches),
                correlation_id=correlation_id,
            )
            return {
                "processing_path": "A",
                "status": "DRAFTING",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }
        else:
            # Path B: Human team must investigate
            logger.info(
                "Path B selected — insufficient KB match for resolution",
                step="path_decision",
                decision="path_b",
                best_score=kb_result.get("best_match_score"),
                has_sufficient=has_sufficient,
                has_specific_facts=has_specific_facts,
                correlation_id=correlation_id,
            )

            # Update routing_decision to flag human investigation required
            # RoutingDecision is frozen, so we create a new instance
            routing_data = state.get("routing_decision", {})
            if routing_data:
                sla_data = routing_data.get("sla_target", {})
                updated_routing = RoutingDecision(
                    assigned_team=routing_data.get("assigned_team", "general-support"),
                    sla_target=SLATarget(**sla_data) if sla_data else SLATarget(total_hours=24),
                    category=routing_data.get("category", "general"),
                    priority=routing_data.get("priority", "MEDIUM"),
                    routing_reason=routing_data.get("routing_reason", ""),
                    requires_human_investigation=True,
                )
                return {
                    "processing_path": "B",
                    "status": "DRAFTING",
                    "routing_decision": updated_routing.model_dump(),
                    "updated_at": TimeHelper.ist_now().isoformat(),
                }

            return {
                "processing_path": "B",
                "status": "DRAFTING",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }
