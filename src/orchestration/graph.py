"""Module: orchestration/graph.py

LangGraph orchestrator for the VQMS AI pipeline.

Wires all pipeline nodes into a StateGraph with conditional
edges for confidence check (Path C branch) and path decision
(Path A vs Path B branch).

Graph flow:
    START → context_loading → query_analysis → confidence_check
        ─(processing_path=="C")─→ triage_placeholder → END
        ─(else)─→ routing → kb_search → path_decision
            ─(processing_path=="A")─→ resolution_placeholder → quality_gate_placeholder → delivery_placeholder → END
            ─(processing_path=="B")─→ acknowledgment_placeholder → quality_gate_placeholder → delivery_placeholder → END

Placeholder nodes for Phase 4 (resolution, acknowledgment,
quality_gate, delivery, triage) return state unchanged with
a TODO log.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from models.workflow import PipelineState
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


# ===========================
# Placeholder Nodes (Phase 4)
# ===========================
# These return state unchanged and log a TODO.
# They will be replaced with real implementations in Phase 4.


async def triage_placeholder(state: PipelineState) -> PipelineState:
    """Placeholder for Path C triage node (Phase 5)."""
    logger.info(
        "Triage placeholder reached — Path C",
        step="triage_placeholder",
        correlation_id=state.get("correlation_id", ""),
    )
    return {
        "status": "PAUSED",
        "updated_at": TimeHelper.ist_now().isoformat(),
    }


async def resolution_placeholder(state: PipelineState) -> PipelineState:
    """Placeholder for Path A resolution node (Phase 4)."""
    logger.info(
        "Resolution placeholder reached — Path A",
        step="resolution_placeholder",
        correlation_id=state.get("correlation_id", ""),
    )
    return {
        "updated_at": TimeHelper.ist_now().isoformat(),
    }


async def acknowledgment_placeholder(state: PipelineState) -> PipelineState:
    """Placeholder for Path B acknowledgment node (Phase 4)."""
    logger.info(
        "Acknowledgment placeholder reached — Path B",
        step="acknowledgment_placeholder",
        correlation_id=state.get("correlation_id", ""),
    )
    return {
        "updated_at": TimeHelper.ist_now().isoformat(),
    }


async def quality_gate_placeholder(state: PipelineState) -> PipelineState:
    """Placeholder for quality gate node (Phase 4)."""
    logger.info(
        "Quality gate placeholder reached",
        step="quality_gate_placeholder",
        correlation_id=state.get("correlation_id", ""),
    )
    return {
        "updated_at": TimeHelper.ist_now().isoformat(),
    }


async def delivery_placeholder(state: PipelineState) -> PipelineState:
    """Placeholder for delivery node (Phase 4)."""
    logger.info(
        "Delivery placeholder reached",
        step="delivery_placeholder",
        correlation_id=state.get("correlation_id", ""),
    )
    return {
        "status": "RESOLVED",
        "updated_at": TimeHelper.ist_now().isoformat(),
    }


# ===========================
# Conditional Edge Functions
# ===========================


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
# Graph Builder
# ===========================


def build_pipeline_graph(
    context_loading_node: Any,
    query_analysis_node: Any,
    confidence_check_node: Any,
    routing_node: Any,
    kb_search_node: Any,
    path_decision_node: Any,
) -> Any:
    """Build the LangGraph pipeline graph with all nodes and edges.

    Each node parameter is expected to have an `execute(state)` method
    that takes PipelineState and returns a partial PipelineState update.

    Args:
        context_loading_node: Step 7 — loads vendor context.
        query_analysis_node: Step 8 — LLM Call #1, intent + entities.
        confidence_check_node: Decision Point 1 — confidence gate.
        routing_node: Step 9A — deterministic team/SLA assignment.
        kb_search_node: Step 9B — embed + pgvector search.
        path_decision_node: Decision Point 2 — Path A vs Path B.

    Returns:
        Compiled LangGraph StateGraph ready for invocation.
    """
    graph = StateGraph(PipelineState)

    # Register real nodes (Steps 7-9)
    graph.add_node("context_loading", context_loading_node.execute)
    graph.add_node("query_analysis", query_analysis_node.execute)
    graph.add_node("confidence_check", confidence_check_node.execute)
    graph.add_node("routing", routing_node.execute)
    graph.add_node("kb_search", kb_search_node.execute)
    graph.add_node("path_decision", path_decision_node.execute)

    # Register placeholder nodes (Phase 4+)
    graph.add_node("triage", triage_placeholder)
    graph.add_node("resolution", resolution_placeholder)
    graph.add_node("acknowledgment", acknowledgment_placeholder)
    graph.add_node("quality_gate", quality_gate_placeholder)
    graph.add_node("delivery", delivery_placeholder)

    # Wire edges
    # START → context_loading → query_analysis → confidence_check
    graph.set_entry_point("context_loading")
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
    graph.add_edge("quality_gate", "delivery")
    graph.add_edge("delivery", END)

    return graph.compile()
