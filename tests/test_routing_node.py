"""Tests for the Routing Node (Step 9A).

Covers:
- Primary routing (intent_classification alone resolves the group)
- Secondary routing (intent + vendor_category resolves the group)
- Fallback routing ("Vendor Support") when nothing matches
- LLM-suggested category trust (only when in the canonical taxonomy)
- SLA calculation by tier + urgency
- Default behavior when vendor context is missing
"""

from __future__ import annotations

import pytest

from orchestration.nodes.routing import RoutingNode, resolve_assignment_group


@pytest.fixture
def routing_node(mock_settings) -> RoutingNode:
    """Create a RoutingNode with default settings."""
    return RoutingNode(settings=mock_settings)


def _make_state(
    intent: str = "INVOICE_PAYMENT",
    suggested_category: str | None = None,
    urgency: str = "MEDIUM",
    tier: str = "GOLD",
    vendor_category: str | None = None,
    vendor_context: dict | None = None,
) -> dict:
    """Build a pipeline state for routing tests.

    By default, suggested_category is left blank so the deterministic
    resolver runs. Tests that want to check LLM-trust behavior set
    suggested_category explicitly.
    """
    if vendor_context is None:
        vendor_context = {
            "vendor_profile": {
                "tier": {"tier_name": tier, "sla_hours": 8, "priority_multiplier": 1.0},
                "vendor_category": vendor_category,
            },
        }
    return {
        "correlation_id": "test-123",
        "analysis_result": {
            "intent_classification": intent,
            "suggested_category": suggested_category or "",
            "urgency_level": urgency,
            "confidence_score": 0.90,
        },
        "vendor_context": vendor_context,
    }


class TestPrimaryRouting:
    """Intent_classification alone determines the assignment group."""

    @pytest.mark.asyncio
    async def test_invoice_payment_routes_to_finance(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(intent="INVOICE_PAYMENT"))
        assert result["routing_decision"]["assigned_team"] == "Vendor Finance – AP & Invoicing"

    @pytest.mark.asyncio
    async def test_compliance_audit_routes_to_compliance(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(intent="COMPLIANCE_AUDIT"))
        assert result["routing_decision"]["assigned_team"] == "Vendor Compliance & Audit"

    @pytest.mark.asyncio
    async def test_general_inquiry_routes_to_support(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(intent="GENERAL_INQUIRY"))
        assert result["routing_decision"]["assigned_team"] == "Vendor Support"


class TestSecondaryRouting:
    """vendor_category + eligible intent resolves the group."""

    @pytest.mark.asyncio
    async def test_it_services_technical_support(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="TECHNICAL_SUPPORT", vendor_category="IT Services")
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor IT Services"

    @pytest.mark.asyncio
    async def test_telecom_sla_breach(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="SLA_BREACH_REPORT", vendor_category="Telecom")
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor Telecom Services"

    @pytest.mark.asyncio
    async def test_security_contract_query(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="CONTRACT_QUERY", vendor_category="Security")
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor Security Services"

    @pytest.mark.asyncio
    async def test_raw_materials_purchase_order(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="PURCHASE_ORDER", vendor_category="Raw Materials")
        )
        assert (
            result["routing_decision"]["assigned_team"]
            == "Vendor Procurement – Raw Materials"
        )

    @pytest.mark.asyncio
    async def test_manufacturing_catalog_pricing(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="CATALOG_PRICING", vendor_category="Manufacturing")
        )
        assert (
            result["routing_decision"]["assigned_team"]
            == "Vendor Procurement – Manufacturing"
        )

    @pytest.mark.asyncio
    async def test_office_supplies_return_refund(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="RETURN_REFUND", vendor_category="Office Supplies")
        )
        assert (
            result["routing_decision"]["assigned_team"]
            == "Vendor Procurement – Office Supplies"
        )

    @pytest.mark.asyncio
    async def test_facilities_quality_issue(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="QUALITY_ISSUE", vendor_category="Facilities")
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor Facilities Management"

    @pytest.mark.asyncio
    async def test_logistics_delivery_shipment(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="DELIVERY_SHIPMENT", vendor_category="Logistics")
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor Logistics Management"

    @pytest.mark.asyncio
    async def test_professional_services_onboarding(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="ONBOARDING", vendor_category="Professional Services")
        )
        assert (
            result["routing_decision"]["assigned_team"] == "Vendor Professional Services"
        )

    @pytest.mark.asyncio
    async def test_consulting_quality_issue(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(intent="QUALITY_ISSUE", vendor_category="Consulting")
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor Consulting Services"


class TestFallbackRouting:
    """Anything unmatched defaults to Vendor Support."""

    @pytest.mark.asyncio
    async def test_unknown_intent_routes_to_support(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(intent="WHO_KNOWS"))
        assert result["routing_decision"]["assigned_team"] == "Vendor Support"

    @pytest.mark.asyncio
    async def test_eligible_intent_wrong_category_routes_to_support(
        self, routing_node
    ) -> None:
        # TECHNICAL_SUPPORT is eligible only for IT/Telecom/Security categories.
        # If the vendor is in Logistics, it falls through to Vendor Support.
        result = await routing_node.execute(
            _make_state(intent="TECHNICAL_SUPPORT", vendor_category="Logistics")
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor Support"

    @pytest.mark.asyncio
    async def test_missing_vendor_category_falls_back_to_support(
        self, routing_node
    ) -> None:
        # Intent isn't a primary-routing intent and no vendor_category.
        result = await routing_node.execute(
            _make_state(intent="DELIVERY_SHIPMENT", vendor_category=None)
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor Support"


class TestSuggestedCategoryTrust:
    """LLM-emitted suggested_category overrides the resolver only when valid."""

    @pytest.mark.asyncio
    async def test_valid_suggested_category_wins(self, routing_node) -> None:
        # Intent says ONBOARDING + Consulting → Vendor Consulting Services
        # but the LLM suggested Vendor IT Services. We trust the LLM
        # because the value is in the canonical taxonomy.
        result = await routing_node.execute(
            _make_state(
                intent="ONBOARDING",
                vendor_category="Consulting",
                suggested_category="Vendor IT Services",
            )
        )
        assert result["routing_decision"]["assigned_team"] == "Vendor IT Services"

    @pytest.mark.asyncio
    async def test_garbage_suggested_category_falls_through(self, routing_node) -> None:
        # LLM hallucinated a non-existent group → fall back to resolver.
        result = await routing_node.execute(
            _make_state(intent="INVOICE_PAYMENT", suggested_category="finance-ops")
        )
        assert (
            result["routing_decision"]["assigned_team"]
            == "Vendor Finance – AP & Invoicing"
        )


class TestSLACalculation:
    """SLA calculation by tier + urgency (unchanged math)."""

    @pytest.mark.asyncio
    async def test_platinum_critical_1h(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(urgency="CRITICAL", tier="PLATINUM")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 1

    @pytest.mark.asyncio
    async def test_gold_high_4h(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(urgency="HIGH", tier="GOLD"))
        assert result["routing_decision"]["sla_target"]["total_hours"] == 4

    @pytest.mark.asyncio
    async def test_silver_medium_16h(self, routing_node) -> None:
        result = await routing_node.execute(
            _make_state(urgency="MEDIUM", tier="SILVER")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 16

    @pytest.mark.asyncio
    async def test_bronze_low_36h(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(urgency="LOW", tier="BRONZE"))
        assert result["routing_decision"]["sla_target"]["total_hours"] == 36


class TestRoutingDefaults:
    """Default behavior when vendor context is missing."""

    @pytest.mark.asyncio
    async def test_missing_vendor_context_defaults_to_bronze(
        self, routing_node
    ) -> None:
        state = _make_state(vendor_context={})
        result = await routing_node.execute(state)
        assert result["routing_decision"]["sla_target"]["total_hours"] == 24

    @pytest.mark.asyncio
    async def test_status_set_to_routing(self, routing_node) -> None:
        result = await routing_node.execute(_make_state())
        assert result["status"] == "ROUTING"

    @pytest.mark.asyncio
    async def test_routing_reason_included(self, routing_node) -> None:
        result = await routing_node.execute(_make_state())
        assert len(result["routing_decision"]["routing_reason"]) > 0


class TestResolverDirect:
    """Direct unit tests for resolve_assignment_group."""

    def test_primary_invoice_payment(self) -> None:
        assert (
            resolve_assignment_group("INVOICE_PAYMENT", "IT Services")
            == "Vendor Finance – AP & Invoicing"
        )

    def test_secondary_it_services(self) -> None:
        assert (
            resolve_assignment_group("TECHNICAL_SUPPORT", "IT Services")
            == "Vendor IT Services"
        )

    def test_fallback_when_category_missing(self) -> None:
        assert resolve_assignment_group("DELIVERY_SHIPMENT", None) == "Vendor Support"

    def test_fallback_when_intent_unknown(self) -> None:
        assert resolve_assignment_group("MYSTERY_INTENT", "IT Services") == "Vendor Support"

    def test_case_insensitive_category(self) -> None:
        assert (
            resolve_assignment_group("technical_support", "it services")
            == "Vendor IT Services"
        )
