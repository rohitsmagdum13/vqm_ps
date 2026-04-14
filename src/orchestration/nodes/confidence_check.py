"""Module: orchestration/nodes/confidence_check.py

Confidence Check Node — Decision Point 1 in the VQMS pipeline.

Simple gate that checks the confidence_score from the Query
Analysis Agent against the configurable threshold (0.85).

- >= threshold: continue to routing + KB search (Path A or B)
- < threshold: route to Path C (human review, workflow pauses)

Corresponds to Decision Point 1 in the VQMS Architecture Document.
"""

from __future__ import annotations

import structlog

from config.settings import Settings
from models.workflow import PipelineState
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


class ConfidenceCheckNode:
    """Checks analysis confidence against threshold.

    If confidence is high enough, the query continues to
    routing and KB search. If too low, it routes directly
    to Path C for human review.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with confidence threshold from settings.

        Args:
            settings: Application settings (agent_confidence_threshold = 0.85).
        """
        self._threshold = settings.agent_confidence_threshold

    async def execute(self, state: PipelineState) -> PipelineState:
        """Check confidence and set processing path.

        Args:
            state: Current pipeline state with analysis_result.

        Returns:
            Updated state with processing_path set.
        """
        correlation_id = state.get("correlation_id", "")
        analysis_result = state.get("analysis_result", {})
        confidence_score = analysis_result.get("confidence_score", 0.0)

        if confidence_score >= self._threshold:
            # Continue to routing + KB search
            logger.info(
                "Confidence check passed — continuing to routing",
                step="confidence_check",
                confidence_score=confidence_score,
                threshold=self._threshold,
                decision="continue",
                correlation_id=correlation_id,
            )
            return {
                "updated_at": TimeHelper.ist_now().isoformat(),
            }
        else:
            # Route to Path C — workflow pauses for human review
            logger.info(
                "Confidence below threshold — routing to Path C",
                step="confidence_check",
                confidence_score=confidence_score,
                threshold=self._threshold,
                decision="path_c",
                correlation_id=correlation_id,
            )
            return {
                "processing_path": "C",
                "status": "PAUSED",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }
