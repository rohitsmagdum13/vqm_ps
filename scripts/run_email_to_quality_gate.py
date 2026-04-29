# ruff: noqa: E402
"""Script: run_email_to_quality_gate.py

VQMS FULL Pipeline — Phase 1 (Intake) -> Phase 6 (Closure & Memory).

This script runs the COMPLETE end-to-end pipeline in a single process,
including a real SQS hop between intake and the AI pipeline, ServiceNow
ticket creation, email delivery, and all Phase 6 background services:

  Phase 1 — Email Intake (Steps E1 - E2.9):
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

  Phase 3 — AI Pipeline (Steps 7 - 11):
    Step 7:   Context Loading (vendor profile, episodic memory)
    Step 8:   Query Analysis Agent (LLM Call #1 -> intent, entities, confidence)
    Step 8.5: Confidence Check (>= 0.85 -> pass, < 0.85 -> Path C)
    Step 9A:  Routing (deterministic rules -> team, SLA + sla_checkpoints row)
    Step 9B:  KB Search (embed -> pgvector cosine similarity)
    Step 9.5: Path Decision (KB match >= 80% -> Path A, else -> Path B)
    Step 10:  Resolution draft (Path A) or Acknowledgment draft (Path B)
    Step 11:  Quality Gate (7 deterministic checks on draft email)

  Phase 4 — Delivery (Step 12):
    Step 12:  Create ServiceNow ticket, swap PENDING -> INC number,
              send email via Graph API, update final status.
              On Path A success, register with ClosureService so the
              auto-close timer starts.

  Phase 6 — Background services (Steps 13, 16):
    Step 13:  SlaMonitor.tick() — scan workflow.sla_checkpoints once,
              publish any threshold events that have not yet fired.
    Step 16:  Show workflow.closure_tracking row written by delivery,
              run AutoCloseScheduler.tick() once (no-op unless the
              auto-close deadline has already passed).
              Optional: simulate ClosureService.close_case() to
              demonstrate episodic memory write-back.

Usage:
    uv run python scripts/run_email_to_quality_gate.py
    uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..."
    uv run python scripts/run_email_to_quality_gate.py --skip-salesforce
    uv run python scripts/run_email_to_quality_gate.py --no-sqs-hop
    uv run python scripts/run_email_to_quality_gate.py --skip-delivery
    uv run python scripts/run_email_to_quality_gate.py --no-email-send
    uv run python scripts/run_email_to_quality_gate.py --skip-phase6
    uv run python scripts/run_email_to_quality_gate.py --simulate-close

Prerequisites:
    1. .env configured with Graph API, AWS, PostgreSQL, Bedrock/OpenAI,
       ServiceNow credentials.
    2. SQS queue (vqms-email-intake-queue) must exist (pre-provisioned).
    3. S3 bucket (vqms-data-store) must exist (pre-provisioned).
    4. KB articles seeded: uv run python scripts/seed_knowledge_base.py --clear
    5. Migration 012 applied so workflow.sla_checkpoints,
       workflow.closure_tracking, and memory.episodic_memory exist.
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
from adapters.servicenow import ServiceNowConnector
from db.connection import PostgresConnector
from orchestration.graph import build_pipeline_graph
from orchestration.nodes.acknowledgment import AcknowledgmentNode
from orchestration.nodes.confidence_check import ConfidenceCheckNode
from orchestration.nodes.context_loading import ContextLoadingNode
from orchestration.nodes.delivery import DeliveryNode
from orchestration.nodes.kb_search import KBSearchNode
from orchestration.nodes.path_decision import PathDecisionNode
from orchestration.nodes.quality_gate import QualityGateNode
from orchestration.nodes.query_analysis import QueryAnalysisNode
from orchestration.nodes.resolution import ResolutionNode
from orchestration.nodes.resolution_from_notes import ResolutionFromNotesNode
from orchestration.nodes.routing import RoutingNode
from orchestration.nodes.triage import TriageNode
from orchestration.prompts.prompt_manager import PromptManager
from queues.sqs import SQSConnector
from services.auto_close_scheduler import AutoCloseScheduler
from services.closure import ClosureService
from services.email_intake import EmailIntakeService
from services.episodic_memory import EpisodicMemoryWriter
from services.sla_monitor import SlaMonitor
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

async def run_full_pipeline(
    *,
    message_id: str | None,
    skip_salesforce: bool,
    no_sqs_hop: bool,
    skip_delivery: bool,
    skip_phase6: bool,
    simulate_close: bool,
    no_email_send: bool,
) -> None:
    """Run the full Phase 1 -> Phase 6 pipeline end to end.

    Phase 1: Email intake (Steps E1-E2.9) using real services.
    Phase 2: SQS consume (real message hop, unless --no-sqs-hop).
    Phase 3: LangGraph AI pipeline (Steps 7-11).
    Phase 4: Delivery (Step 12) -- ServiceNow ticket + Graph email.
    Phase 6: SLA monitor tick, closure tracking, auto-close tick,
             optional simulate-close -> episodic memory write.
    """
    settings = get_settings()
    pipeline_start = time.time()

    banner("VQMS Full Pipeline: Email -> Pipeline -> Delivery -> Phase 6")
    result("Mailbox", settings.graph_api_mailbox, indent=2)
    result("S3 Bucket", settings.s3_bucket_data_store, indent=2)
    result("SQS Queue", settings.sqs_email_intake_queue_url or "(not configured)", indent=2)
    result("LLM Provider", settings.llm_provider, indent=2)
    result("SQS Hop", "SKIP (direct)" if no_sqs_hop else "REAL (enqueue + receive)", indent=2)
    result("Skip Salesforce", str(skip_salesforce), indent=2)
    result("Skip Delivery", str(skip_delivery), indent=2)
    result("No Email Send", str(no_email_send), indent=2)
    result("Skip Phase 6", str(skip_phase6), indent=2)
    result("Simulate close_case", str(simulate_close), indent=2)

    graph_api: GraphAPIConnector | None = None
    postgres: PostgresConnector | None = None
    servicenow: ServiceNowConnector | None = None

    try:
        # =================================================================
        # Step 0: Initialize ALL connectors + Phase 6 services
        # =================================================================
        step_hdr("0", "Initialize connectors and Phase 6 services")

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

        # ServiceNow (lazy httpx client)
        servicenow = ServiceNowConnector(settings)
        result("ServiceNow", "[OK] (lazy)")

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

        # ---- Phase 6 services (all wired, whether or not we use them) ----
        episodic_memory_writer = EpisodicMemoryWriter(
            postgres=postgres, settings=settings, llm_gateway=llm_gateway,
        )
        result("EpisodicMemoryWriter", "[OK]")

        closure_service = ClosureService(
            postgres=postgres,
            servicenow=servicenow,
            eventbridge=eventbridge,
            sqs=sqs,
            episodic_memory_writer=episodic_memory_writer,
            settings=settings,
        )
        result("ClosureService", "[OK]")

        sla_monitor = SlaMonitor(
            postgres=postgres,
            eventbridge=eventbridge,
            settings=settings,
        )
        result("SlaMonitor", f"[OK] (interval={settings.sla_monitor_interval_seconds}s)")

        auto_close_scheduler = AutoCloseScheduler(
            postgres=postgres,
            closure_service=closure_service,
            settings=settings,
        )
        result(
            "AutoCloseScheduler",
            f"[OK] (interval={settings.auto_close_interval_seconds}s, "
            f"business_days={settings.auto_close_business_days})",
        )

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

        # Pull CC + extra-To off the raw email so the script's two
        # reconstructed-payload paths (duplicate fallback and SQS-skip
        # fallback) carry them through to the pipeline. The real
        # production path puts these on the SQS message via
        # EmailIntakeService; the script's reconstructions need to do
        # the same or CC silently disappears.
        own_mailbox_lc = (settings.graph_api_mailbox or "").lower()
        raw_cc_emails = [
            (ea.get("emailAddress", {}) or {}).get("address", "")
            for ea in raw_email.get("ccRecipients", []) or []
        ]
        raw_to_emails = [
            (ea.get("emailAddress", {}) or {}).get("address", "")
            for ea in raw_email.get("toRecipients", []) or []
        ]
        cc_emails_from_raw = [
            e for e in raw_cc_emails
            if e and e.lower() != own_mailbox_lc
        ]
        extra_to_emails_from_raw = [
            e for e in raw_to_emails
            if e and e.lower() != own_mailbox_lc
        ]

        result("From", f"{sender_name} <{sender_email}>")
        result("Subject", subject)
        result("Body preview", body_preview + ("..." if len(body_preview) == 150 else ""))
        result("Attachments", str(len(attachments_raw)))
        result(
            "CC on original",
            ", ".join(cc_emails_from_raw) if cc_emails_from_raw else "(none)",
        )
        result(
            "Extra To (besides mailbox)",
            ", ".join(extra_to_emails_from_raw)
            if extra_to_emails_from_raw else "(none)",
        )

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
                    "cc_emails": cc_emails_from_raw,
                    "extra_to_emails": extra_to_emails_from_raw,
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
                    result(
                        f"  {att.filename}",
                        f"{att.extraction_status} ({att.size_bytes} bytes)",
                    )

            correlation_id = parsed_email.correlation_id
            query_id = parsed_email.query_id
            execution_id = IdGenerator.generate_execution_id()

            # This is what EmailIntakeService enqueued to SQS (Step E2.9b).
            # Include cc_emails / extra_to_emails so this reconstructed
            # payload (used when --no-sqs-hop is set or the SQS receive
            # times out) matches what the real EmailIntakeService puts on
            # the queue. Without these, CC silently disappears.
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
                    "cc_emails": cc_emails_from_raw,
                    "extra_to_emails": extra_to_emails_from_raw,
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
        # PHASE 3 + PHASE 4: LangGraph AI Pipeline (Steps 7 - 12)
        # =================================================================
        banner("PHASE 3 + 4: AI Pipeline (Steps 7 -> 11) + Delivery (Step 12)")

        step_hdr("GRAPH", "Build full pipeline graph (entry -> ... -> delivery -> END)")

        context_loading = ContextLoadingNode(
            postgres=postgres, salesforce=salesforce, settings=settings,
        )
        query_analysis = QueryAnalysisNode(
            bedrock=llm_gateway, prompt_manager=prompt_manager, settings=settings,
        )
        confidence_check = ConfidenceCheckNode(settings=settings)
        triage = TriageNode(
            postgres=postgres, eventbridge=eventbridge, settings=settings,
        )
        routing = RoutingNode(settings=settings, postgres=postgres)
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

        # Delivery is the Phase 4 node. If --skip-delivery, we stub it out
        # with an AsyncMock so the graph still compiles but does nothing at
        # the delivery step — useful when ServiceNow/Graph send should not
        # fire (e.g. running against production mailboxes during testing).
        if skip_delivery:
            delivery_stub = AsyncMock()

            async def _stub_execute(state):
                """Placeholder delivery that prints but never sends."""
                print(
                    "\n    [SKIP-DELIVERY] Step 12 stubbed — no ticket, "
                    "no email send."
                )
                return {
                    "ticket_info": None,
                    "status": "DELIVERY_SKIPPED",
                    "updated_at": TimeHelper.ist_now().isoformat(),
                }

            delivery_stub.execute = _stub_execute
            delivery_node = delivery_stub
            result("Delivery", "[STUB] --skip-delivery enabled")
        else:
            # --no-email-send keeps real ServiceNow ticket creation but
            # swaps graph_api.send_email with a no-op so nothing actually
            # lands in a vendor mailbox. This is the "keep ServiceNow,
            # don't bother the vendor" mode for dev testing.
            delivery_graph_api = graph_api
            if no_email_send:
                real_send = graph_api.send_email

                async def _noop_send_email(
                    *, to, subject, body_html, cc=None, bcc=None,
                    reply_to_message_id=None, correlation_id=None,
                    **_kwargs,
                ):
                    """Stubbed send_email -- logs the intent but does not send."""
                    cc_repr = ", ".join(cc) if cc else "(none)"
                    print(
                        f"    [NO-EMAIL-SEND] Would send to {to} "
                        f"cc=[{cc_repr}] (subject: {subject[:60]!r})"
                    )
                    # Return the same dict shape the real send_email returns
                    return {
                        "sent": True,
                        "stubbed": True,
                        "to": to,
                        "cc": list(cc) if cc else [],
                        "subject": subject,
                    }

                # Swap on the instance so DeliveryNode sees the stub.
                # real_send stays referenced so ruff does not complain.
                graph_api.send_email = _noop_send_email  # type: ignore[method-assign]
                _ = real_send  # keep a reference; not called
                result(
                    "Graph API send_email",
                    "[STUB] --no-email-send on; ticket will still be created",
                )

            delivery_node = DeliveryNode(
                servicenow=servicenow,
                graph_api=delivery_graph_api,
                settings=settings,
                eventbridge=eventbridge,
                closure_service=closure_service,
            )
            result("Delivery", "[OK] (ServiceNow + Graph API + ClosureService wired)")

        # Resolution-from-notes node (Step 15, only used on webhook re-entry)
        resolution_from_notes = ResolutionFromNotesNode(
            llm_gateway=llm_gateway,
            prompt_manager=prompt_manager,
            servicenow=servicenow,
            settings=settings,
        )

        compiled_graph = build_pipeline_graph(
            context_loading_node=context_loading,
            query_analysis_node=query_analysis,
            confidence_check_node=confidence_check,
            triage_node=triage,
            routing_node=routing,
            kb_search_node=kb_search,
            path_decision_node=path_decision,
            resolution_node=resolution,
            acknowledgment_node=acknowledgment,
            quality_gate_node=quality_gate,
            delivery_node=delivery_node,
            resolution_from_notes_node=resolution_from_notes,
        )
        result("Graph", "[OK] full pipeline compiled (Steps 7 -> 12)")

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
        # Surface CC / extra-To right before pipeline entry so we can see
        # whether the metadata that DeliveryNode needs is actually present.
        _meta = sqs_payload.get("metadata") or {}
        result(
            "Payload metadata.cc_emails",
            ", ".join(_meta.get("cc_emails") or []) or "(none)",
        )
        result(
            "Payload metadata.extra_to_emails",
            ", ".join(_meta.get("extra_to_emails") or []) or "(none)",
        )

        # --- Run the pipeline ---
        step_hdr("7-12", "Running LangGraph (context -> analysis -> routing -> draft -> QG -> delivery)")

        ai_start = time.time()

        try:
            pipeline_result = await compiled_graph.ainvoke(initial_state)
        except Exception as exc:
            print(f"\n    [ERROR] Pipeline failed: {exc}")
            logger.exception("Pipeline execution failed")
            return

        ai_elapsed = time.time() - ai_start

        # =================================================================
        # Display Phase 3 Results (Steps 7 - 11)
        # =================================================================
        banner("PIPELINE RESULTS (Steps 7 - 11)")

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
            result(
                "Tokens in/out",
                f"{analysis.get('tokens_in', '?')} / {analysis.get('tokens_out', '?')}",
                indent=2,
            )
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
            result(
                "Tokens in/out",
                f"{draft.get('tokens_in', '?')} / {draft.get('tokens_out', '?')}",
                indent=2,
            )
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

        # =================================================================
        # Phase 4 Delivery Results (Step 12)
        # =================================================================
        banner("DELIVERY RESULTS (Step 12)")

        ticket_info = pipeline_result.get("ticket_info")
        final_status = pipeline_result.get("status", "?")

        if skip_delivery:
            print("  [SKIP-DELIVERY] Delivery was stubbed out via CLI flag.")
            print("  No ServiceNow ticket created, no email sent.")
        elif ticket_info:
            print("  --- ServiceNow Ticket ---")
            result("Ticket Number", ticket_info.get("ticket_number")
                   or ticket_info.get("ticket_id", "?"), indent=2)
            result("Query ID", ticket_info.get("query_id", "?"), indent=2)
            result("Status", ticket_info.get("status", "?"), indent=2)
            result("Assigned Team", ticket_info.get("assigned_team", "?"), indent=2)
            result("SLA Deadline", str(ticket_info.get("sla_deadline", "?")), indent=2)
            result("Created At", str(ticket_info.get("created_at", "?")), indent=2)

            print("\n  --- Email Send ---")
            # Pull the recipient stash off the persisted draft snapshot —
            # DeliveryNode writes _recipient_email there. Empty value
            # means the pipeline ran but couldn't find an address, in
            # which case Path B silently skipped the send.
            draft_snapshot = pipeline_result.get("draft_response") or {}
            recipient_used = draft_snapshot.get("_recipient_email", "")
            cc_used = draft_snapshot.get("_cc_emails") or []
            result(
                "CC list passed to send",
                ", ".join(cc_used) if cc_used else "(none — vendor only)",
                indent=2,
            )

            if final_status == "DELIVERY_FAILED":
                result("Send Status", "[FAILED] " + str(pipeline_result.get("error", "")), indent=2)
            elif processing_path == "A":
                # Path A halts at PENDING_APPROVAL — Delivery does NOT
                # send; an admin sends later from /admin/draft-approvals.
                result(
                    "Email Type",
                    "RESOLUTION (full answer -> vendor)",
                    indent=2,
                )
                result("Send Status", "[HELD for admin approval]", indent=2)
                result("Recipient (when approved)", recipient_used or "(unresolved)", indent=2)
                result(
                    "Final Status",
                    "PENDING_APPROVAL (admin reviews in /admin/draft-approvals)",
                    indent=2,
                )
            elif processing_path == "B":
                result(
                    "Email Type",
                    "ACKNOWLEDGMENT (no answer -- team investigating)",
                    indent=2,
                )
                # Path B auto-sends — distinguish actually-sent from the
                # silent-skip case so the user knows whether the vendor
                # got the email or not.
                if recipient_used:
                    result("Send Status", "[SENT via Graph API]", indent=2)
                    result("Recipient", recipient_used, indent=2)
                else:
                    result(
                        "Send Status",
                        "[SKIPPED] No recipient -- ticket created, no email sent",
                        indent=2,
                    )
                    result(
                        "Hint",
                        "Vendor profile has no primary_contact_email AND "
                        "payload had no sender_email -- check Salesforce "
                        "or the email's From header",
                        indent=2,
                    )
                result(
                    "Final Status",
                    "AWAITING_RESOLUTION (Path B -- human team investigates)",
                    indent=2,
                )
            else:
                result("Email Type", "(unknown)", indent=2)
                result("Final Status", final_status, indent=2)
        else:
            print(f"  [NO TICKET] final_status={final_status}")
            if pipeline_result.get("error"):
                result("Error", str(pipeline_result["error"]), indent=2)

        # =================================================================
        # PHASE 6: SLA Monitor + Closure Tracking + Auto-Close
        # =================================================================
        phase6_elapsed = 0.0
        if skip_phase6:
            banner("PHASE 6: SKIPPED (--skip-phase6)")
        else:
            banner("PHASE 6: SLA Monitor + Closure Tracking + Auto-Close")
            phase6_start = time.time()

            # ---- Read the sla_checkpoints row the Routing node wrote ----
            step_hdr("13.0", "Check workflow.sla_checkpoints row (from Routing node)")
            try:
                checkpoint_row = await postgres.fetchrow(
                    """
                    SELECT query_id, sla_started_at, sla_deadline,
                           warning_fired, l1_fired, l2_fired,
                           last_status, last_checked_at
                    FROM workflow.sla_checkpoints
                    WHERE query_id = $1
                    """,
                    query_id,
                )
            except Exception as exc:
                checkpoint_row = None
                result("Checkpoint read", f"[ERROR] {exc}", indent=2)

            if checkpoint_row:
                result("Query ID", checkpoint_row.get("query_id", "?"), indent=2)
                result("Started At", str(checkpoint_row.get("sla_started_at", "?")), indent=2)
                result("Deadline", str(checkpoint_row.get("sla_deadline", "?")), indent=2)
                result("Warning Fired", str(checkpoint_row.get("warning_fired", "?")), indent=2)
                result("L1 Fired", str(checkpoint_row.get("l1_fired", "?")), indent=2)
                result("L2 Fired", str(checkpoint_row.get("l2_fired", "?")), indent=2)
                result("Last Status", checkpoint_row.get("last_status", "?"), indent=2)
            else:
                print("    [INFO] No sla_checkpoints row found for this query.")
                print("    (Path C or non-critical INSERT failure -- not an error)")

            # ---- SlaMonitor.tick() once ----
            step_hdr("13.1", "Run SlaMonitor.tick() once")
            try:
                tick_correlation_id = IdGenerator.generate_correlation_id()
                events_published = await sla_monitor.tick(
                    correlation_id=tick_correlation_id,
                )
                result(
                    "Events published this tick",
                    str(events_published),
                    indent=2,
                )
                print(
                    "    (Fresh cases have far-away deadlines, so a single "
                    "tick usually publishes 0 events.)"
                )
            except Exception as exc:
                result("SlaMonitor.tick", f"[ERROR] {exc}", indent=2)
                logger.exception("SlaMonitor tick failed")

            # ---- Read workflow.closure_tracking row (if delivery ran) ----
            step_hdr("16.1", "Check workflow.closure_tracking (from delivery hook)")
            try:
                closure_row = await postgres.fetchrow(
                    """
                    SELECT query_id, resolution_sent_at, auto_close_deadline,
                           closed_at, closed_reason,
                           vendor_confirmation_detected_at
                    FROM workflow.closure_tracking
                    WHERE query_id = $1
                    """,
                    query_id,
                )
            except Exception as exc:
                closure_row = None
                result("Closure read", f"[ERROR] {exc}", indent=2)

            if closure_row:
                result("Query ID", closure_row.get("query_id", "?"), indent=2)
                result(
                    "Resolution Sent At",
                    str(closure_row.get("resolution_sent_at", "?")),
                    indent=2,
                )
                result(
                    "Auto-Close Deadline",
                    str(closure_row.get("auto_close_deadline", "?")),
                    indent=2,
                )
                result("Closed At", str(closure_row.get("closed_at") or "(open)"), indent=2)
                result("Closed Reason", closure_row.get("closed_reason") or "(open)", indent=2)
            else:
                print("    [INFO] No closure_tracking row found.")
                print(
                    "    (Expected if Path B first-send, Path C, or "
                    "--skip-delivery was used.)"
                )

            # ---- AutoCloseScheduler.tick() once ----
            step_hdr("16.2", "Run AutoCloseScheduler.tick() once")
            try:
                auto_close_cid = IdGenerator.generate_correlation_id()
                closed_this_tick = await auto_close_scheduler.tick(
                    correlation_id=auto_close_cid,
                )
                result("Cases closed this tick", str(closed_this_tick), indent=2)
                print(
                    f"    (Deadline is {settings.auto_close_business_days} "
                    "business days out so a fresh case won't close yet.)"
                )
            except Exception as exc:
                result("AutoCloseScheduler.tick", f"[ERROR] {exc}", indent=2)
                logger.exception("AutoCloseScheduler tick failed")

            # ---- Optional: simulate ClosureService.close_case ----
            step_hdr("16.3", "Simulate close_case (optional)")
            if simulate_close and closure_row and closure_row.get("closed_at") is None:
                print(
                    "    --simulate-close flag ON and closure row is open --"
                    " calling close_case(VENDOR_CONFIRMED)..."
                )
                try:
                    await closure_service.close_case(
                        query_id=query_id,
                        reason="VENDOR_CONFIRMED",
                        correlation_id=correlation_id,
                    )
                    result("close_case", "[OK] simulated", indent=2)

                    # Show the episodic_memory row that was just written
                    mem_row = await postgres.fetchrow(
                        """
                        SELECT memory_id, vendor_id, query_id, intent,
                               resolution_path, outcome, resolved_at, summary
                        FROM memory.episodic_memory
                        WHERE query_id = $1
                        ORDER BY resolved_at DESC
                        LIMIT 1
                        """,
                        query_id,
                    )
                    if mem_row:
                        print("\n    --- memory.episodic_memory (just written) ---")
                        result("Memory ID", mem_row.get("memory_id", "?"), indent=4)
                        result("Vendor ID", mem_row.get("vendor_id", "?"), indent=4)
                        result("Intent", mem_row.get("intent", "?"), indent=4)
                        result("Path", mem_row.get("resolution_path", "?"), indent=4)
                        result("Outcome", mem_row.get("outcome", "?"), indent=4)
                        result(
                            "Resolved At",
                            str(mem_row.get("resolved_at", "?")),
                            indent=4,
                        )
                        summary_txt = mem_row.get("summary") or ""
                        if summary_txt:
                            print(f"        Summary: {summary_txt}")
                    else:
                        print("    [INFO] No episodic_memory row written (non-critical failure).")
                except Exception as exc:
                    result("close_case", f"[ERROR] {exc}", indent=2)
                    logger.exception("close_case simulation failed")
            elif simulate_close:
                print("    --simulate-close set but no open closure row -- skipping.")
            else:
                print(
                    "    Skipped. Pass --simulate-close to demonstrate "
                    "close_case + episodic_memory write-back."
                )

            phase6_elapsed = time.time() - phase6_start

        # =================================================================
        # Final Status + Timing Summary
        # =================================================================
        banner("FINAL STATUS")
        total_elapsed = time.time() - pipeline_start

        print("  --- Pipeline Status ---")
        result("Final status", pipeline_result.get("status", "?"), indent=2)
        result("Processing path", processing_path or "?", indent=2)
        error = pipeline_result.get("error")
        if error:
            result("Error", str(error), indent=2)

        print(f"\n{SUBDIV}")
        print("  --- Timing ---")
        result("Phase 1 (email intake)", f"{phase1_elapsed:.1f}s", indent=2)
        result("Phase 2+3+4 (SQS + AI + delivery)", f"{ai_elapsed:.1f}s", indent=2)
        if not skip_phase6:
            result("Phase 6 (SLA + closure + auto-close)", f"{phase6_elapsed:.1f}s", indent=2)
        result("Total end-to-end", f"{total_elapsed:.1f}s", indent=2)

        # --- What's still downstream (outside this script's scope) ---
        print(f"\n{SUBDIV}")
        print("  --- What continues downstream (out of scope for this script) ---")
        print("    * SlaMonitor / AutoCloseScheduler normally run forever via lifespan")
        print("    * On a real Path B case: ServiceNow webhook -> re-enqueue")
        print("      with resume_context.action='prepare_resolution' -> graph")
        print("      entry-switch routes to resolution_from_notes -> quality_gate")
        print("      -> delivery (resolution_mode) -> status AWAITING_VENDOR_CONFIRMATION")
        print("    * Vendor confirmation reply triggers ClosureService.detect_confirmation")
        print("      -> close_case(VENDOR_CONFIRMED) -> episodic memory row saved")
        print()

    except Exception:
        logger.exception("Full pipeline failed")
        print("\n    [FAIL] Pipeline failed -- check logs above for details")
        raise
    finally:
        if graph_api:
            await graph_api.close()
        if servicenow:
            try:
                await servicenow.close()
            except Exception:
                pass
        if postgres:
            await postgres.disconnect()
        print("    Connectors closed.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI args and run the full Phase 1 -> Phase 6 pipeline."""
    parser = argparse.ArgumentParser(
        description=(
            "VQMS: FULL pipeline — Graph API -> S3 -> SQS -> "
            "LangGraph (Steps 7-12) -> Phase 6 (SLA + Closure + Memory)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Full flow on first unread email (SQS hop + real delivery + Phase 6)\n"
            "  uv run python scripts/run_email_to_quality_gate.py\n\n"
            "  # Process a specific email by message_id\n"
            "  uv run python scripts/run_email_to_quality_gate.py "
            '--message-id "AAMkAGI2..."\n\n'
            "  # Stop before delivery (no ServiceNow ticket, no email send)\n"
            "  uv run python scripts/run_email_to_quality_gate.py "
            "--skip-delivery --skip-phase6\n\n"
            "  # Keep ServiceNow (real ticket) but do NOT email the vendor\n"
            "  uv run python scripts/run_email_to_quality_gate.py --no-email-send\n\n"
            "  # Skip SQS hop (email intake -> pipeline directly)\n"
            "  uv run python scripts/run_email_to_quality_gate.py --no-sqs-hop\n\n"
            "  # Skip Salesforce vendor lookup\n"
            "  uv run python scripts/run_email_to_quality_gate.py --skip-salesforce\n\n"
            "  # Run the full pipeline AND simulate vendor confirmation\n"
            "  uv run python scripts/run_email_to_quality_gate.py --simulate-close\n"
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
        help="Skip real SQS enqueue/receive -- pass payload directly to pipeline. "
             "Use this if SQS queue URL is not configured.",
    )
    parser.add_argument(
        "--skip-delivery",
        action="store_true",
        help="Stub out Step 12 (Delivery) -- no ServiceNow ticket is created "
             "and no email is sent. Useful for testing the pipeline without "
             "touching ServiceNow or the mailbox.",
    )
    parser.add_argument(
        "--no-email-send",
        action="store_true",
        help="Keep real ServiceNow ticket creation but stub out the "
             "Graph API email send. Use this when you want a real INC number "
             "and the closure_tracking row, but do NOT want to actually "
             "email the vendor from the shared mailbox.",
    )
    parser.add_argument(
        "--skip-phase6",
        action="store_true",
        help="Skip the Phase 6 demonstration section (SLA Monitor tick, "
             "closure tracking inspection, AutoCloseScheduler tick, "
             "optional close_case simulation).",
    )
    parser.add_argument(
        "--simulate-close",
        action="store_true",
        help="After delivery, call ClosureService.close_case with reason "
             "VENDOR_CONFIRMED to demonstrate the closure path and the "
             "episodic_memory write-back.",
    )
    args = parser.parse_args()

    asyncio.run(
        run_full_pipeline(
            message_id=args.message_id,
            skip_salesforce=args.skip_salesforce,
            no_sqs_hop=args.no_sqs_hop,
            skip_delivery=args.skip_delivery,
            skip_phase6=args.skip_phase6,
            simulate_close=args.simulate_close,
            no_email_send=args.no_email_send,
        )
    )


if __name__ == "__main__":
    main()
