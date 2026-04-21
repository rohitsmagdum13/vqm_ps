"""Module: orchestration/graph.py

LangGraph orchestrator for the VQMS AI pipeline.

Wires all pipeline nodes into a StateGraph with conditional
edges for confidence check (Path C branch), path decision
(Path A vs Path B branch), and the Phase 6 resolution-from-notes
re-entry (Step 15).

Graph flow:
    START (entry switch)
      ─(resume_context.action=="prepare_resolution")─→ resolution_from_notes
                                                          ↓
                                                      quality_gate
                                                          ↓
                                                       delivery → END
      ─(else)─→ context_loading → query_analysis → confidence_check
          ─(processing_path=="C")─→ triage → END
          ─(else)─→ routing → kb_search → path_decision
              ─(processing_path=="A")─→ resolution → quality_gate → delivery → END
              ─(processing_path=="B")─→ acknowledgment → quality_gate → delivery → END

Step 15 (resolution-from-notes) is triggered by a ServiceNow webhook
(see src/api/routes/webhooks.py -> servicenow_webhook). The webhook
re-enqueues the case with resume_context.action="prepare_resolution";
sqs_consumer.py surfaces that into PipelineState so the entry switch
below routes the case directly into the resolution-from-notes branch.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from models.workflow import PipelineState

logger = structlog.get_logger(__name__)


# ===========================
# Conditional Edge Functions
# ===========================


def route_from_entry(state: PipelineState) -> str:
    """Decide whether this run is a normal intake or a resume.

    Phase 6: ServiceNow sets resume_context.action == "prepare_resolution"
    when the human team finishes an investigation. In that case the
    pipeline must skip context_loading / query_analysis (already done
    on the first run) and jump straight to resolution-from-notes.
    """
    resume_context = state.get("resume_context")
    if isinstance(resume_context, dict) and resume_context.get("action") == "prepare_resolution":
        return "resolution_from_notes"
    return "context_loading"


def route_after_confidence_check(state: PipelineState) -> str:
    """Route based on confidence check result.

    If processing_path is "C", route to triage (Path C).
    Otherwise, continue to routing node.
    """
    processing_path = state.get("processing_path")
    if processing_path == "C":
        return "triage"
    return "routing"


def route_after_path_decision(state: PipelineState) -> str:
    """Route based on path decision result.

    Path A → resolution (KB has the answer)
    Path B → acknowledgment (human team investigates)
    """
    processing_path = state.get("processing_path")
    if processing_path == "A":
        return "resolution"
    return "acknowledgment"


# ===========================
# Entry passthrough node
# ===========================


async def _entry_passthrough(state: PipelineState) -> PipelineState:
    """No-op node used so START can go through a conditional edge.

    LangGraph's set_entry_point is a hard edge; to branch at the top
    we set entry to this passthrough and use a conditional edge from
    here. Returning an empty dict means "make no state changes."
    """
    return {}


# ===========================
# Graph Builder
# ===========================


def build_pipeline_graph(
    context_loading_node: Any,
    query_analysis_node: Any,
    confidence_check_node: Any,
    triage_node: Any,
    routing_node: Any,
    kb_search_node: Any,
    path_decision_node: Any,
    resolution_node: Any,
    acknowledgment_node: Any,
    quality_gate_node: Any,
    delivery_node: Any,
    resolution_from_notes_node: Any,
) -> Any:
    """Build the LangGraph pipeline graph with all nodes and edges.

    Each node parameter is expected to have an `execute(state)` method
    that takes PipelineState and returns a partial PipelineState update.

    Args:
        context_loading_node: Step 7 — loads vendor context.
        query_analysis_node: Step 8 — LLM Call #1, intent + entities.
        confidence_check_node: Decision Point 1 — confidence gate.
        triage_node: Path C — builds triage package and pauses workflow
            when confidence is below threshold.
        routing_node: Step 9A — deterministic team/SLA assignment.
        kb_search_node: Step 9B — embed + pgvector search.
        path_decision_node: Decision Point 2 — Path A vs Path B.
        resolution_node: Step 10A — Path A full resolution draft.
        acknowledgment_node: Step 10B — Path B acknowledgment draft.
        quality_gate_node: Step 11 — 7-check validation.
        delivery_node: Step 12 — ServiceNow ticket + Graph API email.
        resolution_from_notes_node: Phase 6 Step 15 — Path B resolution
            drafted from ServiceNow work notes.

    Returns:
        Compiled LangGraph StateGraph ready for invocation.
    """
    graph = StateGraph(PipelineState)

    # Entry passthrough — lets us add a conditional edge at the very top.
    graph.add_node("entry", _entry_passthrough)

    # Register all real nodes (Steps 7-12, Step 15, Path C)
    graph.add_node("context_loading", context_loading_node.execute)
    graph.add_node("query_analysis", query_analysis_node.execute)
    graph.add_node("confidence_check", confidence_check_node.execute)
    graph.add_node("routing", routing_node.execute)
    graph.add_node("kb_search", kb_search_node.execute)
    graph.add_node("path_decision", path_decision_node.execute)
    graph.add_node("resolution", resolution_node.execute)
    graph.add_node("acknowledgment", acknowledgment_node.execute)
    graph.add_node("quality_gate", quality_gate_node.execute)
    graph.add_node("delivery", delivery_node.execute)
    graph.add_node("triage", triage_node.execute)
    graph.add_node("resolution_from_notes", resolution_from_notes_node.execute)

    # Top-level entry switch — normal intake vs. Step 15 resume.
    graph.set_entry_point("entry")
    graph.add_conditional_edges(
        "entry",
        route_from_entry,
        {
            "context_loading": "context_loading",
            "resolution_from_notes": "resolution_from_notes",
        },
    )

    # Normal intake: context_loading → query_analysis → confidence_check
    graph.add_edge("context_loading", "query_analysis")
    graph.add_edge("query_analysis", "confidence_check")

    # Confidence check → routing (continue) or triage (Path C)
    graph.add_conditional_edges(
        "confidence_check",
        route_after_confidence_check,
        {"routing": "routing", "triage": "triage"},
    )

    # Triage → END (workflow pauses)
    graph.add_edge("triage", END)

    # Routing → KB search → path decision
    graph.add_edge("routing", "kb_search")
    graph.add_edge("kb_search", "path_decision")

    # Path decision → resolution (Path A) or acknowledgment (Path B)
    graph.add_conditional_edges(
        "path_decision",
        route_after_path_decision,
        {"resolution": "resolution", "acknowledgment": "acknowledgment"},
    )

    # Both paths converge → quality gate → delivery → END
    graph.add_edge("resolution", "quality_gate")
    graph.add_edge("acknowledgment", "quality_gate")

    # Step 15 resolution-from-notes also funnels through the gate + delivery.
    graph.add_edge("resolution_from_notes", "quality_gate")

    graph.add_edge("quality_gate", "delivery")
    graph.add_edge("delivery", END)

    return graph.compile()
