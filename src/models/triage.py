"""Module: models/triage.py

Pydantic models for Path C human review (low-confidence triage).

When the Query Analysis Agent confidence is below 0.85,
a TriagePackage is created and sent to the human review queue.
A reviewer corrects the AI's classification and the workflow
resumes with validated data.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models.workflow import AnalysisResult
from models.communication import DraftResponse
from models.query import UnifiedQueryPayload
from models.ticket import RoutingDecision


class TriagePackage(BaseModel):
    """Package sent to human reviewer when AI confidence is low (Path C).

    Contains everything the reviewer needs to make a decision:
    the original query, the AI's analysis, confidence breakdown,
    and the AI's suggested routing and draft.

    The callback_token is used by the API layer to identify which
    paused workflow to resume when the reviewer submits corrections.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(description="VQMS query ID")
    correlation_id: str = Field(description="UUID v4 tracing ID")
    callback_token: str = Field(description="Unique token used to resume the paused workflow")
    original_query: UnifiedQueryPayload = Field(description="The original vendor query")
    analysis_result: AnalysisResult = Field(description="AI's analysis output")
    confidence_breakdown: dict = Field(
        default_factory=dict,
        description="Detailed confidence scores by dimension (intent, entity, sentiment)",
    )
    suggested_routing: RoutingDecision | None = Field(
        default=None,
        description="AI's suggested routing decision (None if routing not yet computed)",
    )
    suggested_draft: DraftResponse | None = Field(
        default=None,
        description="AI's suggested draft (if available)",
    )
    created_at: datetime = Field(description="When the triage package was created (IST)")


class TriageQueueItem(BaseModel):
    """Lightweight summary of a triage package for the reviewer queue list.

    Reviewers see these cards in the queue; they open one to get the
    full TriagePackage for review.

    Some display fields (subject, vendor_id, ai_intent) are surfaced
    from the stored package_data JSONB so the queue page can render
    real values without one /triage/{id} fetch per row.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(description="VQMS query ID")
    correlation_id: str = Field(description="UUID v4 tracing ID")
    original_confidence: float = Field(description="AI's confidence score (triggered Path C)")
    suggested_category: str | None = Field(default=None, description="AI's suggested category")
    status: str = Field(description="Package status: PENDING or REVIEWED")
    created_at: datetime = Field(description="When the triage package was created (IST)")
    subject: str | None = Field(
        default=None, description="Subject from the original query (surfaced from package_data)"
    )
    vendor_id: str | None = Field(
        default=None, description="Vendor ID from the original query (surfaced from package_data)"
    )
    ai_intent: str | None = Field(
        default=None,
        description="AI intent classification (surfaced from package_data analysis_result)",
    )


class ReviewerDecision(BaseModel):
    """Human reviewer's corrections to the AI's analysis (Path C).

    After the reviewer submits corrections, the workflow resumes
    with this validated data. The corrected fields override
    the AI's original analysis.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(description="VQMS query ID being reviewed")
    reviewer_id: str = Field(description="Cognito user ID of the reviewer")
    corrected_intent: str | None = Field(default=None, description="Corrected intent classification")
    corrected_vendor_id: str | None = Field(default=None, description="Corrected vendor ID")
    corrected_routing: str | None = Field(default=None, description="Corrected routing team")
    confidence_override: float | None = Field(
        default=None,
        description="Reviewer's confidence override (always high since human-validated)",
    )
    reviewer_notes: str = Field(description="Reviewer's notes explaining the corrections")
    decided_at: datetime = Field(description="When the review was completed (IST)")
