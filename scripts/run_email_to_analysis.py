# ruff: noqa: E402
"""Script: run_email_to_analysis.py

VQMS End-to-End Email Pipeline: Fetch Email -> Query Analysis Agent.

This script runs the COMPLETE email pipeline in a single process:

  Step E1:    Fetch email from shared mailbox (MS Graph API)
  Step E2.1:  Idempotency check (PostgreSQL cache)
  Step E2.2:  Parse email fields
  Step E2.3:  Store raw email in S3
  Step E2.4:  Process attachments (S3 + text extraction)
  Step E2.5:  Vendor resolution (Salesforce 3-step fallback)
  Step E2.6:  Thread correlation (NEW / EXISTING_OPEN / REPLY_TO_CLOSED)
  Step E2.7:  Generate tracking IDs (query_id, execution_id, correlation_id)
  Step E2.8:  Store metadata in PostgreSQL (email_messages + case_execution)
  Step E2.9a: Publish EmailParsed event (EventBridge)
  Step 7:     Context loading (vendor profile, episodic memory)
  Step 8:     Query Analysis Agent (LLM call -> intent, entities, confidence)
  Step 8.5:   Confidence check (>= 0.85 -> pass, < 0.85 -> Path C)
  Step 9A:    Routing (deterministic rules -> team, SLA)
  Step 9B:    KB Search (embed -> pgvector cosine similarity)
  Step 9.5:   Path decision (KB match >= 80% -> Path A, else -> Path B)

The script runs the LangGraph pipeline DIRECTLY (no SQS hop),
so you can see the full flow from email fetch to path decision
in a single terminal.

Usage:
    uv run python scripts/run_email_to_analysis.py
    uv run python scripts/run_email_to_analysis.py --message-id "AAMkAGI2..."
    uv run python scripts/run_email_to_analysis.py --skip-salesforce

Prerequisites:
    1. .env configured with Graph API, AWS, PostgreSQL, Bedrock credentials
    2. Pipeline is NOT required to be running separately
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
from events.eventbridge import EventBridgeConnector
from adapters.graph_api import GraphAPIConnector
from adapters.llm_gateway import LLMGateway
from db.connection import PostgresConnector
from storage.s3_client import S3Connector
from adapters.salesforce import SalesforceConnector
from queues.sqs import SQSConnector
from services.email_intake import EmailIntakeService
from orchestration.dependencies import create_pipeline
from utils.helpers import IdGenerator, TimeHelper
from utils.logger import LoggingSetup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LoggingSetup.configure()
logger = logging.getLogger("scripts.run_email_to_analysis")

# Silence noisy third-party loggers
for _noisy in ("botocore", "urllib3", "msal", "httpx", "httpcore",
               "openai._base_client", "pdfminer", "pdfplumber"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


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
    # Replace non-ASCII chars that Windows cp1252 console can't display
    safe_value = value.encode("ascii", errors="replace").decode("ascii")
    safe_label = label.encode("ascii", errors="replace").decode("ascii")
    print(f"{' ' * indent}{safe_label}: {safe_value}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_full_email_pipeline(
    *,
    message_id: str | None,
    skip_salesforce: bool,
) -> None:
    """Run the entire email-to-analysis pipeline in a single process.

    Fetches an email from the shared mailbox, runs the full intake
    pipeline (Steps E1-E2), then feeds the result directly into
    the LangGraph AI pipeline (Steps 7-9) without an SQS hop.
    """
    settings = get_settings()
    pipeline_start = time.time()

    banner("VQMS Email -> Query Analysis Pipeline")
    result("Mailbox", settings.graph_api_mailbox, indent=2)
    result("AWS Region", settings.aws_region, indent=2)
    result("LLM Provider", settings.llm_provider, indent=2)

    # =====================================================================
    # Step 0: Initialize all connectors
    # =====================================================================
    step("0", "Initialize connectors")

    graph_api: GraphAPIConnector | None = None
    postgres: PostgresConnector | None = None

    try:
        # --- PostgreSQL (SSH tunnel -> RDS) ---
        print("    Connecting to PostgreSQL via SSH tunnel...")
        postgres = PostgresConnector(settings)
        await postgres.connect()
        result("PostgreSQL", "[OK]")

        # --- AWS connectors (lightweight, no connection needed) ---
        s3 = S3Connector(settings)
        result("S3", "[OK]")

        sqs = SQSConnector(settings)
        result("SQS", "[OK]")

        eventbridge = EventBridgeConnector(settings)
        result("EventBridge", "[OK]")

        # --- Graph API (lazy init — MSAL auth on first call) ---
        graph_api = GraphAPIConnector(settings)
        result("Graph API", f"[OK] (mailbox: {settings.graph_api_mailbox})")

        # --- Salesforce (or mock if skipped) ---
        if skip_salesforce:
            salesforce = AsyncMock()
            salesforce.identify_vendor.return_value = None
            salesforce.find_vendor_by_id.return_value = None
            result("Salesforce", "[SKIP] Using mock (vendor will be None)")
        else:
            salesforce = SalesforceConnector(settings)
            result("Salesforce", "[OK]")

        # --- LLM Gateway (Bedrock primary + OpenAI fallback) ---
        llm_gateway = LLMGateway(settings)
        result("LLM Gateway", f"[OK] (mode: {settings.llm_provider})")

        # =====================================================================
        # Step E1: Fetch email from shared mailbox via Graph API
        # =====================================================================
        step("E1", "Fetch email from shared mailbox (Graph API)")

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

            # Fetch full email with attachments
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

        # =====================================================================
        # Step E2: Run Email Intake Service (Steps E2.1 - E2.9)
        # =====================================================================
        step("E2", "Email Intake Pipeline (idempotency -> parse -> S3 -> vendor -> DB -> SQS)")

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

        if parsed_email is None:
            print("\n    [DUPLICATE] Email already processed (idempotency check).")
            print("    To re-process, send a new email or use a different message_id.")

            # For testing convenience, let's build a synthetic payload
            # so we can still run the AI pipeline
            print("\n    Building synthetic payload from raw email to continue...")
            correlation_id = IdGenerator.generate_correlation_id()
            query_id = IdGenerator.generate_query_id()
            execution_id = IdGenerator.generate_execution_id()

            # Extract body text from raw email
            body_obj = raw_email.get("body", {})
            body_html = body_obj.get("content", "")
            # Simple HTML to text
            import re
            body_text = re.sub(r"<[^>]+>", " ", body_html)
            body_text = re.sub(r"\s+", " ", body_text).strip()

            unified_payload = {
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
        else:
            print(f"\n    [OK] Email processed successfully in {intake_elapsed:.1f}s")
            result("Query ID", parsed_email.query_id)
            result("Correlation ID", parsed_email.correlation_id)
            result("Sender", f"{parsed_email.sender_name} <{parsed_email.sender_email}>")
            result("Subject", parsed_email.subject)
            result("Thread Status", parsed_email.thread_status)
            result("Vendor ID", parsed_email.vendor_id or "None (unresolved)")
            result("Match Method", parsed_email.vendor_match_method or "N/A")
            result("Attachments", str(len(parsed_email.attachments)))
            result("S3 Raw Key", parsed_email.s3_raw_email_key or "None")
            result("Intake Time", f"{intake_elapsed:.1f}s")

            if parsed_email.attachments:
                for att in parsed_email.attachments:
                    result(f"  {att.filename}", f"{att.extraction_status} ({att.size_bytes} bytes)")

            # Build unified payload from parsed email
            correlation_id = parsed_email.correlation_id
            query_id = parsed_email.query_id
            execution_id = IdGenerator.generate_execution_id()

            unified_payload = {
                "query_id": query_id,
                "correlation_id": correlation_id,
                "execution_id": execution_id,
                "source": "email",
                "vendor_id": parsed_email.vendor_id,
                "subject": parsed_email.subject,
                "body": parsed_email.body_text,
                "priority": "MEDIUM",
                "received_at": parsed_email.received_at.isoformat(),
                "attachments": [att.model_dump() for att in parsed_email.attachments],
                "thread_status": parsed_email.thread_status,
                "metadata": {
                    "message_id": message_id,
                    "sender_email": parsed_email.sender_email,
                    "sender_name": parsed_email.sender_name,
                    "vendor_match_method": parsed_email.vendor_match_method,
                    "conversation_id": parsed_email.conversation_id,
                },
            }

        email_intake_elapsed = time.time() - pipeline_start

        # =====================================================================
        # Steps 7-9: Run LangGraph AI Pipeline DIRECTLY (no SQS hop)
        # =====================================================================
        banner(f"Email Intake Complete - {email_intake_elapsed:.1f}s")
        print("    Now running AI pipeline (Steps 7 -> 8 -> 8.5 -> 9A -> 9B -> Path Decision)...")

        step("7-9", "LangGraph AI Pipeline (context -> analysis -> routing -> path)")

        # Build the compiled graph via dependency injection
        compiled_graph, _consumer = create_pipeline(
            settings=settings,
            postgres=postgres,
            llm_gateway=llm_gateway,
            salesforce=salesforce,
            sqs=sqs,
        )

        # Build the initial PipelineState
        now = TimeHelper.ist_now().isoformat()
        initial_state = {
            "query_id": query_id,
            "correlation_id": correlation_id,
            "execution_id": execution_id,
            "source": "email",
            "unified_payload": unified_payload,
            "status": "RECEIVED",
            "created_at": now,
            "updated_at": now,
        }

        result("Query ID", query_id)
        result("Correlation ID", correlation_id)
        result("Body length", f"{len(unified_payload.get('body', ''))} chars")
        result("Vendor ID", unified_payload.get("vendor_id") or "None")

        ai_start = time.time()

        try:
            pipeline_result = await compiled_graph.ainvoke(initial_state)
        except Exception as e:
            print(f"\n    [ERROR] Pipeline failed: {e}")
            logger.exception("Pipeline execution failed")
            return

        ai_elapsed = time.time() - ai_start
        total_elapsed = time.time() - pipeline_start

        # =====================================================================
        # Display Results
        # =====================================================================
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
        routing = pipeline_result.get("routing_decision")
        if routing:
            print("\n  --- Routing (Step 9A) ---")
            result("Team", routing.get("assigned_team", "?"), indent=2)
            sla = routing.get("sla_target", {})
            result("SLA", f"{sla.get('sla_hours', '?')}h", indent=2)
            result("SLA deadline", sla.get("deadline_at", "?"), indent=2)
            result("Priority", routing.get("priority", "?"), indent=2)
        else:
            if processing_path != "C":
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
                        f"{m.get('title', '?')} (score={m.get('similarity_score', 0):.3f})",
                        indent=2,
                    )
        else:
            if processing_path != "C":
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

        # --- Pipeline Status ---
        print("\n  --- Pipeline Status ---")
        result("Final status", pipeline_result.get("status", "?"), indent=2)

        error = pipeline_result.get("error")
        if error:
            result("Error", error, indent=2)

        # --- Timing Summary ---
        print(f"\n{SUBDIV}")
        print("  --- Timing ---")
        result("Email intake", f"{email_intake_elapsed:.1f}s", indent=2)
        result("AI pipeline", f"{ai_elapsed:.1f}s", indent=2)
        result("Total", f"{total_elapsed:.1f}s", indent=2)
        print()

    except Exception:
        logger.exception("Email-to-analysis pipeline failed")
        print("\n    [FAIL] Pipeline failed -- check logs above for details")
        raise
    finally:
        # Cleanup
        if graph_api:
            await graph_api.close()
        if postgres:
            await postgres.disconnect()
        print("    Connectors closed.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI args and run the full email-to-analysis pipeline."""
    parser = argparse.ArgumentParser(
        description="VQMS: Fetch email -> run full AI pipeline (Steps E1-E2, 7-9)",
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
        help="Skip Salesforce vendor lookup (use if SF credentials are not available).",
    )
    args = parser.parse_args()

    asyncio.run(
        run_full_email_pipeline(
            message_id=args.message_id,
            skip_salesforce=args.skip_salesforce,
        )
    )


if __name__ == "__main__":
    main()
