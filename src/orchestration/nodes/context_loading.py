"""Module: orchestration/nodes/context_loading.py

Context Loading Node — Step 7 in the VQMS pipeline.

Loads vendor profile (from cache or Salesforce), episodic memory
(last 5 interactions), and updates the pipeline status to ANALYZING.
This gives the downstream Query Analysis Agent rich context about
the vendor before it classifies the query.

Corresponds to Step 7 in the VQMS Architecture Document.
"""

from __future__ import annotations

import structlog

from config.settings import Settings
from db.connection import PostgresConnector
from adapters.salesforce import SalesforceConnector
from models.memory import VendorContext
from models.workflow import PipelineState
from models.vendor import VendorProfile, VendorTier
from utils.helpers import TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)


class ContextLoadingNode:
    """Loads vendor context at the start of the AI pipeline.

    Step 7.1: Load vendor profile (cache check → Salesforce fallback)
    Step 7.2: Load episodic memory (last 5 vendor interactions)
    Step 7.3: Update workflow status to ANALYZING
    """

    def __init__(
        self,
        postgres: PostgresConnector,
        salesforce: SalesforceConnector,
        settings: Settings,
    ) -> None:
        """Initialize with required connectors.

        Args:
            postgres: PostgreSQL connector for cache and memory reads.
            salesforce: Salesforce connector for vendor profile lookup.
            settings: Application settings.
        """
        self._postgres = postgres
        self._salesforce = salesforce
        self._settings = settings

    async def execute(self, state: PipelineState) -> PipelineState:
        """Load vendor context and update pipeline status.

        Args:
            state: Current pipeline state with unified_payload.

        Returns:
            Updated state with vendor_context and status=ANALYZING.
        """
        correlation_id = state.get("correlation_id", "")
        payload = state.get("unified_payload", {})
        vendor_id = payload.get("vendor_id")
        query_id = state.get("query_id") or payload.get("query_id")

        logger.info(
            "Context loading started",
            step="context_loading",
            vendor_id=vendor_id,
            correlation_id=correlation_id,
        )

        # Pull any follow-up info that arrived after this case entered the
        # pipeline. ClosureService.handle_followup_info appends to this
        # column when a vendor replies on the same thread with a missing
        # PDF / extra detail — surfacing it here means Query Analysis
        # sees the merged corpus instead of running on stale input.
        additional_context = await self._load_additional_context(
            query_id, correlation_id
        )

        # If no vendor_id (unresolved from email path), skip vendor loading
        if not vendor_id:
            logger.info(
                "No vendor_id — skipping vendor context loading",
                step="context_loading",
                correlation_id=correlation_id,
            )
            result_no_vendor: PipelineState = {
                "vendor_context": None,
                "status": "ANALYZING",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }
            if additional_context:
                result_no_vendor["additional_context"] = additional_context
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="context_loading",
                status="skipped",
                details={
                    "reason": "no_vendor_id",
                    "followup_entries": len(additional_context),
                },
            )
            return result_no_vendor

        # Step 7.1: Load vendor profile (cache → Salesforce fallback)
        vendor_profile = await self._load_vendor_profile(vendor_id, correlation_id)

        # Step 7.2: Load episodic memory (last 5 interactions)
        recent_interactions = await self._load_episodic_memory(vendor_id, correlation_id)

        # Build VendorContext
        vendor_context = VendorContext(
            vendor_id=vendor_id,
            vendor_profile=vendor_profile,
            recent_interactions=recent_interactions,
            open_tickets=[],
        )

        logger.info(
            "Context loading complete",
            step="context_loading",
            vendor_id=vendor_id,
            interactions_loaded=len(recent_interactions),
            followup_entries=len(additional_context),
            correlation_id=correlation_id,
        )

        result_with_vendor: PipelineState = {
            "vendor_context": vendor_context.model_dump(),
            "status": "ANALYZING",
            "updated_at": TimeHelper.ist_now().isoformat(),
        }
        if additional_context:
            result_with_vendor["additional_context"] = additional_context
        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="context_loading",
            status="success",
            details={
                "vendor_id": vendor_id,
                "vendor_name": vendor_profile.vendor_name,
                "vendor_tier": vendor_profile.tier.tier_name,
                "interactions_loaded": len(recent_interactions),
                "followup_entries": len(additional_context),
            },
        )
        return result_with_vendor

    async def _load_additional_context(
        self, query_id: str | None, correlation_id: str
    ) -> list[dict]:
        """Read workflow.case_execution.additional_context for this query.

        Returns an empty list if the column is NULL, the query has no
        case row yet, or the read fails. Non-critical: missing follow-up
        info should never block the pipeline.
        """
        if not query_id:
            return []
        try:
            row = await self._postgres.fetchrow(
                """
                SELECT additional_context
                FROM workflow.case_execution
                WHERE query_id = $1
                """,
                query_id,
            )
        except Exception:
            logger.warning(
                "additional_context lookup failed — continuing without it",
                step="context_loading",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return []
        if row is None:
            return []
        value = row.get("additional_context")
        if value is None:
            return []
        # asyncpg returns JSONB as a Python object directly; the str
        # branch is defensive for callers that go through a custom decoder.
        if isinstance(value, str):
            try:
                import orjson

                value = orjson.loads(value)
            except Exception:
                return []
        if not isinstance(value, list):
            return []
        return value

    async def _load_vendor_profile(
        self, vendor_id: str, correlation_id: str
    ) -> VendorProfile:
        """Load vendor profile from cache or Salesforce.

        First checks PostgreSQL cache (1-hour TTL). On cache miss,
        fetches from Salesforce and caches the result.

        Returns a default BRONZE profile if both sources fail.
        """
        # Check cache first
        try:
            cached = await self._postgres.cache_read(
                "cache.vendor_cache", "vendor_id", vendor_id
            )
            if cached:
                logger.info(
                    "Vendor profile loaded from cache",
                    step="context_loading",
                    vendor_id=vendor_id,
                    correlation_id=correlation_id,
                )
                return self._build_vendor_profile(cached)
        except Exception:
            logger.warning(
                "Cache read failed — falling back to Salesforce",
                step="context_loading",
                vendor_id=vendor_id,
                correlation_id=correlation_id,
            )

        # Cache miss — fetch from Salesforce
        try:
            sf_data = await self._salesforce.find_vendor_by_id(
                vendor_id, correlation_id=correlation_id
            )
            if sf_data:
                logger.info(
                    "Vendor profile loaded from Salesforce",
                    step="context_loading",
                    vendor_id=vendor_id,
                    correlation_id=correlation_id,
                )
                return self._build_vendor_profile_from_salesforce(sf_data, vendor_id)
        except Exception:
            logger.warning(
                "Salesforce lookup failed — using default profile",
                step="context_loading",
                vendor_id=vendor_id,
                correlation_id=correlation_id,
            )

        # Both failed — return default BRONZE profile
        return self._default_vendor_profile(vendor_id)

    async def _load_episodic_memory(
        self, vendor_id: str, correlation_id: str
    ) -> list:
        """Load last 5 interactions for this vendor.

        Non-critical: if the query fails, return an empty list
        and log a warning. The pipeline continues without history.
        """
        try:
            rows = await self._postgres.fetch(
                "SELECT * FROM memory.episodic_memory "
                "WHERE vendor_id = $1 "
                "ORDER BY resolved_at DESC LIMIT 5",
                vendor_id,
            )
            return rows
        except Exception:
            logger.warning(
                "Failed to load episodic memory — continuing without history",
                step="context_loading",
                vendor_id=vendor_id,
                correlation_id=correlation_id,
            )
            return []

    def _build_vendor_profile(self, data: dict) -> VendorProfile:
        """Build VendorProfile from cached data dict."""
        tier_data = data.get("tier", {})
        if isinstance(tier_data, dict):
            tier = VendorTier(**tier_data)
        else:
            tier = VendorTier(tier_name="BRONZE", sla_hours=24, priority_multiplier=1.0)

        return VendorProfile(
            vendor_id=data.get("vendor_id", ""),
            vendor_name=data.get("vendor_name", "Unknown"),
            tier=tier,
            primary_contact_email=data.get("primary_contact_email", ""),
            is_active=data.get("is_active", True),
            account_manager=data.get("account_manager"),
        )

    def _build_vendor_profile_from_salesforce(
        self, sf_data: dict, vendor_id: str
    ) -> VendorProfile:
        """Build VendorProfile from Salesforce Vendor_Account__c record."""
        return VendorProfile(
            vendor_id=vendor_id,
            vendor_name=sf_data.get("Name", "Unknown"),
            tier=VendorTier(tier_name="SILVER", sla_hours=16, priority_multiplier=1.0),
            primary_contact_email=sf_data.get("Email", ""),
            is_active=True,
            account_manager=sf_data.get("Owner", {}).get("Name") if isinstance(sf_data.get("Owner"), dict) else None,
        )

    def _default_vendor_profile(self, vendor_id: str) -> VendorProfile:
        """Return a default BRONZE vendor profile when all lookups fail."""
        return VendorProfile(
            vendor_id=vendor_id,
            vendor_name="Unknown Vendor",
            tier=VendorTier(tier_name="BRONZE", sla_hours=24, priority_multiplier=1.0),
            primary_contact_email="",
            is_active=True,
        )
