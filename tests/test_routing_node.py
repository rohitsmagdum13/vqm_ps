"""Tests for the Routing Node (Step 9A).

Tests team assignment rules, SLA calculation by tier+urgency,
and default behavior when vendor context is missing.
"""

from __future__ import annotations

import pytest

from orchestration.nodes.routing import RoutingNode


@pytest.fixture
def routing_node(mock_settings) -> RoutingNode:
    """Create a RoutingNode with default settings."""
    return RoutingNode(settings=mock_settings)


def _make_state(
    category: str = "billing",
    urgency: str = "MEDIUM",
    tier: str = "GOLD",
    vendor_context: dict | None = None,
) -> dict:
    """Build a pipeline state for routing tests."""
    if vendor_context is None:
        vendor_context = {
            "vendor_profile": {
                "tier": {"tier_name": tier, "sla_hours": 8, "priority_multiplier": 1.0},
            },
        }
    return {
        "correlation_id": "test-123",
        "analysis_result": {
            "suggested_category": category,
            "urgency_level": urgency,
            "confidence_score": 0.90,
        },
        "vendor_context": vendor_context,
    }


class TestTeamAssignment:
    """Tests for team assignment by category."""

    @pytest.mark.asyncio
    async def test_billing_routes_to_finance_ops(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(category="billing"))
        assert result["routing_decision"]["assigned_team"] == "finance-ops"

    @pytest.mark.asyncio
    async def test_invoice_routes_to_finance_ops(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(category="invoice"))
        assert result["routing_decision"]["assigned_team"] == "finance-ops"

    @pytest.mark.asyncio
    async def test_delivery_routes_to_supply_chain(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(category="delivery"))
        assert result["routing_decision"]["assigned_team"] == "supply-chain"

    @pytest.mark.asyncio
    async def test_contract_routes_to_legal(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(category="contract"))
        assert result["routing_decision"]["assigned_team"] == "legal-compliance"

    @pytest.mark.asyncio
    async def test_technical_routes_to_tech_support(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(category="technical"))
        assert result["routing_decision"]["assigned_team"] == "tech-support"

    @pytest.mark.asyncio
    async def test_unknown_category_routes_to_general(self, routing_node) -> None:
        result = await routing_node.execute(_make_state(category="something_random"))
        assert result["routing_decision"]["assigned_team"] == "general-support"


class TestSLACalculation:
    """Tests for SLA calculation by tier + urgency."""

    @pytest.mark.asyncio
    async def test_platinum_critical_1h(self, routing_node) -> None:
        """PLATINUM + CRITICAL = 4h * 0.25 = 1h."""
        result = await routing_node.execute(
            _make_state(urgency="CRITICAL", tier="PLATINUM")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 1

    @pytest.mark.asyncio
    async def test_platinum_high_2h(self, routing_node) -> None:
        """PLATINUM + HIGH = 4h * 0.5 = 2h."""
        result = await routing_node.execute(
            _make_state(urgency="HIGH", tier="PLATINUM")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 2

    @pytest.mark.asyncio
    async def test_gold_critical_2h(self, routing_node) -> None:
        """GOLD + CRITICAL = 8h * 0.25 = 2h."""
        result = await routing_node.execute(
            _make_state(urgency="CRITICAL", tier="GOLD")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 2

    @pytest.mark.asyncio
    async def test_gold_high_4h(self, routing_node) -> None:
        """GOLD + HIGH = 8h * 0.5 = 4h."""
        result = await routing_node.execute(
            _make_state(urgency="HIGH", tier="GOLD")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 4

    @pytest.mark.asyncio
    async def test_silver_critical_4h(self, routing_node) -> None:
        """SILVER + CRITICAL = 16h * 0.25 = 4h."""
        result = await routing_node.execute(
            _make_state(urgency="CRITICAL", tier="SILVER")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 4

    @pytest.mark.asyncio
    async def test_silver_medium_16h(self, routing_node) -> None:
        """SILVER + MEDIUM = 16h * 1.0 = 16h."""
        result = await routing_node.execute(
            _make_state(urgency="MEDIUM", tier="SILVER")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 16

    @pytest.mark.asyncio
    async def test_bronze_any_24h(self, routing_node) -> None:
        """BRONZE + MEDIUM = 24h * 1.0 = 24h."""
        result = await routing_node.execute(
            _make_state(urgency="MEDIUM", tier="BRONZE")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 24

    @pytest.mark.asyncio
    async def test_bronze_low_36h(self, routing_node) -> None:
        """BRONZE + LOW = 24h * 1.5 = 36h."""
        result = await routing_node.execute(
            _make_state(urgency="LOW", tier="BRONZE")
        )
        assert result["routing_decision"]["sla_target"]["total_hours"] == 36


class TestRoutingDefaults:
    """Tests for default behavior."""

    @pytest.mark.asyncio
    async def test_missing_vendor_context_defaults_to_bronze(self, routing_node) -> None:
        """No vendor context should default to BRONZE tier."""
        state = _make_state(vendor_context={})
        result = await routing_node.execute(state)

        # BRONZE + MEDIUM = 24h * 1.0 = 24h
        assert result["routing_decision"]["sla_target"]["total_hours"] == 24

    @pytest.mark.asyncio
    async def test_status_set_to_routing(self, routing_node) -> None:
        """Status should be set to ROUTING."""
        result = await routing_node.execute(_make_state())
        assert result["status"] == "ROUTING"

    @pytest.mark.asyncio
    async def test_routing_reason_included(self, routing_node) -> None:
        """Routing reason should be a non-empty human-readable string."""
        result = await routing_node.execute(_make_state())
        assert len(result["routing_decision"]["routing_reason"]) > 0
