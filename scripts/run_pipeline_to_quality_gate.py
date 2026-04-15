# ruff: noqa: E402
"""Script: run_pipeline_to_quality_gate.py

VQMS Pipeline Demo: Portal Submission -> Quality Gate (Steps 7-11).

This script runs the AI pipeline from START through Step 11 (Quality Gate),
excluding Step 12 (Delivery). It demonstrates the full analysis-to-validation
flow without creating ServiceNow tickets or sending emails.

Pipeline flow:
  Step 7:   Context Loading (vendor profile, episodic memory)
  Step 8:   Query Analysis Agent (LLM Call #1 -> intent, entities, confidence)
  Step 8.5: Confidence Check (>= 0.85 -> pass, < 0.85 -> Path C)
  Step 9A:  Routing (deterministic rules -> team, SLA)
  Step 9B:  KB Search (embed -> pgvector cosine similarity)
  Step 9.5: Path Decision (KB match >= 80% -> Path A, else -> Path B)
  Step 10A: Resolution draft (Path A) / Step 10B: Acknowledgment draft (Path B)
  Step 11:  Quality Gate (7 deterministic checks on draft email)

The graph ends at quality_gate -> END. No ServiceNow ticket creation,
no Graph API email send.

Usage:
    uv run python scripts/run_pipeline_to_quality_gate.py
    uv run python scripts/run_pipeline_to_quality_gate.py --skip-salesforce
    uv run python scripts/run_pipeline_to_quality_gate.py --query-type DELIVERY_SHIPMENT --subject "Late delivery on PO-2026-999" --description "Our PO-2026-999 delivery is 3 days late. We need an ETA."

Prerequisites:
    1. .env configured with AWS, PostgreSQL, Bedrock credentials
    2. Pipeline is NOT required to be running separately
    3. ServiceNow / Graph API credentials NOT needed (delivery excluded)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from unittest.mock import AsyncMock

# ---------------------------------------------------------------------------
# Bootstrap — must happen before project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from config.settings import get_settings
from adapters.llm_gateway import LLMGateway
from adapters.salesforce import SalesforceConnector
from db.connection import PostgresConnector
from models.query import QUERY_TYPES
from orchestration.nodes.acknowledgment import AcknowledgmentNode
from orchestration.nodes.confidence_check import ConfidenceCheckNode
from orchestration.nodes.context_loading import ContextLoadingNode
from orchestration.nodes.kb_search import KBSearchNode
from orchestration.nodes.path_decision import PathDecisionNode
from orchestration.nodes.quality_gate import QualityGateNode
from orchestration.nodes.query_analysis import QueryAnalysisNode
from orchestration.nodes.resolution import ResolutionNode
from orchestration.nodes.routing import RoutingNode
from orchestration.prompts.prompt_manager import PromptManager
from models.workflow import PipelineState
from utils.helpers import IdGenerator, TimeHelper
from utils.logger import LoggingSetup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LoggingSetup.configure()
logger = logging.getLogger("scripts.run_pipeline_to_quality_gate")

# Silence noisy third-party loggers
for _noisy in ("botocore", "urllib3", "msal", "httpx", "httpcore",
               "openai._base_client", "pdfminer", "pdfplumber"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Build truncated graph (Steps 7-11, no delivery)
# ---------------------------------------------------------------------------

def build_quality_gate_graph(
    context_loading_node: ContextLoadingNode,
    query_analysis_node: QueryAnalysisNode,
    confidence_check_node: ConfidenceCheckNode,
    routing_node: RoutingNode,
    kb_search_node: KBSearchNode,
    path_decision_node: PathDecisionNode,
    resolution_node: ResolutionNode,
    acknowledgment_node: AcknowledgmentNode,
    quality_gate_node: QualityGateNode,
):
    """Build a LangGraph pipeline that ends at quality_gate (no delivery).

    Same structure as the full pipeline graph but quality_gate -> END
    instead of quality_gate -> delivery -> END.
    """
    from langgraph.graph import END, StateGraph
    from orchestration.graph import (
        route_after_confidence_check,
        route_after_path_decision,
        triage_placeholder,
    )

    graph = StateGraph(PipelineState)

    # Register nodes (Steps 7-11, no Step 12)
    graph.add_node("context_loading", context_loading_node.execute)
    graph.add_node("query_analysis", query_analysis_node.execute)
    graph.add_node("confidence_check", confidence_check_node.execute)
    graph.add_node("routing", routing_node.execute)
    graph.add_node("kb_search", kb_search_node.execute)
    graph.add_node("path_decision", path_decision_node.execute)
    graph.add_node("resolution", resolution_node.execute)
    graph.add_node("acknowledgment", acknowledgment_node.execute)
    graph.add_node("quality_gate", quality_gate_node.execute)
    graph.add_node("triage", triage_placeholder)

    # Wire edges
    graph.set_entry_point("context_loading")
    graph.add_edge("context_loading", "query_analysis")
    graph.add_edge("query_analysis", "confidence_check")

    # Confidence check -> routing (continue) or triage (Path C)
    graph.add_conditional_edges(
        "confidence_check",
        route_after_confidence_check,
        {"routing": "routing", "triage": "triage"},
    )
    graph.add_edge("triage", END)

    # Routing -> KB search -> path decision
    graph.add_edge("routing", "kb_search")
    graph.add_edge("kb_search", "path_decision")

    # Path decision -> resolution (Path A) or acknowledgment (Path B)
    graph.add_conditional_edges(
        "path_decision",
        route_after_path_decision,
        {"resolution": "resolution", "acknowledgment": "acknowledgment"},
    )

    # Both paths converge -> quality_gate -> END (no delivery)
    graph.add_edge("resolution", "quality_gate")
    graph.add_edge("acknowledgment", "quality_gate")
    graph.add_edge("quality_gate", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

DIVIDER = "=" * 70
SUBDIV = "-" * 60


def banner(text: str) -> None:
    """Print a section banner."""
    print(f"\n{DIVIDER}")
    print(f"  {text}")
    print(DIVIDER)


def step(num: str, title: str) -> None:
    """Print a step header."""
    print(f"\n{SUBDIV}")
    print(f"  Step {num}: {title}")
    print(SUBDIV)


def result(label: str, value: str, indent: int = 4) -> None:
    """Print a key-value result line."""
    safe_value = value.encode("ascii", errors="replace").decode("ascii")
    safe_label = label.encode("ascii", errors="replace").decode("ascii")
    print(f"{' ' * indent}{safe_label}: {safe_value}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_pipeline_to_quality_gate(
    *,
    query_type: str,
    subject: str,
    description: str,
    priority: str,
    vendor_id: str,
    skip_salesforce: bool,
) -> None:
    """Run the pipeline from START through Quality Gate (Steps 7-11).

    Creates a synthetic portal-style submission and feeds it through
    the LangGraph AI pipeline, stopping at quality_gate (Step 11).
    No ServiceNow ticket or Graph API email.
    """
    settings = get_settings()
    pipeline_start = time.time()

    banner("VQMS Pipeline: START -> Quality Gate (Steps 7-11)")
    result("Query Type", f"{query_type} ({QUERY_TYPES.get(query_type, '?')})", indent=2)
    result("Subject", subject, indent=2)
    result("Priority", priority, indent=2)
    result("Vendor ID", vendor_id, indent=2)
    result("LLM Provider", settings.llm_provider, indent=2)
    result("Skip Salesforce", str(skip_salesforce), indent=2)
    print("\n    NOTE: Delivery (Step 12) is EXCLUDED from this run.")

    postgres: PostgresConnector | None = None

    try:
        # =================================================================
        # Step 0: Initialize connectors
        # =================================================================
        step("0", "Initialize connectors")

        # --- PostgreSQL ---
        print("    Connecting to PostgreSQL via SSH tunnel...")
        postgres = PostgresConnector(settings)
        await postgres.connect()
        result("PostgreSQL", "[OK]")

        # --- LLM Gateway ---
        llm_gateway = LLMGateway(settings)
        result("LLM Gateway", f"[OK] (mode: {settings.llm_provider})")

        # --- Salesforce (or mock if skipped) ---
        if skip_salesforce:
            salesforce = AsyncMock()
            salesforce.identify_vendor.return_value = None
            salesforce.find_vendor_by_id.return_value = None
            result("Salesforce", "[SKIP] Using mock")
        else:
            salesforce = SalesforceConnector(settings)
            result("Salesforce", "[OK]")

        # --- Prompt Manager ---
        prompt_manager = PromptManager()
        result("Prompt Manager", "[OK]")

        # =================================================================
        # Build truncated graph (Steps 7-11)
        # =================================================================
        step("GRAPH", "Build truncated pipeline (quality_gate -> END)")

        context_loading = ContextLoadingNode(
            postgres=postgres, salesforce=salesforce, settings=settings,
        )
        query_analysis = QueryAnalysisNode(
            bedrock=llm_gateway, prompt_manager=prompt_manager, settings=settings,
        )
        confidence_check = ConfidenceCheckNode(settings=settings)
        routing = RoutingNode(settings=settings)
        kb_search = KBSearchNode(
            bedrock=llm_gateway, postgres=postgres, settings=settings,
        )
        path_decision = PathDecisionNode(settings=settings)
        resolution = ResolutionNode(
            llm_gateway=llm_gateway, prompt_manager=prompt_manager, settings=settings,
        )
        acknowledgment = AcknowledgmentNode(
            llm_gateway=llm_gateway, prompt_manager=prompt_manager, settings=settings,
        )
        quality_gate = QualityGateNode(settings=settings)

        compiled_graph = build_quality_gate_graph(
            context_loading_node=context_loading,
            query_analysis_node=query_analysis,
            confidence_check_node=confidence_check,
            routing_node=routing,
            kb_search_node=kb_search,
            path_decision_node=path_decision,
            resolution_node=resolution,
            acknowledgment_node=acknowledgment,
            quality_gate_node=quality_gate,
        )
        result("Graph", "[OK] quality_gate -> END (no delivery)")

        # =================================================================
        # Build initial pipeline state (simulated portal submission)
        # =================================================================
        step("INPUT", "Build pipeline state (portal submission)")

        query_id = IdGenerator.generate_query_id()
        correlation_id = IdGenerator.generate_correlation_id()
        execution_id = IdGenerator.generate_execution_id()
        now = TimeHelper.ist_now().isoformat()

        unified_payload = {
            "query_id": query_id,
            "correlation_id": correlation_id,
            "execution_id": execution_id,
            "source": "portal",
            "vendor_id": vendor_id,
            "subject": subject,
            "body": description,
            "query_type": query_type,
            "priority": priority,
            "received_at": now,
            "attachments": [],
            "thread_status": "NEW",
            "metadata": {"submitted_via": "run_pipeline_to_quality_gate.py"},
        }

        initial_state: dict = {
            "query_id": query_id,
            "correlation_id": correlation_id,
            "execution_id": execution_id,
            "source": "portal",
            "unified_payload": unified_payload,
            "status": "RECEIVED",
            "created_at": now,
            "updated_at": now,
        }

        result("Query ID", query_id)
        result("Correlation ID", correlation_id)
        result("Body length", f"{len(description)} chars")

        # =================================================================
        # Run the pipeline
        # =================================================================
        banner("Running Pipeline (Steps 7 -> 8 -> 8.5 -> 9A -> 9B -> 10 -> 11)")

        ai_start = time.time()

        try:
            pipeline_result = await compiled_graph.ainvoke(initial_state)
        except Exception as e:
            print(f"\n    [ERROR] Pipeline failed: {e}")
            logger.exception("Pipeline execution failed")
            return

        ai_elapsed = time.time() - ai_start
        total_elapsed = time.time() - pipeline_start

        # =================================================================
        # Display Results
        # =================================================================
        banner("PIPELINE RESULTS")

        # --- Analysis Result (Step 8) ---
        analysis = pipeline_result.get("analysis_result")
        if analysis:
            print("  --- Query Analysis (Step 8) ---")
            result("Intent", analysis.get("intent_classification", "?"), indent=2)
            result("Confidence", str(analysis.get("confidence_score", "?")), indent=2)
            result("Urgency", analysis.get("urgency_level", "?"), indent=2)
            result("Sentiment", analysis.get("sentiment", "?"), indent=2)
            result("Multi-issue", str(analysis.get("multi_issue_detected", False)), indent=2)
            result("Category", analysis.get("suggested_category", "?"), indent=2)
            result("Model", analysis.get("model_id", "?"), indent=2)
            result("Tokens in", str(analysis.get("tokens_in", "?")), indent=2)
            result("Tokens out", str(analysis.get("tokens_out", "?")), indent=2)
            result("Analysis time", f"{analysis.get('analysis_duration_ms', '?')}ms", indent=2)

            entities = analysis.get("extracted_entities", {})
            if entities:
                print("\n  --- Extracted Entities ---")
                for key, vals in entities.items():
                    if vals:
                        result(key, str(vals), indent=2)
        else:
            result("Analysis", "[ERROR] No analysis result", indent=2)

        # --- Confidence Check (Step 8.5) ---
        processing_path = pipeline_result.get("processing_path")
        confidence = analysis.get("confidence_score", 0.0) if analysis else 0.0
        print("\n  --- Confidence Check (Step 8.5) ---")
        result("Confidence", str(confidence), indent=2)
        result("Threshold", "0.85", indent=2)
        if processing_path == "C":
            result("Decision", "BELOW THRESHOLD -> Path C (human review)", indent=2)
        else:
            result("Decision", "ABOVE THRESHOLD -> continue to routing + KB search", indent=2)

        # --- Routing Decision (Step 9A) ---
        routing_result = pipeline_result.get("routing_decision")
        if routing_result:
            print("\n  --- Routing (Step 9A) ---")
            result("Team", routing_result.get("assigned_team", "?"), indent=2)
            sla = routing_result.get("sla_target", {})
            result("SLA hours", str(sla.get("total_hours", "?")), indent=2)
            result("SLA deadline", str(sla.get("deadline_at", "N/A")), indent=2)
            result("Priority", routing_result.get("priority", "?"), indent=2)
            result("Category", routing_result.get("category", "?"), indent=2)
            result("Reason", routing_result.get("routing_reason", "?"), indent=2)
        elif processing_path != "C":
            result("Routing", "[NOT REACHED]", indent=2)

        # --- KB Search (Step 9B) ---
        kb = pipeline_result.get("kb_search_result")
        if kb:
            print("\n  --- KB Search (Step 9B) ---")
            matches = kb.get("matches", [])
            result("Total matches", str(len(matches)), indent=2)
            result("Best score", str(kb.get("best_match_score", "None")), indent=2)
            result("Has sufficient", str(kb.get("has_sufficient_match", False)), indent=2)
            result("Search time", f"{kb.get('search_duration_ms', '?')}ms", indent=2)
            result("Embedding model", kb.get("query_embedding_model", "?"), indent=2)

            if matches:
                print("\n  --- Top KB Matches ---")
                for i, m in enumerate(matches[:3]):
                    result(
                        f"#{i + 1}",
                        f"{m.get('title', m.get('article_id', '?'))} "
                        f"(score={m.get('similarity_score', 0):.3f})",
                        indent=2,
                    )
        elif processing_path != "C":
            result("KB Search", "[NOT REACHED]", indent=2)

        # --- Path Decision (Step 9.5) ---
        print("\n  --- Path Decision (Step 9.5) ---")
        path_labels = {
            "A": "Path A -- AI-Resolved (KB has the answer)",
            "B": "Path B -- Human-Team-Resolved (KB lacks specific facts)",
            "C": "Path C -- Low-Confidence (human reviewer validates)",
        }
        result(
            "Selected path",
            path_labels.get(processing_path, f"Path {processing_path or '?'}"),
            indent=2,
        )

        # --- Draft Response (Step 10) ---
        draft = pipeline_result.get("draft_response")
        if draft:
            draft_type = draft.get("draft_type", "?")
            print(f"\n  --- Draft Response (Step 10{'A' if draft_type == 'RESOLUTION' else 'B'}) ---")
            result("Draft type", draft_type, indent=2)
            result("Subject", draft.get("subject", "?"), indent=2)
            result("Confidence", str(draft.get("confidence", "?")), indent=2)
            result("Model", draft.get("model_id", "?"), indent=2)
            result("Tokens in", str(draft.get("tokens_in", "?")), indent=2)
            result("Tokens out", str(draft.get("tokens_out", "?")), indent=2)
            result("Draft time", f"{draft.get('draft_duration_ms', '?')}ms", indent=2)

            sources = draft.get("sources", [])
            if sources:
                result("Sources", ", ".join(sources), indent=2)

            body = draft.get("body", "")
            if body:
                # Show first 500 chars of the email body
                preview = body[:500]
                print("\n  --- Email Draft Preview (first 500 chars) ---")
                print(f"    {preview}")
                if len(body) > 500:
                    print(f"    ... ({len(body) - 500} more chars)")
        elif processing_path != "C":
            result("Draft", "[NOT REACHED]", indent=2)

        # --- Quality Gate (Step 11) ---
        qg = pipeline_result.get("quality_gate_result")
        if qg:
            passed = qg.get("passed", False)
            checks_run = qg.get("checks_run", 0)
            checks_passed = qg.get("checks_passed", 0)
            failed = qg.get("failed_checks", [])

            print("\n  --- Quality Gate (Step 11) ---")
            result("Passed", "YES" if passed else "NO", indent=2)
            result("Checks", f"{checks_passed}/{checks_run} passed", indent=2)

            if failed:
                result("Failed checks", ", ".join(failed), indent=2)
            else:
                result("Failed checks", "None", indent=2)
        elif processing_path != "C":
            result("Quality Gate", "[NOT REACHED]", indent=2)

        # --- Final Status ---
        print("\n  --- Pipeline Status ---")
        result("Final status", pipeline_result.get("status", "?"), indent=2)
        result("Processing path", processing_path or "?", indent=2)

        error = pipeline_result.get("error")
        if error:
            result("Error", str(error), indent=2)

        # --- Timing Summary ---
        print(f"\n{SUBDIV}")
        print("  --- Timing ---")
        result("AI pipeline", f"{ai_elapsed:.1f}s", indent=2)
        result("Total (incl. setup)", f"{total_elapsed:.1f}s", indent=2)

        # --- What Would Happen Next ---
        print(f"\n{SUBDIV}")
        print("  --- What Would Happen Next (Step 12 - EXCLUDED) ---")
        if processing_path == "A":
            print("    1. Delivery node would create a ServiceNow ticket (INC-XXXXXXX)")
            print("    2. Replace 'PENDING' in draft with real ticket number")
            print("    3. Send RESOLUTION email to vendor via Graph API")
            print("    4. Status -> RESOLVED")
        elif processing_path == "B":
            print("    1. Delivery node would create a ServiceNow ticket (INC-XXXXXXX)")
            print("    2. Replace 'PENDING' in draft with real ticket number")
            print("    3. Send ACKNOWLEDGMENT email to vendor via Graph API")
            print("    4. Status -> AWAITING_RESOLUTION (human team investigates)")
        elif processing_path == "C":
            print("    Workflow PAUSED for human review. No delivery.")
        print()

    except Exception:
        logger.exception("Pipeline execution failed")
        print("\n    [FAIL] Pipeline failed -- check logs above for details")
        raise
    finally:
        if postgres:
            await postgres.disconnect()
        print("    Connectors closed.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# Default test query that exercises a typical invoice scenario
DEFAULT_SUBJECT = "Invoice INV-2026-TEST payment status inquiry"
DEFAULT_DESCRIPTION = (
    "We submitted invoice INV-2026-TEST on 2026-04-01 for purchase order PO-2026-001. "
    "The total amount is $15,000 and payment was due on 2026-04-10. "
    "We have not received payment yet and need an update on the processing status. "
    "Our accounts receivable team needs this resolved within the week. "
    "Please provide the expected payment date and any issues causing the delay."
)


def main() -> None:
    """Parse CLI args and run the pipeline to quality gate."""
    valid_types = list(QUERY_TYPES.keys())

    parser = argparse.ArgumentParser(
        description="VQMS: Run AI pipeline from START to Quality Gate (Steps 7-11, no delivery)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Default invoice query\n"
            "  uv run python scripts/run_pipeline_to_quality_gate.py\n\n"
            "  # Custom delivery query\n"
            "  uv run python scripts/run_pipeline_to_quality_gate.py \\\n"
            '    --query-type DELIVERY_SHIPMENT \\\n'
            '    --subject "Late delivery on PO-2026-999" \\\n'
            '    --description "Our PO-2026-999 delivery is 3 days overdue. Need ETA."\n\n'
            "  # Skip Salesforce if no credentials\n"
            "  uv run python scripts/run_pipeline_to_quality_gate.py --skip-salesforce\n\n"
            f"  Valid query types: {', '.join(valid_types)}\n"
        ),
    )
    parser.add_argument(
        "--query-type",
        type=str,
        default="INVOICE_PAYMENT",
        choices=valid_types,
        help=f"Query type (default: INVOICE_PAYMENT). One of: {', '.join(valid_types)}",
    )
    parser.add_argument(
        "--subject",
        type=str,
        default=DEFAULT_SUBJECT,
        help="Query subject line",
    )
    parser.add_argument(
        "--description",
        type=str,
        default=DEFAULT_DESCRIPTION,
        help="Query description / body text",
    )
    parser.add_argument(
        "--priority",
        type=str,
        default="MEDIUM",
        choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        help="Query priority (default: MEDIUM)",
    )
    parser.add_argument(
        "--vendor-id",
        type=str,
        default="V-TEST-001",
        help="Vendor ID (default: V-TEST-001)",
    )
    parser.add_argument(
        "--skip-salesforce",
        action="store_true",
        help="Skip Salesforce vendor lookup (use mock).",
    )
    args = parser.parse_args()

    asyncio.run(
        run_pipeline_to_quality_gate(
            query_type=args.query_type,
            subject=args.subject,
            description=args.description,
            priority=args.priority,
            vendor_id=args.vendor_id,
            skip_salesforce=args.skip_salesforce,
        )
    )


if __name__ == "__main__":
    main()
