# ruff: noqa: E402
"""Script: seed_triage_past_cases.py

Seed past resolved cases for the Path C triage reviewer copilot.

The Path C reviewer MCP server (src/mcp_servers/reviewer/tools.py) queries:
  - memory.episodic_memory          -> episodic_memory_for_vendor / get_similar_past_queries
  - workflow.triage_packages        -> confidence_breakdown_explainer
  - workflow.case_execution         -> joined for case context
  - ServiceNow incident table       -> view_servicenow_history

In a fresh / dev environment those tables are empty and the copilot has
no context to surface to a reviewer. This script writes a small but
realistic set of historical cases so reviewers can demo the workflow
end-to-end without having to run the full pipeline first.

What gets written for every past case (PAST_CASES below):
  1. workflow.case_execution     — central case row with the analysis_result JSON
  2. workflow.routing_decision   — team / SLA / priority assignment
  3. workflow.ticket_link        — local pointer to a ServiceNow incident number
                                   (we don't create the incident in ServiceNow itself —
                                    that requires office IAM access we don't always have)
  4. memory.episodic_memory      — closure summary + (optional) Titan v2 embedding
                                   so get_similar_past_queries can rank by similarity

Plus, for the single ACTIVE_TRIAGE_CASE:
  5. workflow.case_execution     — status PAUSED, processing_path C
  6. workflow.triage_packages    — full TriagePackage JSON so
                                   confidence_breakdown_explainer returns rich data

Usage:
    uv run python scripts/seed_triage_past_cases.py
    uv run python scripts/seed_triage_past_cases.py --clear            # wipe seed rows first
    uv run python scripts/seed_triage_past_cases.py --no-embeddings    # skip embedding calls
                                                                       # (faster / works offline)

Prerequisites:
  1. .env configured with PostgreSQL + SSH tunnel + Bedrock/OpenAI creds
  2. Migrations 004, 006, 011, 016 applied (case_execution, episodic_memory,
     triage_packages, episodic_memory.embedding column)
  3. pgvector extension enabled (migration 002)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap — must run before any project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from dotenv import load_dotenv

load_dotenv(override=True)

from config.settings import get_settings
from adapters.llm_gateway import LLMGateway
from db.connection import PostgresConnector
from utils.logger import LoggingSetup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LoggingSetup.configure()
logger = logging.getLogger("scripts.seed_triage_past_cases")

for _noisy in ("botocore", "urllib3", "msal", "httpx", "httpcore",
               "openai._base_client", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

DIVIDER = "=" * 72
SUBDIV = "-" * 60


def banner(text: str) -> None:
    """Print a section banner — keeps the script output scannable."""
    print(f"\n{DIVIDER}")
    print(f"  {text}")
    print(DIVIDER)


def line(label: str, value: str, indent: int = 4) -> None:
    """Print a key-value line with safe ASCII output (Windows console-friendly)."""
    safe_value = value.encode("ascii", errors="replace").decode("ascii")
    print(f"{' ' * indent}{label}: {safe_value}")


# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PastCase:
    """One past resolved vendor case.

    Lives in code (not a JSON file) because the small set is easier to
    review inline with the migration schemas it has to match. A row in
    PAST_CASES corresponds to one row in each of:
      workflow.case_execution, workflow.routing_decision,
      workflow.ticket_link, memory.episodic_memory.
    """

    query_id: str
    vendor_id: str
    intent: str
    processing_path: str           # "A" or "B"
    outcome: str                   # VENDOR_CONFIRMED / AUTO_CLOSED / RESOLVED
    summary: str
    subject: str
    body: str
    suggested_category: str
    confidence_score: float
    urgency_level: str             # LOW | MEDIUM | HIGH | CRITICAL
    sentiment: str
    extracted_entities: dict[str, Any]
    assigned_team: str
    priority: str                  # LOW | MEDIUM | HIGH | CRITICAL
    sla_hours: int
    ticket_id: str                 # ServiceNow incident number (local mirror)
    ticket_status: str             # New / In Progress / Resolved / Closed
    resolved_at: datetime
    source: str = "email"          # "email" | "portal"


# The first three cases mirror the notebook's mock EPISODIC_MEMORY_DB +
# SERVICENOW_TICKETS so the reviewer copilot returns the same data the
# demo notebook relies on. The rest fill out a more diverse history so
# get_similar_past_queries has enough variety to rank meaningfully.
PAST_CASES: tuple[PastCase, ...] = (
    PastCase(
        query_id="VQ-2026-0089",
        vendor_id="VEND-001",
        intent="invoice_status",
        processing_path="A",
        outcome="VENDOR_CONFIRMED",
        summary=(
            "invoice_status for VEND-001: AI-resolved — invoice INV-7741 "
            "payment date and reference shared from KB-008."
        ),
        subject="Invoice INV-7741 — payment status?",
        body=(
            "Hi team, can you confirm whether invoice INV-7741 has been paid? "
            "It was raised on March 22 against PO-2241. Thanks."
        ),
        suggested_category="invoicing",
        confidence_score=0.92,
        urgency_level="MEDIUM",
        sentiment="neutral",
        extracted_entities={
            "invoice_numbers": ["INV-7741"],
            "purchase_orders": ["PO-2241"],
            "amounts": [],
            "dates": ["2026-03-22"],
        },
        assigned_team="AP-FINANCE",
        priority="MEDIUM",
        sla_hours=24,
        ticket_id="INC-7723451",
        ticket_status="Closed",
        resolved_at=datetime(2026, 4, 10, 14, 30),
    ),
    PastCase(
        query_id="VQ-2026-0102",
        vendor_id="VEND-001",
        intent="po_amendment",
        processing_path="B",
        outcome="VENDOR_CONFIRMED",
        summary=(
            "po_amendment for VEND-001: team-resolved — PO-2299 quantity "
            "increase approved by procurement after re-approval."
        ),
        subject="PO-2299 — request to increase quantity by 200 units",
        body=(
            "Hello, we need to increase the order quantity on PO-2299 from "
            "800 to 1000 units. Can procurement re-approve? Original delivery "
            "date is May 12."
        ),
        suggested_category="procurement",
        confidence_score=0.88,
        urgency_level="HIGH",
        sentiment="neutral",
        extracted_entities={
            "purchase_orders": ["PO-2299"],
            "amounts": [],
            "dates": ["2026-05-12"],
            "quantities": [800, 1000],
        },
        assigned_team="PROCUREMENT",
        priority="HIGH",
        sla_hours=8,
        ticket_id="INC-7724102",
        ticket_status="Closed",
        resolved_at=datetime(2026, 4, 17, 11, 15),
    ),
    PastCase(
        query_id="VQ-2026-0118",
        vendor_id="VEND-001",
        intent="payment_terms_query",
        processing_path="A",
        outcome="VENDOR_CONFIRMED",
        summary=(
            "payment_terms_query for VEND-001: AI-resolved — explained "
            "NET-30 vs NET-45 with contract Section 4.2 citation."
        ),
        subject="Clarification on payment terms — NET-30 or NET-45?",
        body=(
            "We were under the impression our terms were NET-45 but recent "
            "remittance advice shows NET-30. Could you confirm which applies "
            "to our master agreement?"
        ),
        suggested_category="contract",
        confidence_score=0.90,
        urgency_level="LOW",
        sentiment="neutral",
        extracted_entities={
            "invoice_numbers": [],
            "purchase_orders": [],
            "amounts": [],
            "dates": [],
        },
        assigned_team="LEGAL-CONTRACTS",
        priority="LOW",
        sla_hours=48,
        ticket_id="INC-7724587",
        ticket_status="Closed",
        resolved_at=datetime(2026, 4, 20, 16, 45),
    ),
    PastCase(
        query_id="VQ-2026-0091",
        vendor_id="VEND-002",
        intent="delivery_delay",
        processing_path="B",
        outcome="VENDOR_CONFIRMED",
        summary=(
            "delivery_delay for VEND-002: team-resolved — shipment delayed "
            "two weeks, logistics coordinated revised ETA."
        ),
        subject="Shipment SHP-4421 delayed by 2 weeks — need new ETA",
        body=(
            "Hi, our shipment SHP-4421 against PO-2210 is delayed two weeks "
            "due to a port closure. Please advise on the revised delivery date "
            "and any penalty implications."
        ),
        suggested_category="logistics",
        confidence_score=0.86,
        urgency_level="HIGH",
        sentiment="concerned",
        extracted_entities={
            "purchase_orders": ["PO-2210"],
            "shipments": ["SHP-4421"],
        },
        assigned_team="LOGISTICS-OPS",
        priority="HIGH",
        sla_hours=8,
        ticket_id="INC-7724889",
        ticket_status="Closed",
        resolved_at=datetime(2026, 4, 11, 10, 5),
    ),
    PastCase(
        query_id="VQ-2026-0095",
        vendor_id="VEND-003",
        intent="refund_request",
        processing_path="A",
        outcome="VENDOR_CONFIRMED",
        summary=(
            "refund_request for VEND-003: AI-resolved — RMA process and "
            "15-day refund timeline cited from KB-001."
        ),
        subject="Defective batch — request RMA against PO-2188",
        body=(
            "We received 50 units against PO-2188 last week and 12 of them "
            "are defective. Please share the RMA process and expected refund "
            "timeline."
        ),
        suggested_category="return_refund",
        confidence_score=0.93,
        urgency_level="MEDIUM",
        sentiment="frustrated",
        extracted_entities={
            "purchase_orders": ["PO-2188"],
            "quantities": [50, 12],
        },
        assigned_team="AP-FINANCE",
        priority="MEDIUM",
        sla_hours=24,
        ticket_id="INC-7723998",
        ticket_status="Closed",
        resolved_at=datetime(2026, 4, 13, 9, 50),
    ),
    PastCase(
        query_id="VQ-2026-0107",
        vendor_id="VEND-002",
        intent="banking_detail_update",
        processing_path="B",
        outcome="VENDOR_CONFIRMED",
        summary=(
            "banking_detail_update for VEND-002: team-resolved — bank "
            "account change verified via dual-control process."
        ),
        subject="Update bank account on file for future remittances",
        body=(
            "Please update our remittance bank account from HDFC ****1234 "
            "to ICICI ****5678 effective May 1. We can share a cancelled "
            "cheque on request."
        ),
        suggested_category="payments",
        confidence_score=0.84,
        urgency_level="MEDIUM",
        sentiment="neutral",
        extracted_entities={
            "dates": ["2026-05-01"],
        },
        assigned_team="AP-FINANCE",
        priority="MEDIUM",
        sla_hours=24,
        ticket_id="INC-7724201",
        ticket_status="Closed",
        resolved_at=datetime(2026, 4, 18, 13, 25),
    ),
)


@dataclass(frozen=True)
class ActiveTriageCase:
    """The single in-flight Path C case the reviewer is currently looking at.

    Mirrors QUERY_ANALYSIS_DB['VQ-2026-0123'] from notebooks/mcp.ipynb so
    the reviewer copilot demo lines up with the notebook's narrative.
    Distinct from PastCase because it has no resolution data yet — the
    workflow is paused waiting for the human reviewer to act.
    """

    query_id: str = "VQ-2026-0123"
    vendor_id: str = "VEND-001"
    subject: str = "Question about our payment situation"
    body: str = (
        "Hi, regarding our recent dealings, can you help us figure out "
        "where things stand? It's getting confusing on our end. Need "
        "clarity ASAP."
    )
    suggested_category: str = "payments"
    confidence_score: float = 0.62
    suggested_team: str = "AP-FINANCE"
    suggested_priority: str = "MEDIUM"
    suggested_sla_hours: int = 24

    confidence_breakdown: dict[str, float] = field(default_factory=lambda: {
        "overall": 0.62,
        "intent_classification": 0.45,
        "entity_extraction": 0.40,
        "single_issue_detection": 0.55,
        "threshold": 0.85,
    })
    low_confidence_reasons: tuple[str, ...] = (
        "Query uses vague phrases like 'recent dealings' and 'where "
        "things stand' without specific entities (no invoice number, "
        "PO number, or amount).",
        "'It's getting confusing on our end' suggests multiple unrelated "
        "concerns may be bundled together.",
        "Sentiment is 'frustrated' which often indicates the vendor "
        "expects context the AI doesn't have.",
    )


ACTIVE_TRIAGE_CASE = ActiveTriageCase()


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------

class TriageSeeder:
    """Writes past cases + one active triage package to the database.

    Stays single-responsibility: each public method seeds one table. The
    public seed() method is the orchestrator. Embedding generation is
    optional so this script can run on machines without Bedrock or
    OpenAI credentials configured.
    """

    def __init__(
        self,
        postgres: PostgresConnector,
        llm_gateway: LLMGateway | None,
        *,
        embedding_dims: int,
    ) -> None:
        """Initialize with already-connected postgres + optional LLM gateway."""
        self._pg = postgres
        self._llm = llm_gateway
        self._embedding_dims = embedding_dims

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    async def seed(self) -> dict[str, int]:
        """Seed all tables. Returns a counter dict for the summary banner."""
        counters: dict[str, int] = {
            "case_execution": 0,
            "routing_decision": 0,
            "ticket_link": 0,
            "episodic_memory": 0,
            "triage_packages": 0,
        }

        banner("Seeding past cases")
        for case in PAST_CASES:
            inserted = await self._seed_one_past_case(case)
            for key, count in inserted.items():
                counters[key] += count

        banner("Seeding active Path C triage case")
        active_inserted = await self._seed_active_triage_case(ACTIVE_TRIAGE_CASE)
        for key, count in active_inserted.items():
            counters[key] += count

        return counters

    async def clear(self) -> None:
        """Delete prior seed rows so the next run is deterministic.

        Filters on the seed query_ids only — never wipes the whole table.
        """
        banner("Clearing prior seed rows")
        seed_query_ids = [c.query_id for c in PAST_CASES] + [ACTIVE_TRIAGE_CASE.query_id]
        seed_ticket_ids = [c.ticket_id for c in PAST_CASES]

        # Order matters when there are FKs, but none of these tables FK
        # each other today — still, clear children before parents to keep
        # the script forward-compatible if FKs are added later.
        await self._pg.execute(
            "DELETE FROM memory.episodic_memory WHERE query_id = ANY($1::text[])",
            seed_query_ids,
        )
        await self._pg.execute(
            "DELETE FROM workflow.ticket_link WHERE query_id = ANY($1::text[]) "
            "OR ticket_id = ANY($2::text[])",
            seed_query_ids, seed_ticket_ids,
        )
        await self._pg.execute(
            "DELETE FROM workflow.routing_decision WHERE query_id = ANY($1::text[])",
            seed_query_ids,
        )
        await self._pg.execute(
            "DELETE FROM workflow.triage_packages WHERE query_id = ANY($1::text[])",
            seed_query_ids,
        )
        await self._pg.execute(
            "DELETE FROM workflow.case_execution WHERE query_id = ANY($1::text[])",
            seed_query_ids,
        )
        line("Cleared", f"{len(seed_query_ids)} seed query_ids", indent=2)

    # ------------------------------------------------------------------
    # Per-case seeders
    # ------------------------------------------------------------------

    async def _seed_one_past_case(self, case: PastCase) -> dict[str, int]:
        """Insert all four rows that represent one resolved past case."""
        counts = {
            "case_execution": 0,
            "routing_decision": 0,
            "ticket_link": 0,
            "episodic_memory": 0,
            "triage_packages": 0,
        }
        correlation_id = str(uuid.uuid4())

        # ---- workflow.case_execution ----
        analysis_result = self._build_analysis_result(case)
        routing_decision_json = self._build_routing_decision_json(case)
        case_inserted = await self._insert_case_execution(
            query_id=case.query_id,
            correlation_id=correlation_id,
            source=case.source,
            status="CLOSED",
            processing_path=case.processing_path,
            vendor_id=case.vendor_id,
            analysis_result=analysis_result,
            routing_decision=routing_decision_json,
            created_at=case.resolved_at,
        )
        counts["case_execution"] += int(case_inserted)

        # ---- workflow.routing_decision ----
        routing_inserted = await self._insert_routing_decision(case)
        counts["routing_decision"] += int(routing_inserted)

        # ---- workflow.ticket_link ----
        ticket_inserted = await self._insert_ticket_link(case)
        counts["ticket_link"] += int(ticket_inserted)

        # ---- memory.episodic_memory (with optional embedding) ----
        memory_inserted = await self._insert_episodic_memory(case)
        counts["episodic_memory"] += int(memory_inserted)

        line(
            case.query_id,
            f"vendor={case.vendor_id} path={case.processing_path} "
            f"ticket={case.ticket_id} -> "
            f"case={'OK' if case_inserted else 'SKIP'}, "
            f"route={'OK' if routing_inserted else 'SKIP'}, "
            f"ticket={'OK' if ticket_inserted else 'SKIP'}, "
            f"memory={'OK' if memory_inserted else 'SKIP'}",
            indent=2,
        )
        return counts

    async def _seed_active_triage_case(
        self, case: ActiveTriageCase
    ) -> dict[str, int]:
        """Insert the live Path C case + its TriagePackage row."""
        counts = {
            "case_execution": 0,
            "routing_decision": 0,
            "ticket_link": 0,
            "episodic_memory": 0,
            "triage_packages": 0,
        }
        correlation_id = str(uuid.uuid4())
        callback_token = str(uuid.uuid4())
        now = datetime.utcnow()

        analysis_result = {
            "intent_classification": "ambiguous",
            "extracted_entities": {},
            "urgency_level": "MEDIUM",
            "sentiment": "frustrated",
            "confidence_score": case.confidence_score,
            "multi_issue_detected": True,
            "suggested_category": case.suggested_category,
            "low_confidence_reasons": list(case.low_confidence_reasons),
        }

        case_inserted = await self._insert_case_execution(
            query_id=case.query_id,
            correlation_id=correlation_id,
            source="email",
            status="PAUSED",
            processing_path="C",
            vendor_id=case.vendor_id,
            analysis_result=analysis_result,
            routing_decision=None,
            created_at=now,
        )
        counts["case_execution"] += int(case_inserted)

        # Build the TriagePackage payload exactly the way the triage
        # node would have written it — confidence_breakdown_explainer
        # reads these keys directly out of package_data.
        package_data = {
            "query_id": case.query_id,
            "vendor_id": case.vendor_id,
            "original_query": {
                "subject": case.subject,
                "body": case.body,
                "source": "email",
            },
            "analysis_result": analysis_result,
            "confidence_breakdown": case.confidence_breakdown,
            "suggested_routing": {
                "assigned_team": case.suggested_team,
                "priority": case.suggested_priority,
                "sla_hours": case.suggested_sla_hours,
                "category": case.suggested_category,
                "routing_reason": (
                    "Suggested team based on suggested_category=payments. "
                    "Reviewer should confirm or override after clarifying intent."
                ),
            },
            "suggested_draft": {
                "type": "ACKNOWLEDGMENT",
                "subject": f"Re: {case.subject}",
                "body": (
                    "Hi,\n\nThanks for reaching out — we have received your "
                    "message and our team is reviewing the details. We will "
                    "share a substantive update within one business day.\n\n"
                    "If you can share a specific invoice number, PO number, "
                    "or remittance reference in the meantime, that will help "
                    "us track this down faster.\n\nBest regards,\nVendor Support"
                ),
            },
        }

        triage_inserted = await self._insert_triage_package(
            query_id=case.query_id,
            correlation_id=correlation_id,
            callback_token=callback_token,
            package_data=package_data,
            original_confidence=case.confidence_score,
            suggested_category=case.suggested_category,
            created_at=now,
        )
        counts["triage_packages"] += int(triage_inserted)

        line(
            case.query_id,
            f"vendor={case.vendor_id} path=C status=PAUSED -> "
            f"case={'OK' if case_inserted else 'SKIP'}, "
            f"triage={'OK' if triage_inserted else 'SKIP'}",
            indent=2,
        )
        return counts

    # ------------------------------------------------------------------
    # Row builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_analysis_result(case: PastCase) -> dict[str, Any]:
        """Build the AnalysisResult JSONB the way query_analysis writes it."""
        return {
            "intent_classification": case.intent,
            "extracted_entities": case.extracted_entities,
            "urgency_level": case.urgency_level,
            "sentiment": case.sentiment,
            "confidence_score": case.confidence_score,
            "multi_issue_detected": False,
            "suggested_category": case.suggested_category,
        }

    @staticmethod
    def _build_routing_decision_json(case: PastCase) -> dict[str, Any]:
        """Build the RoutingDecision JSONB stored on case_execution.

        Same shape as models.ticket.RoutingDecision so the workflow read
        path keeps working unchanged.
        """
        return {
            "assigned_team": case.assigned_team,
            "category": case.suggested_category,
            "priority": case.priority,
            "sla_target": {
                "total_hours": case.sla_hours,
                "warning_at_percent": 70,
                "l1_escalation_at_percent": 85,
                "l2_escalation_at_percent": 95,
            },
            "routing_reason": (
                f"Routed to {case.assigned_team} based on category "
                f"'{case.suggested_category}' and priority {case.priority}."
            ),
            "requires_human_investigation": case.processing_path == "B",
        }

    # ------------------------------------------------------------------
    # Per-table insert helpers
    # ------------------------------------------------------------------

    async def _insert_case_execution(
        self,
        *,
        query_id: str,
        correlation_id: str,
        source: str,
        status: str,
        processing_path: str,
        vendor_id: str,
        analysis_result: dict[str, Any],
        routing_decision: dict[str, Any] | None,
        created_at: datetime,
    ) -> bool:
        """Insert a workflow.case_execution row, skipping on conflict."""
        result = await self._pg.execute(
            """
            INSERT INTO workflow.case_execution (
                query_id, correlation_id, execution_id, source, status,
                processing_path, vendor_id, analysis_result, routing_decision,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $10)
            ON CONFLICT (query_id) DO NOTHING
            """,
            query_id,
            correlation_id,
            str(uuid.uuid4()),  # execution_id is per-run, not per-query
            source,
            status,
            processing_path,
            vendor_id,
            json.dumps(analysis_result),
            json.dumps(routing_decision) if routing_decision else None,
            created_at,
        )
        # asyncpg returns "INSERT 0 1" on insert, "INSERT 0 0" on conflict
        return result.endswith("1")

    async def _insert_routing_decision(self, case: PastCase) -> bool:
        """Insert workflow.routing_decision (no UNIQUE — guard manually)."""
        existing = await self._pg.fetchrow(
            "SELECT id FROM workflow.routing_decision WHERE query_id = $1",
            case.query_id,
        )
        if existing:
            return False

        await self._pg.execute(
            """
            INSERT INTO workflow.routing_decision (
                query_id, assigned_team, category, priority, sla_hours,
                routing_reason, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            case.query_id,
            case.assigned_team,
            case.suggested_category,
            case.priority,
            case.sla_hours,
            f"Auto-routed to {case.assigned_team} based on past case seed.",
            case.resolved_at,
        )
        return True

    async def _insert_ticket_link(self, case: PastCase) -> bool:
        """Insert the local ServiceNow ticket pointer row."""
        existing = await self._pg.fetchrow(
            "SELECT id FROM workflow.ticket_link "
            "WHERE query_id = $1 AND ticket_id = $2",
            case.query_id, case.ticket_id,
        )
        if existing:
            return False

        await self._pg.execute(
            """
            INSERT INTO workflow.ticket_link (
                query_id, ticket_id, servicenow_sys_id, status, created_at
            )
            VALUES ($1, $2, $3, $4, $5)
            """,
            case.query_id,
            case.ticket_id,
            f"SEED-{case.ticket_id.lower()}",  # mirrors a sys_id placeholder
            case.ticket_status,
            case.resolved_at,
        )
        return True

    async def _insert_episodic_memory(self, case: PastCase) -> bool:
        """Insert memory.episodic_memory row, embedding the summary if possible."""
        existing = await self._pg.fetchrow(
            "SELECT id FROM memory.episodic_memory WHERE query_id = $1",
            case.query_id,
        )
        if existing:
            return False

        memory_id = f"MEM-{uuid.uuid4()}"
        embedding_str = await self._embed_text(
            f"{case.subject}\n\n{case.body}\n\n{case.summary}",
            label=case.query_id,
        )

        if embedding_str is None:
            await self._pg.execute(
                """
                INSERT INTO memory.episodic_memory (
                    memory_id, vendor_id, query_id, intent,
                    resolution_path, outcome, resolved_at, summary, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                memory_id,
                case.vendor_id,
                case.query_id,
                case.intent,
                case.processing_path,
                case.outcome,
                case.resolved_at,
                case.summary,
                case.resolved_at,
            )
        else:
            await self._pg.execute(
                """
                INSERT INTO memory.episodic_memory (
                    memory_id, vendor_id, query_id, intent,
                    resolution_path, outcome, resolved_at, summary,
                    embedding, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, $10)
                """,
                memory_id,
                case.vendor_id,
                case.query_id,
                case.intent,
                case.processing_path,
                case.outcome,
                case.resolved_at,
                case.summary,
                embedding_str,
                case.resolved_at,
            )
        return True

    async def _insert_triage_package(
        self,
        *,
        query_id: str,
        correlation_id: str,
        callback_token: str,
        package_data: dict[str, Any],
        original_confidence: float,
        suggested_category: str,
        created_at: datetime,
    ) -> bool:
        """Insert workflow.triage_packages row, skipping on conflict."""
        result = await self._pg.execute(
            """
            INSERT INTO workflow.triage_packages (
                query_id, correlation_id, callback_token, package_data,
                status, original_confidence, suggested_category, created_at
            )
            VALUES ($1, $2, $3, $4::jsonb, 'PENDING', $5, $6, $7)
            ON CONFLICT (query_id) DO NOTHING
            """,
            query_id,
            correlation_id,
            callback_token,
            json.dumps(package_data),
            original_confidence,
            suggested_category,
            created_at,
        )
        return result.endswith("1")

    # ------------------------------------------------------------------
    # Embedding helper
    # ------------------------------------------------------------------

    async def _embed_text(self, text: str, *, label: str) -> str | None:
        """Embed text via the LLM gateway. Returns pgvector-formatted string.

        Returns None if no gateway is configured (the --no-embeddings flag
        was passed) or if the embed call fails. The caller falls back to
        inserting the row without an embedding — rows without embeddings
        are skipped by the partial HNSW index, so this degrades cleanly.
        """
        if self._llm is None:
            return None

        try:
            start = time.perf_counter()
            embedding = await self._llm.llm_embed(
                text=text,
                correlation_id=f"seed-triage-{label}",
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
        except Exception as exc:
            logger.warning("Embedding failed for %s: %s", label, exc)
            return None

        if len(embedding) != self._embedding_dims:
            logger.warning(
                "Embedding dim mismatch for %s: got %d, expected %d",
                label, len(embedding), self._embedding_dims,
            )
            return None

        line(
            f"  embedded {label}",
            f"{len(embedding)} dims in {elapsed_ms}ms",
            indent=4,
        )
        return "[" + ",".join(str(v) for v in embedding) + "]"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run(*, clear: bool, no_embeddings: bool) -> None:
    """Connect to PostgreSQL + LLM gateway, then run the seeder."""
    settings = get_settings()
    postgres: PostgresConnector | None = None

    try:
        banner("VQMS Triage Past-Case Seeder")
        line("Embedding provider", settings.embedding_provider, indent=2)
        line("Embedding dims", str(settings.bedrock_embedding_dimensions), indent=2)
        line("Past cases to seed", str(len(PAST_CASES)), indent=2)
        line("Active triage cases", "1", indent=2)
        line("Embeddings", "DISABLED" if no_embeddings else "ENABLED", indent=2)

        # Connectors
        print(f"\n{SUBDIV}")
        print("  Initializing connectors...")
        print(SUBDIV)
        postgres = PostgresConnector(settings)
        await postgres.connect()
        line("PostgreSQL", "[OK]")

        llm_gateway: LLMGateway | None = None
        if not no_embeddings:
            llm_gateway = LLMGateway(settings)
            line("LLM Gateway", f"[OK] (mode: {settings.embedding_provider})")
        else:
            line("LLM Gateway", "[SKIP] (--no-embeddings)")

        seeder = TriageSeeder(
            postgres,
            llm_gateway,
            embedding_dims=settings.bedrock_embedding_dimensions,
        )

        if clear:
            await seeder.clear()

        counters = await seeder.seed()

        # Summary
        banner("SEED COMPLETE")
        for table, count in counters.items():
            line(table, f"{count} row(s) inserted", indent=2)

        # Verify by reading back row counts the reviewer copilot will see
        case_count = await postgres.fetchrow(
            "SELECT COUNT(*) AS cnt FROM workflow.case_execution"
        )
        memory_count = await postgres.fetchrow(
            "SELECT COUNT(*) AS cnt FROM memory.episodic_memory"
        )
        triage_count = await postgres.fetchrow(
            "SELECT COUNT(*) AS cnt FROM workflow.triage_packages"
        )
        ticket_count = await postgres.fetchrow(
            "SELECT COUNT(*) AS cnt FROM workflow.ticket_link"
        )
        print()
        line(
            "case_execution rows",
            str(case_count["cnt"] if case_count else 0),
            indent=2,
        )
        line(
            "episodic_memory rows",
            str(memory_count["cnt"] if memory_count else 0),
            indent=2,
        )
        line(
            "triage_packages rows",
            str(triage_count["cnt"] if triage_count else 0),
            indent=2,
        )
        line(
            "ticket_link rows",
            str(ticket_count["cnt"] if ticket_count else 0),
            indent=2,
        )
    except Exception:
        logger.exception("Triage seed failed")
        print("\n    [FAIL] Seed failed -- check logs above for details")
        raise
    finally:
        if postgres:
            await postgres.disconnect()
        print("\n    Connectors closed.\n")


def main() -> None:
    """Parse CLI flags and dispatch the async seeder."""
    parser = argparse.ArgumentParser(
        description=(
            "VQMS: Seed past resolved cases (memory.episodic_memory + "
            "workflow.case_execution + workflow.ticket_link) plus one "
            "active Path C triage package for the reviewer copilot demo."
        ),
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete prior seed rows (matched by query_id) before inserting.",
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help=(
            "Skip the embedding step. Rows are still inserted but without "
            "an embedding column, so get_similar_past_queries skips them."
        ),
    )
    args = parser.parse_args()

    asyncio.run(run(clear=args.clear, no_embeddings=args.no_embeddings))


if __name__ == "__main__":
    main()
