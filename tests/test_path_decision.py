"""Tests for the Path Decision Node (Decision Point 2).

Tests Path A (sufficient KB match) vs Path B (insufficient match).
"""

from __future__ import annotations

import pytest

from orchestration.nodes.path_decision import PathDecisionNode


@pytest.fixture
def path_node(mock_settings) -> PathDecisionNode:
    """Create a PathDecisionNode with default threshold (0.80)."""
    return PathDecisionNode(settings=mock_settings)


def _make_state(
    has_sufficient: bool = True,
    best_score: float | None = 0.92,
    content_length: int = 200,
) -> dict:
    """Build a pipeline state with KB search results."""
    matches = []
    if best_score is not None:
        matches = [
            {
                "article_id": "KB-001",
                "title": "Test Article",
                "content_snippet": "x" * content_length,
                "similarity_score": best_score,
                "category": "billing",
                "source_url": None,
            },
        ]

    return {
        "correlation_id": "test-123",
        "kb_search_result": {
            "matches": matches,
            "search_duration_ms": 500,
            "query_embedding_model": "titan-embed-v2",
            "best_match_score": best_score,
            "has_sufficient_match": has_sufficient,
        },
        "routing_decision": {
            "assigned_team": "finance-ops",
            "sla_target": {"total_hours": 4, "warning_at_percent": 70,
                           "l1_escalation_at_percent": 85, "l2_escalation_at_percent": 95},
            "category": "billing",
            "priority": "HIGH",
            "routing_reason": "Test routing",
            "requires_human_investigation": False,
        },
    }


class TestPathDecision:
    """Tests for PathDecisionNode.execute."""

    @pytest.mark.asyncio
    async def test_sufficient_match_with_facts_routes_to_path_a(self, path_node) -> None:
        """KB match >= 0.80 with content > 100 chars → Path A."""
        result = await path_node.execute(
            _make_state(has_sufficient=True, best_score=0.92, content_length=200)
        )

        assert result["processing_path"] == "A"
        assert result["status"] == "DRAFTING"

    @pytest.mark.asyncio
    async def test_no_match_routes_to_path_b(self, path_node) -> None:
        """No KB matches → Path B."""
        result = await path_node.execute(
            _make_state(has_sufficient=False, best_score=None, content_length=0)
        )

        assert result["processing_path"] == "B"
        assert result["status"] == "DRAFTING"

    @pytest.mark.asyncio
    async def test_below_threshold_routes_to_path_b(self, path_node) -> None:
        """KB match below threshold → Path B."""
        result = await path_node.execute(
            _make_state(has_sufficient=False, best_score=0.72, content_length=200)
        )

        assert result["processing_path"] == "B"

    @pytest.mark.asyncio
    async def test_short_content_routes_to_path_b(self, path_node) -> None:
        """KB match with short content (< 100 chars) → Path B."""
        result = await path_node.execute(
            _make_state(has_sufficient=True, best_score=0.90, content_length=50)
        )

        assert result["processing_path"] == "B"

    @pytest.mark.asyncio
    async def test_path_b_sets_human_investigation_flag(self, path_node) -> None:
        """Path B should update routing_decision with requires_human_investigation=True."""
        result = await path_node.execute(
            _make_state(has_sufficient=False, best_score=0.72)
        )

        routing = result.get("routing_decision", {})
        assert routing.get("requires_human_investigation") is True

    @pytest.mark.asyncio
    async def test_empty_kb_result_routes_to_path_b(self, path_node) -> None:
        """Empty kb_search_result in state → Path B."""
        state = {
            "correlation_id": "test-123",
            "kb_search_result": {
                "matches": [],
                "search_duration_ms": 0,
                "query_embedding_model": "test",
                "best_match_score": None,
                "has_sufficient_match": False,
            },
            "routing_decision": {
                "assigned_team": "general-support",
                "sla_target": {"total_hours": 24, "warning_at_percent": 70,
                               "l1_escalation_at_percent": 85, "l2_escalation_at_percent": 95},
                "category": "general",
                "priority": "MEDIUM",
                "routing_reason": "Default",
                "requires_human_investigation": False,
            },
        }

        result = await path_node.execute(state)
        assert result["processing_path"] == "B"
