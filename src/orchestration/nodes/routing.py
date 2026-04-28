"""Module: orchestration/nodes/routing.py

Routing Node — Step 9A in the VQMS pipeline.

Deterministic rules engine that assigns a team, sets SLA targets,
and determines priority based on vendor tier and query urgency.
NO LLM calls — this is pure business logic.

Corresponds to Step 9A in the VQMS Architecture Document.
"""

from __future__ import annotations

import structlog

from config.settings import Settings
from models.workflow import PipelineState
from models.ticket import RoutingDecision, SLATarget
from utils.helpers import TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Assignment groups (the 6 family / 13 sub-team taxonomy)
#
# These names are the source of truth for what gets written into
# RoutingDecision.assigned_team and ServiceNow's assignment_group.
# The LLM is asked to emit the same names in `suggested_category`
# (see prompts/query_analysis_v1.j2). When the LLM disagrees with
# the deterministic rules below, the rules win — the LLM output is
# only a hint, not a source of truth.
# ---------------------------------------------------------------------------
DEFAULT_TEAM = "Vendor Support"

# Primary routing — intent_classification alone determines the group.
# These intents are unambiguous and don't need vendor_category to route.
PRIMARY_INTENT_TEAMS: dict[str, str] = {
    "INVOICE_PAYMENT": "Vendor Finance – AP & Invoicing",
    "COMPLIANCE_AUDIT": "Vendor Compliance & Audit",
    "GENERAL_INQUIRY": "Vendor Support",
}

# Secondary routing — vendor_category + eligible intent types map to a
# specific sub-team. Each row: (normalized vendor_category, eligible intents,
# group name).
SECONDARY_ROUTING: list[tuple[str, frozenset[str], str]] = [
    # IT & Digital Services
    ("it services", frozenset({"TECHNICAL_SUPPORT", "SLA_BREACH_REPORT", "DELIVERY_SHIPMENT", "CONTRACT_QUERY"}), "Vendor IT Services"),
    ("telecom", frozenset({"TECHNICAL_SUPPORT", "SLA_BREACH_REPORT", "DELIVERY_SHIPMENT", "CONTRACT_QUERY"}), "Vendor Telecom Services"),
    ("security", frozenset({"TECHNICAL_SUPPORT", "SLA_BREACH_REPORT", "DELIVERY_SHIPMENT", "CONTRACT_QUERY"}), "Vendor Security Services"),
    # Procurement & Supply Chain
    ("raw materials", frozenset({"PURCHASE_ORDER", "CONTRACT_QUERY", "CATALOG_PRICING", "RETURN_REFUND"}), "Vendor Procurement – Raw Materials"),
    ("manufacturing", frozenset({"PURCHASE_ORDER", "CONTRACT_QUERY", "CATALOG_PRICING", "RETURN_REFUND"}), "Vendor Procurement – Manufacturing"),
    ("office supplies", frozenset({"PURCHASE_ORDER", "CONTRACT_QUERY", "CATALOG_PRICING", "RETURN_REFUND"}), "Vendor Procurement – Office Supplies"),
    # Facilities & Logistics
    ("facilities", frozenset({"DELIVERY_SHIPMENT", "QUALITY_ISSUE", "SLA_BREACH_REPORT"}), "Vendor Facilities Management"),
    ("logistics", frozenset({"DELIVERY_SHIPMENT", "QUALITY_ISSUE", "SLA_BREACH_REPORT"}), "Vendor Logistics Management"),
    # Professional & Consulting
    ("professional services", frozenset({"CONTRACT_QUERY", "SLA_BREACH_REPORT", "QUALITY_ISSUE", "ONBOARDING"}), "Vendor Professional Services"),
    ("consulting", frozenset({"CONTRACT_QUERY", "SLA_BREACH_REPORT", "QUALITY_ISSUE", "ONBOARDING"}), "Vendor Consulting Services"),
]

# Set of all valid assignment-group names — used to validate LLM output
# against the canonical taxonomy. Anything not in this set falls back
# to the deterministic resolver below.
VALID_ASSIGNMENT_GROUPS: frozenset[str] = frozenset(
    [DEFAULT_TEAM]
    + list(PRIMARY_INTENT_TEAMS.values())
    + [group for _, _, group in SECONDARY_ROUTING]
)


def resolve_assignment_group(
    intent_classification: str | None,
    vendor_category: str | None,
) -> str:
    """Apply primary → secondary → fallback routing to pick a group.

    The LLM is asked to do the same reasoning in the prompt, but this
    function is the deterministic source of truth so a hallucinated
    `suggested_category` cannot send a query to a non-existent team.
    Default is "Vendor Support" when nothing matches.
    """
    intent = (intent_classification or "").upper().strip()
    category = (vendor_category or "").lower().strip()

    # Primary: intent alone resolves the group.
    if intent in PRIMARY_INTENT_TEAMS:
        return PRIMARY_INTENT_TEAMS[intent]

    # Secondary: vendor category + eligible intent.
    for cat_key, eligible_intents, group_name in SECONDARY_ROUTING:
        if category == cat_key and intent in eligible_intents:
            return group_name

    # Fallback.
    return DEFAULT_TEAM

# Base SLA hours by vendor tier
TIER_SLA_HOURS: dict[str, int] = {
    "PLATINUM": 4,
    "GOLD": 8,
    "SILVER": 16,
    "BRONZE": 24,
}

# Urgency multiplier applied to tier SLA hours
URGENCY_MULTIPLIER: dict[str, float] = {
    "CRITICAL": 0.25,
    "HIGH": 0.5,
    "MEDIUM": 1.0,
    "LOW": 1.5,
}


class RoutingNode:
    """Deterministic routing rules engine.

    Assigns team, sets SLA target, and determines priority
    based on query category, vendor tier, and urgency level.
    """

    def __init__(self, settings: Settings, postgres=None) -> None:
        """Initialize with SLA configuration from settings.

        Args:
            settings: Application settings with SLA thresholds.
            postgres: Optional PostgresConnector. When provided, the
                SLA checkpoint row is inserted here so the SlaMonitor
                can pick it up. Optional to keep unit tests that only
                exercise routing logic independent of the DB layer.
        """
        self._settings = settings
        self._postgres = postgres

    async def execute(self, state: PipelineState) -> PipelineState:
        """Apply routing rules and produce a RoutingDecision.

        Args:
            state: Current pipeline state with analysis_result and vendor_context.

        Returns:
            Updated state with routing_decision and status=ROUTING.
        """
        correlation_id = state.get("correlation_id", "")
        analysis_result = state.get("analysis_result", {})
        vendor_context = state.get("vendor_context") or {}

        # Extract fields for routing rules
        intent_classification = analysis_result.get("intent_classification", "")
        suggested_category = analysis_result.get("suggested_category", "")
        urgency_level = analysis_result.get("urgency_level", "MEDIUM")

        # Get vendor tier + category (defaults: BRONZE / unknown)
        vendor_profile = vendor_context.get("vendor_profile", {})
        tier_data = vendor_profile.get("tier", {})
        vendor_tier = tier_data.get("tier_name", "BRONZE")
        vendor_category = vendor_profile.get("vendor_category")

        # Rule 1: Team assignment
        # Trust the LLM's suggested_category ONLY when it's one of the
        # canonical assignment-group names. Otherwise fall back to the
        # deterministic resolver, which guarantees a valid group name
        # (default: "Vendor Support") regardless of LLM output.
        if suggested_category in VALID_ASSIGNMENT_GROUPS:
            assigned_team = suggested_category
        else:
            assigned_team = resolve_assignment_group(
                intent_classification, vendor_category
            )

        # Rule 2: SLA calculation
        tier_hours = TIER_SLA_HOURS.get(vendor_tier, self._settings.sla_default_hours)
        multiplier = URGENCY_MULTIPLIER.get(urgency_level, 1.0)
        total_hours = max(1, int(tier_hours * multiplier))

        sla_target = SLATarget(
            total_hours=total_hours,
            warning_at_percent=self._settings.sla_warning_threshold_percent,
            l1_escalation_at_percent=self._settings.sla_l1_escalation_threshold_percent,
            l2_escalation_at_percent=self._settings.sla_l2_escalation_threshold_percent,
        )

        # Build routing reason for audit trail
        routing_reason = (
            f"Intent '{intent_classification}' + "
            f"vendor_category '{vendor_category or 'unknown'}' → "
            f"team '{assigned_team}'. "
            f"Tier '{vendor_tier}' + urgency '{urgency_level}' → "
            f"SLA {total_hours}h."
        )

        routing_decision = RoutingDecision(
            assigned_team=assigned_team,
            sla_target=sla_target,
            category=suggested_category or intent_classification or "unknown",
            priority=urgency_level,
            routing_reason=routing_reason,
            requires_human_investigation=False,
        )

        logger.info(
            "Routing decision made",
            step="routing",
            assigned_team=assigned_team,
            sla_hours=total_hours,
            priority=urgency_level,
            intent_classification=intent_classification,
            suggested_category=suggested_category,
            vendor_category=vendor_category,
            vendor_tier=vendor_tier,
            correlation_id=correlation_id,
        )

        # Phase 6: register this query with the SLA monitor so the
        # background SlaMonitor can fire warning / escalation events.
        # Non-critical — routing must not block on a DB failure.
        await self._write_sla_checkpoint(
            query_id=state.get("query_id", ""),
            correlation_id=correlation_id,
            sla_target_hours=total_hours,
        )

        await record_node(
            query_id=state.get("query_id", ""),
            correlation_id=correlation_id,
            step_name="routing",
            status="success",
            details={
                "assigned_team": assigned_team,
                "priority": urgency_level,
                "sla_hours": total_hours,
                "intent_classification": intent_classification,
                "suggested_category": suggested_category,
                "vendor_category": vendor_category,
                "vendor_tier": vendor_tier,
            },
        )

        return {
            "routing_decision": routing_decision.model_dump(),
            "status": "ROUTING",
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    async def _write_sla_checkpoint(
        self,
        *,
        query_id: str,
        correlation_id: str,
        sla_target_hours: int,
    ) -> None:
        """Insert a row into workflow.sla_checkpoints for the SLA monitor.

        Non-critical: we log and continue on any failure so a DB hiccup
        cannot derail the pipeline. If the row is missing, the monitor
        simply won't scan this query — worst case is a missed escalation
        event, which is acceptable in dev mode.
        """
        if not self._postgres or not query_id:
            return

        now = TimeHelper.ist_now()
        deadline = TimeHelper.ist_now_offset(hours=sla_target_hours)
        try:
            await self._postgres.execute(
                """
                INSERT INTO workflow.sla_checkpoints (
                    query_id, correlation_id, sla_started_at, sla_deadline,
                    sla_target_hours, last_status, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, 'ACTIVE', $6, $6)
                ON CONFLICT (query_id) DO NOTHING
                """,
                query_id,
                correlation_id,
                now,
                deadline,
                sla_target_hours,
                now,
            )
        except Exception:
            logger.warning(
                "Failed to write SLA checkpoint — continuing (non-critical)",
                query_id=query_id,
                correlation_id=correlation_id,
            )
