"""Module: orchestration/studio.py

LangGraph Studio entry point for graph visualization.

Fully self-contained — no imports from src/ modules. This avoids
ModuleNotFoundError when langgraph dev loads this file, since it
does not add src/ to sys.path.

Usage in langgraph.json:
    "graphs": {"vqms_pipeline": "./src/orchestration/studio.py:graph"}
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph


# ===========================
# Inline PipelineState (copy of models/workflow.py PipelineState)
# Duplicated here so studio.py has zero project imports.
# ===========================

class PipelineState(TypedDict, total=False):
    """Minimal copy of the pipeline state for Studio visualization."""

    query_id: str
    correlation_id: str
    execution_id: str
    source: str
    unified_payload: dict
    vendor_context: dict | None
    analysis_result: dict | None
    routing_decision: dict | None
    kb_search_result: dict | None
    processing_path: str | None
    draft_response: dict | None
    quality_gate_result: dict | None
    ticket_info: dict | None
    triage_package: dict | None
    status: str
    error: str | None
    created_at: str
    updated_at: str


# ===========================
# Stub node functions
# ===========================

async def context_loading(state: PipelineState) -> dict:
    """Step 7: Load vendor profile + history."""
    return {}


async def query_analysis(state: PipelineState) -> dict:
    """Step 8: LLM Call #1 — intent, entities, confidence."""
    return {}


async def confidence_check(state: PipelineState) -> dict:
    """Decision Point 1: confidence gate."""
    return {}


async def routing(state: PipelineState) -> dict:
    """Step 9A: Deterministic team/SLA assignment."""
    return {}


async def kb_search(state: PipelineState) -> dict:
    """Step 9B: Embed + pgvector cosine similarity."""
    return {}


async def path_decision(state: PipelineState) -> dict:
    """Decision Point 2: Path A vs Path B."""
    return {}


async def triage(state: PipelineState) -> dict:
    """Path C: Create TriagePackage, pause for human review."""
    return {"status": "PAUSED"}


async def resolution(state: PipelineState) -> dict:
    """Step 10A (Path A): LLM Call #2 — full answer from KB."""
    return {}


async def acknowledgment(state: PipelineState) -> dict:
    """Step 10B (Path B): Acknowledgment-only email."""
    return {}


async def quality_gate(state: PipelineState) -> dict:
    """Step 11: 7 quality checks on drafted email."""
    return {}


async def delivery(state: PipelineState) -> dict:
    """Step 12: Create ticket + send email."""
    return {"status": "RESOLVED"}


# ===========================
# Conditional edge functions
# ===========================

def route_after_confidence_check(state: PipelineState) -> str:
    """Route based on confidence check result."""
    if state.get("processing_path") == "C":
        return "triage"
    return "routing"


def route_after_path_decision(state: PipelineState) -> str:
    """Route based on path decision result."""
    if state.get("processing_path") == "A":
        return "resolution"
    return "acknowledgment"


# ===========================
# Build the graph
# ===========================

def _build() -> StateGraph:
    """Build and compile the VQMS pipeline graph."""
    g = StateGraph(PipelineState)

    # Register nodes
    g.add_node("context_loading", context_loading)
    g.add_node("query_analysis", query_analysis)
    g.add_node("confidence_check", confidence_check)
    g.add_node("routing", routing)
    g.add_node("kb_search", kb_search)
    g.add_node("path_decision", path_decision)
    g.add_node("triage", triage)
    g.add_node("resolution", resolution)
    g.add_node("acknowledgment", acknowledgment)
    g.add_node("quality_gate", quality_gate)
    g.add_node("delivery", delivery)

    # Wire edges (identical to orchestration/graph.py)
    g.set_entry_point("context_loading")
    g.add_edge("context_loading", "query_analysis")
    g.add_edge("query_analysis", "confidence_check")

    g.add_conditional_edges(
        "confidence_check",
        route_after_confidence_check,
        {"routing": "routing", "triage": "triage"},
    )
    g.add_edge("triage", END)

    g.add_edge("routing", "kb_search")
    g.add_edge("kb_search", "path_decision")

    g.add_conditional_edges(
        "path_decision",
        route_after_path_decision,
        {"resolution": "resolution", "acknowledgment": "acknowledgment"},
    )

    g.add_edge("resolution", "quality_gate")
    g.add_edge("acknowledgment", "quality_gate")
    g.add_edge("quality_gate", "delivery")
    g.add_edge("delivery", END)

    return g.compile()


# Module-level variable that langgraph dev picks up
graph = _build()
