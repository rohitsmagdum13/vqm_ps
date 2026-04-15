# ruff: noqa: E402
"""Script: run_email_to_quality_gate.py

VQMS Full Email Pipeline: Graph API -> S3 -> SQS -> LangGraph -> Quality Gate.

This script runs the COMPLETE email-to-quality-gate pipeline in a single
process, including a real SQS hop between intake and the AI pipeline:

  Phase 1 — Email Intake (Steps E1–E2.9):
    E1:     Fetch email from shared mailbox (MS Graph API)
    E2.1:   Idempotency check (PostgreSQL cache)
    E2.2:   Parse email fields (sender, subject, body, headers)
    E2.3:   Store raw email in S3
    E2.4:   Process attachments (S3 + text extraction)
    E2.5:   Vendor identification (Salesforce 3-step fallback)
    E2.6:   Thread correlation (NEW / EXISTING_OPEN / REPLY_TO_CLOSED)
    E2.7:   Generate tracking IDs (query_id, execution_id, correlation_id)
    E2.8:   Write metadata to PostgreSQL (email_messages + case_execution)
    E2.9a:  Publish EmailParsed event (EventBridge)
    E2.9b:  Enqueue payload to SQS (vqms-email-intake-queue)

  Phase 2 — SQS Consume:
    Pull the message from vqms-email-intake-queue (real SQS hop)

  Phase 3 — AI Pipeline (Steps 7–11, no delivery):
    Step 7:   Context Loading (vendor profile, episodic memory)
    Step 8:   Query Analysis Agent (LLM Call #1 -> intent, entities, confidence)
    Step 8.5: Confidence Check (>= 0.85 -> pass, < 0.85 -> Path C)
    Step 9A:  Routing (deterministic rules -> team, SLA)
    Step 9B:  KB Search (embed -> pgvector cosine similarity)
    Step 9.5: Path Decision (KB match >= 80% -> Path A, else -> Path B)
    Step 10:  Resolution draft (Path A) or Acknowledgment draft (Path B)
    Step 11:  Quality Gate (7 deterministic checks on draft email)

  The graph ends at quality_gate -> END. No ServiceNow ticket creation,
  no Graph API email send (Step 12 excluded).

Usage:
    uv run python scripts/run_email_to_quality_gate.py
    uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..."
    uv run python scripts/run_email_to_quality_gate.py --skip-salesforce
    uv run python scripts/run_email_to_quality_gate.py --no-sqs-hop

Prerequisites:
    1. .env configured with Graph API, AWS, PostgreSQL, Bedrock/OpenAI credentials
    2. SQS queue (vqms-email-intake-queue) must exist (pre-provisioned)
    3. S3 bucket (vqms-data-store) must exist (pre-provisioned)
    4. KB articles seeded: uv run python scripts/seed_knowledge_base.py --clear
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
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
from events.eventbridge import EventBridgeConnector
from adapters.graph_api import GraphAPIConnector
from adapters.llm_gateway import LLMGateway
from adapters.salesforce import SalesforceConnector
from db.connection import PostgresConnector
from models.workflow import PipelineState
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
from queues.sqs import SQSConnector
from services.email_intake import EmailIntakeService
from storage.s3_client import S3Connector
from utils.helpers import IdGenerator, TimeHelper
from utils.logger import LoggingSetup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LoggingSetup.configure()
logger = logging.getLogger("scripts.run_email_to_quality_gate")

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
    """Build a LangGraph pipeline that ends at quality_gate -> END.

    Same structure as the full pipeline but quality_gate -> END
    instead of quality_gate -> delivery -> END. This avoids needing
    ServiceNow or Graph API connectors for the demo.
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

    # Wire edges: START -> context_loading -> ... -> quality_gate -> END
    graph.set_entry_point("context_loading")
    graph.add_edge("context_loading", "query_analysis")
    graph.add_edge("query_analysis", "confidence_check")

    graph.add_conditional_edges(
        "confidence_check",
        route_after_confidence_check,
        {"routing": "routing", "triage": "triage"},
    )
    graph.add_edge("triage", END)

    graph.add_edge("routing", "kb_search")
    graph.add_edge("kb_search", "path_decision")

    graph.add_conditional_edges(
        "path_decision",
        route_after_path_decision,
        {"resolution": "resolution", "acknowledgment": "acknowledgment"},
    )

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


def step_hdr(num: str, title: str) -> None:
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

async def run_email_to_quality_gate(
    *,
    message_id: str | None,
    skip_salesforce: bool,
    no_sqs_hop: bool,
) -> None:
    """Run the full email pipeline: Graph API -> S3 -> SQS -> Pipeline -> Quality Gate.

    Phase 1: Email intake (Steps E1-E2.9) using real services.
    Phase 2: SQS consume (real message hop, unless --no-sqs-hop).
    Phase 3: LangGraph AI pipeline (Steps 7-11, truncated at quality gate).
    """
    settings = get_settings()
    pipeline_start = time.time()

    banner("VQMS Full Email Pipeline: Email -> S3 -> SQS -> Quality Gate")
    result("Mailbox", settings.graph_api_mailbox, indent=2)
    result("S3 Bucket", settings.s3_bucket_data_store, indent=2)
    result("SQS Queue", settings.sqs_email_intake_queue_url or "(not configured)", indent=2)
    result("LLM Provider", settings.llm_provider, indent=2)
    result("SQS Hop", "SKIP (direct)" if no_sqs_hop else "REAL (enqueue + receive)", indent=2)
    result("Skip Salesforce", str(skip_salesforce), indent=2)
    print("\n    NOTE: Delivery (Step 12) is EXCLUDED from this run.")

    graph_api: GraphAPIConnector | None = None
    postgres: PostgresConnector | None = None

    try:
        # =================================================================
        # Step 0: Initialize ALL connectors
        # =================================================================
        step_hdr("0", "Initialize connectors")

        # PostgreSQL (SSH tunnel -> RDS)
        print("    Connecting to PostgreSQL via SSH tunnel...")
        postgres = PostgresConnector(settings)
        await postgres.connect()
        result("PostgreSQL", "[OK]")

        # AWS connectors (lightweight, no connection needed)
        s3 = S3Connector(settings)
        result("S3", f"[OK] (bucket: {settings.s3_bucket_data_store})")

        sqs = SQSConnector(settings)
        result("SQS", "[OK]")

        eventbridge = EventBridgeConnector(settings)
        result("EventBridge", "[OK]")

        # Graph API (lazy init — MSAL auth on first call)
        graph_api = GraphAPIConnector(settings)
        result("Graph API", f"[OK] (mailbox: {settings.graph_api_mailbox})")

        # Salesforce (or mock if skipped)
        if skip_salesforce:
            salesforce = AsyncMock()
            salesforce.identify_vendor.return_value = None
            salesforce.find_vendor_by_id.return_value = None
            result("Salesforce", "[SKIP] Using mock")
        else:
            salesforce = SalesforceConnector(settings)
            result("Salesforce", "[OK]")

        # LLM Gateway (Bedrock primary + OpenAI fallback)
        llm_gateway = LLMGateway(settings)
        result("LLM Gateway", f"[OK] (mode: {settings.llm_provider})")

        # Prompt Manager
        prompt_manager = PromptManager()
        result("Prompt Manager", "[OK]")

        # =================================================================
        # PHASE 1: Email Intake (Steps E1 - E2.9)
        # =================================================================
        banner("PHASE 1: Email Intake (Steps E1 - E2.9)")

        # --- E1: Fetch email from Graph API ---
        step_hdr("E1", "Fetch email from shared mailbox (Graph API)")

        if message_id:
            print(f"    Using provided message_id: {message_id[:60]}...")
            raw_email = await graph_api.fetch_email(message_id)
        else:
            print(f"    Listing unread emails from {settings.graph_api_mailbox}...")
            messages = await graph_api.list_unread_messages(top=5)

            if not messages:
                print("    [ERROR] No unread emails found in the mailbox!")
                print("    Send a test email to the mailbox and try again.")
                return

            first_msg = messages[0]
            message_id = first_msg["id"]
            sender = first_msg.get("from", {}).get("emailAddress", {})
            print(f"    Found {len(messages)} unread email(s). Using the first one:")
            result("From", f"{sender.get('name', 'N/A')} <{sender.get('address', 'N/A')}>")
            result("Subject", first_msg.get("subject", "(no subject)"))
            result("ID", f"{message_id[:60]}...")

            raw_email = await graph_api.fetch_email(message_id)

        # Display fetched email info
        from_field = raw_email.get("from", {}).get("emailAddress", {})
        sender_email = from_field.get("address", "unknown")
        sender_name = from_field.get("name", "")
        subject = raw_email.get("subject", "(no subject)")
        body_preview = raw_email.get("bodyPreview", "")[:150].replace("\n", " ")
        attachments_raw = raw_email.get("attachments", [])

        result("From", f"{sender_name} <{sender_email}>")
        result("Subject", subject)
        result("Body preview", body_preview + ("..." if len(body_preview) == 150 else ""))
        result("Attachments", str(len(attachments_raw)))

        # --- E2: Run the full 10-step email intake pipeline ---
        step_hdr("E2", "Email Intake Pipeline (idempotency -> parse -> S3 -> vendor -> DB -> SQS)")

        email_intake = EmailIntakeService(
            graph_api=graph_api,
            postgres=postgres,
            s3=s3,
            sqs=sqs,
            eventbridge=eventbridge,
            salesforce=salesforce,
            settings=settings,
        )

        intake_start = time.time()
        parsed_email = await email_intake.process_email(
            message_id,
            correlation_id=None,  # Let it generate one
        )
        intake_elapsed = time.time() - intake_start

        # Handle duplicate (already processed)
        if parsed_email is None:
            print("\n    [DUPLICATE] Email already processed (idempotency check).")
            print("    Building synthetic payload from raw email to continue demo...")

            correlation_id = IdGenerator.generate_correlation_id()
            query_id = IdGenerator.generate_query_id()
            execution_id = IdGenerator.generate_execution_id()

            # Simple HTML to text
            body_html = raw_email.get("body", {}).get("content", "")
            body_text = re.sub(r"<[^>]+>", " ", body_html)
            body_text = re.sub(r"\s+", " ", body_text).strip()

            sqs_payload = {
                "query_id": query_id,
                "correlation_id": correlation_id,
                "execution_id": execution_id,
                "source": "email",
                "vendor_id": None,
                "subject": subject,
                "body": body_text or body_preview,
                "priority": "MEDIUM",
                "received_at": TimeHelper.ist_now().isoformat(),
                "attachments": [],
                "thread_status": "NEW",
                "metadata": {
                    "message_id": message_id,
                    "sender_email": sender_email,
                    "sender_name": sender_name,
                },
            }
            result("Status", "[DUPLICATE] Using synthetic payload")
            result("Query ID", query_id)
            result("Correlation ID", correlation_id)

            # Skip SQS hop for duplicates — SQS message was already consumed
            no_sqs_hop = True
        else:
            print(f"\n    [OK] Email processed in {intake_elapsed:.1f}s")
            result("Query ID", parsed_email.query_id)
            result("Correlation ID", parsed_email.correlation_id)
            result("Sender", f"{parsed_email.sender_name} <{parsed_email.sender_email}>")
            result("Subject", parsed_email.subject)
            result("Thread Status", parsed_email.thread_status)
            result("Vendor ID", parsed_email.vendor_id or "None (unresolved)")
            result("Match Method", parsed_email.vendor_match_method or "N/A")
            result("Attachments", str(len(parsed_email.attachments)))
            result("S3 Raw Key", parsed_email.s3_raw_email_key or "None")

            if parsed_email.attachments:
                for att in parsed_email.attachments:
                    result(f"  {att.filename}", f"{att.extraction_status} ({att.size_bytes} bytes)")

            correlation_id = parsed_email.correlation_id
            query_id = parsed_email.query_id
            execution_id = IdGenerator.generate_execution_id()

            # This is what EmailIntakeService enqueued to SQS (Step E2.9b)
            sqs_payload = {
                "query_id": query_id,
                "correlation_id": correlation_id,
                "execution_id": execution_id,
                "source": "email",
                "vendor_id": parsed_email.vendor_id,
                "subject": parsed_email.subject,
                "body": parsed_email.body_text,
                "priority": "MEDIUM",
                "received_at": parsed_email.received_at.isoformat(),
                "attachments": [att.model_dump(mode="json") for att in parsed_email.attachments],
                "thread_status": parsed_email.thread_status,
                "metadata": {
                    "message_id": message_id,
                    "sender_email": parsed_email.sender_email,
                    "sender_name": parsed_email.sender_name,
                    "vendor_match_method": parsed_email.vendor_match_method,
                    "conversation_id": parsed_email.conversation_id,
                },
            }

        phase1_elapsed = time.time() - pipeline_start

        # =================================================================
        # PHASE 2: SQS Consume (Real message hop)
        # =================================================================
        banner("PHASE 2: SQS Consume")

        if no_sqs_hop:
            step_hdr("SQS", "Direct passthrough (--no-sqs-hop or duplicate)")
            print("    Skipping real SQS hop — using payload directly from intake.")
            result("Payload query_id", sqs_payload["query_id"])
            result("Payload source", sqs_payload["source"])
        else:
            step_hdr("SQS", "Receive message from vqms-email-intake-queue")
            queue_url = settings.sqs_email_intake_queue_url

            if not queue_url:
                print("    [WARN] SQS_EMAIL_INTAKE_QUEUE_URL not set in .env")
                print("    Falling back to direct passthrough (no SQS hop).")
            else:
                print(f"    Polling SQS queue: {queue_url}")
                print("    Waiting up to 10s for the message we just enqueued...")

                sqs_start = time.time()
                received_messages = await sqs.receive_messages(
                    queue_url,
                    max_messages=1,
                    wait_time_seconds=10,
                    correlation_id=correlation_id,
                )
                sqs_elapsed = time.time() - sqs_start

                if not received_messages:
                    print(f"    [WARN] No message received after {sqs_elapsed:.1f}s")
                    print("    Falling back to direct passthrough.")
                else:
                    sqs_msg = received_messages[0]
                    sqs_payload = sqs_msg["body"]
                    receipt_handle = sqs_msg["receipt_handle"]

                    result("SQS Message ID", sqs_msg["message_id"])
                    result("Payload query_id", sqs_payload.get("query_id", "?"))
                    result("Payload source", sqs_payload.get("source", "?"))
                    result("Receive time", f"{sqs_elapsed:.1f}s")

                    # Delete the message so it doesn't get reprocessed
                    await sqs.delete_message(
                        queue_url,
                        receipt_handle,
                        correlation_id=correlation_id,
                    )
                    result("SQS delete", "[OK] Message deleted after processing")

        # =================================================================
        # PHASE 3: LangGraph AI Pipeline (Steps 7-11, no delivery)
        # =================================================================
        banner("PHASE 3: AI Pipeline (Steps 7 -> 11, Quality Gate)")

        step_hdr("GRAPH", "Build truncated pipeline (quality_gate -> END)")

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

        # Build initial PipelineState from the SQS payload
        now = TimeHelper.ist_now().isoformat()
        initial_state: dict = {
            "query_id": sqs_payload.get("query_id", query_id),
            "correlation_id": sqs_payload.get("correlation_id", correlation_id),
            "execution_id": sqs_payload.get("execution_id", execution_id),
            "source": "email",
            "unified_payload": sqs_payload,
            "status": "RECEIVED",
            "created_at": now,
            "updated_at": now,
        }

        result("Query ID", initial_state["query_id"])
        result("Correlation ID", initial_state["correlation_id"])
        result("Body length", f"{len(sqs_payload.get('body', ''))} chars")
        result("Vendor ID", sqs_payload.get("vendor_id") or "None")

        # --- Run the pipeline ---
        step_hdr("7-11", "Running LangGraph (context -> analysis -> routing -> draft -> QG)")

        ai_start = time.time()

        try:
            pipeline_result = await compiled_graph.ainvoke(initial_state)
        except Exception as exc:
            print(f"\n    [ERROR] Pipeline failed: {exc}")
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
            result("Tokens in/out", f"{analysis.get('tokens_in', '?')} / {analysis.get('tokens_out', '?')}", indent=2)
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
            step_label = "10A" if draft_type == "RESOLUTION" else "10B"
            print(f"\n  --- Draft Response (Step {step_label}) ---")
            result("Draft type", draft_type, indent=2)
            result("Subject", draft.get("subject", "?"), indent=2)
            result("Confidence", str(draft.get("confidence", "?")), indent=2)
            result("Model", draft.get("model_id", "?"), indent=2)
            result("Tokens in/out", f"{draft.get('tokens_in', '?')} / {draft.get('tokens_out', '?')}", indent=2)
            result("Draft time", f"{draft.get('draft_duration_ms', '?')}ms", indent=2)

            sources = draft.get("sources", [])
            if sources:
                result("Sources", ", ".join(sources), indent=2)

            body = draft.get("body", "")
            if body:
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
        result("Phase 1 (email intake)", f"{phase1_elapsed:.1f}s", indent=2)
        result("Phase 3 (AI pipeline)", f"{ai_elapsed:.1f}s", indent=2)
        result("Total end-to-end", f"{total_elapsed:.1f}s", indent=2)

        # --- What Would Happen Next ---
        print(f"\n{SUBDIV}")
        print("  --- What Would Happen Next (Step 12 - EXCLUDED) ---")
        if processing_path == "A":
            print("    1. Delivery node creates ServiceNow ticket (INC-XXXXXXX)")
            print("    2. Replace 'PENDING' in draft with real ticket number")
            print("    3. Send RESOLUTION email to vendor via Graph API")
            print("    4. Status -> RESOLVED")
        elif processing_path == "B":
            print("    1. Delivery node creates ServiceNow ticket (INC-XXXXXXX)")
            print("    2. Replace 'PENDING' in draft with real ticket number")
            print("    3. Send ACKNOWLEDGMENT email to vendor via Graph API")
            print("    4. Status -> AWAITING_RESOLUTION (human team investigates)")
        elif processing_path == "C":
            print("    Workflow PAUSED for human review. No delivery.")
        print()

    except Exception:
        logger.exception("Email-to-quality-gate pipeline failed")
        print("\n    [FAIL] Pipeline failed -- check logs above for details")
        raise
    finally:
        if graph_api:
            await graph_api.close()
        if postgres:
            await postgres.disconnect()
        print("    Connectors closed.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI args and run the full email-to-quality-gate pipeline."""
    parser = argparse.ArgumentParser(
        description=(
            "VQMS: Full email pipeline — Graph API -> S3 -> SQS -> "
            "LangGraph (Steps 7-11) -> Quality Gate"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Process first unread email (full flow with SQS hop)\n"
            "  uv run python scripts/run_email_to_quality_gate.py\n\n"
            "  # Process a specific email by message_id\n"
            "  uv run python scripts/run_email_to_quality_gate.py "
            '--message-id "AAMkAGI2..."\n\n'
            "  # Skip SQS hop (email intake -> pipeline directly)\n"
            "  uv run python scripts/run_email_to_quality_gate.py --no-sqs-hop\n\n"
            "  # Skip Salesforce vendor lookup\n"
            "  uv run python scripts/run_email_to_quality_gate.py --skip-salesforce\n"
        ),
    )
    parser.add_argument(
        "--message-id",
        type=str,
        default=None,
        help="Specific email message_id to process. "
             "If omitted, uses the first unread email from the mailbox.",
    )
    parser.add_argument(
        "--skip-salesforce",
        action="store_true",
        help="Skip Salesforce vendor lookup (use mock).",
    )
    parser.add_argument(
        "--no-sqs-hop",
        action="store_true",
        help="Skip real SQS enqueue/receive — pass payload directly to pipeline. "
             "Use this if SQS queue URL is not configured.",
    )
    args = parser.parse_args()

    asyncio.run(
        run_email_to_quality_gate(
            message_id=args.message_id,
            skip_salesforce=args.skip_salesforce,
            no_sqs_hop=args.no_sqs_hop,
        )
    )


if __name__ == "__main__":
    main()
