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
from models.query import QUERY_TYPE_TEAM_MAP
from models.workflow import PipelineState
from models.ticket import RoutingDecision, SLATarget
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# Team assignment by official query type (primary lookup)
# Maps the 12 VQMS query types to their handling teams.
# Imported from models.query so there is a single source of truth.

# Fallback team assignment by suggested_category keyword
# Used when the LLM returns a free-text category instead of
# an official query type (e.g., "billing" instead of "INVOICE_PAYMENT").
CATEGORY_TEAM_MAP: dict[str, str] = {
    "billing": "finance-ops",
    "invoice": "finance-ops",
    "payment": "finance-ops",
    "return": "finance-ops",
    "refund": "finance-ops",
    "delivery": "supply-chain",
    "shipping": "supply-chain",
    "logistics": "supply-chain",
    "shipment": "supply-chain",
    "contract": "legal-compliance",
    "agreement": "legal-compliance",
    "terms": "legal-compliance",
    "legal": "legal-compliance",
    "compliance": "legal-compliance",
    "audit": "legal-compliance",
    "technical": "tech-support",
    "integration": "tech-support",
    "api": "tech-support",
    "product": "tech-support",
    "catalog": "procurement",
    "pricing": "procurement",
    "purchase": "procurement",
    "onboarding": "vendor-management",
    "quality": "quality-assurance",
    "defect": "quality-assurance",
    "sla": "sla-compliance",
}

DEFAULT_TEAM = "general-support"

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
        suggested_category = analysis_result.get("suggested_category", "general")
        urgency_level = analysis_result.get("urgency_level", "MEDIUM")

        # Get vendor tier (default to BRONZE if no vendor context)
        vendor_profile = vendor_context.get("vendor_profile", {})
        tier_data = vendor_profile.get("tier", {})
        vendor_tier = tier_data.get("tier_name", "BRONZE")

        # Rule 1: Team assignment
        # First try exact match on official query type (e.g., "INVOICE_PAYMENT")
        # then fall back to keyword match on lowercase category (e.g., "billing")
        assigned_team = QUERY_TYPE_TEAM_MAP.get(
            suggested_category.upper(),
            CATEGORY_TEAM_MAP.get(suggested_category.lower(), DEFAULT_TEAM),
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
            f"Category '{suggested_category}' → team '{assigned_team}'. "
            f"Tier '{vendor_tier}' + urgency '{urgency_level}' → "
            f"SLA {total_hours}h."
        )

        routing_decision = RoutingDecision(
            assigned_team=assigned_team,
            sla_target=sla_target,
            category=suggested_category,
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
            category=suggested_category,
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
