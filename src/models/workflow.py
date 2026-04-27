"""Module: models/workflow.py

Pydantic model for the Query Analysis Agent output and LangGraph pipeline state.

The Query Analysis Agent (LLM Call #1) processes every vendor
query and produces an AnalysisResult with intent classification,
entity extraction, urgency, sentiment, and confidence score.

PipelineState is a TypedDict (not a Pydantic model) because
LangGraph requires TypedDict for its state machine. Each node
in the graph reads from and writes to this shared state.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class AnalysisResult(BaseModel):
    """Output from the Query Analysis Agent (Step 8).

    This is the structured output parsed from Claude's response.
    The confidence_score determines the processing path:
    - >= 0.85: continue to routing + KB search (Path A or B)
    - < 0.85: route to Path C (human review)
    """

    model_config = ConfigDict(frozen=True)

    intent_classification: str = Field(description="Classified intent (e.g., invoice_inquiry, delivery_status)")
    extracted_entities: dict = Field(
        default_factory=dict,
        description="Extracted entities: invoice numbers, dates, amounts, PO numbers",
    )
    urgency_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        description="Assessed urgency of the query",
    )
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "FRUSTRATED"] = Field(
        description="Detected sender sentiment",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="AI confidence in the analysis (0.0-1.0). Threshold is 0.85.",
    )
    multi_issue_detected: bool = Field(
        default=False,
        description="Whether multiple distinct issues were found in one query",
    )
    suggested_category: str = Field(description="Suggested category for routing")
    analysis_duration_ms: int = Field(description="Time taken for the LLM call in milliseconds")
    model_id: str = Field(description="Model used for analysis (e.g., anthropic.claude-3-5-sonnet)")
    tokens_in: int = Field(description="Input token count")
    tokens_out: int = Field(description="Output token count")


class PipelineState(TypedDict, total=False):
    """Shared state for the LangGraph pipeline.

    Every node reads from and writes to this state dict.
    Using total=False makes all fields optional so nodes
    can incrementally populate the state.

    Note: This is a TypedDict, not a Pydantic model, because
    LangGraph requires TypedDict for its StateGraph definition.
    Values are stored as dicts (serialized Pydantic models)
    for compatibility with LangGraph's state management.
    """

    # Core identifiers — set at pipeline entry
    query_id: str
    correlation_id: str
    execution_id: str
    source: str  # "email" or "portal"

    # Input payload — set by intake services
    unified_payload: dict

    # Context loading output (Step 7)
    vendor_context: dict | None

    # Query analysis output (Step 8)
    analysis_result: dict | None

    # Routing output (Step 9A)
    routing_decision: dict | None

    # KB search output (Step 9B)
    kb_search_result: dict | None

    # Path decision — "A", "B", or "C"
    processing_path: str | None

    # Draft generation output (Step 10A or 10B)
    draft_response: dict | None

    # Quality gate output (Step 11)
    quality_gate_result: dict | None

    # Ticket creation output (Step 12)
    ticket_info: dict | None

    # Path C triage output
    triage_package: dict | None

    # Phase 6 Step 15: Path B resolution-from-notes flow.
    # When a ServiceNow webhook fires a RESOLVED status, the graph re-enters
    # at a special entry that loads these fields and skips the normal path.
    resolution_mode: bool
    work_notes: str

    # Phase 6 resume context — set by sqs_consumer when the incoming SQS
    # message has resume_context.action == "prepare_resolution". Steers the
    # graph entry-switch into the resolution-from-notes branch.
    resume_context: dict | None

    # Follow-up info merged in from a later reply on the same thread.
    # Populated by ClosureService.handle_followup_info on the prior case.
    # context_loading reads this and surfaces it to Query Analysis so the
    # late attachment / clarification is folded into the current run.
    additional_context: list[dict]

    # Pipeline status tracking
    status: str  # RECEIVED, ANALYZING, ROUTING, DRAFTING, VALIDATING, DELIVERING, RESOLVED, PAUSED, FAILED, MERGED_INTO_PARENT
    error: str | None

    # Timestamps (IST, ISO format strings)
    created_at: str
    updated_at: str
