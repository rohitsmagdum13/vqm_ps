"""Tests for the Confidence Check Node (Decision Point 1).

Tests boundary conditions at the 0.85 threshold.
"""

from __future__ import annotations

import pytest

from orchestration.nodes.confidence_check import ConfidenceCheckNode


@pytest.fixture
def confidence_node(mock_settings) -> ConfidenceCheckNode:
    """Create a ConfidenceCheckNode with default threshold (0.85)."""
    return ConfidenceCheckNode(settings=mock_settings)


def _make_state(confidence: float) -> dict:
    """Build a minimal pipeline state with a given confidence score."""
    return {
        "correlation_id": "test-123",
        "analysis_result": {
            "intent_classification": "invoice_inquiry",
            "confidence_score": confidence,
            "urgency_level": "MEDIUM",
        },
    }


class TestConfidenceCheck:
    """Tests for ConfidenceCheckNode.execute."""

    @pytest.mark.asyncio
    async def test_high_confidence_continues(self, confidence_node) -> None:
        """Confidence 0.90 should continue to routing."""
        result = await confidence_node.execute(_make_state(0.90))
        assert result.get("processing_path") is None
        assert result.get("status") is None  # No status change

    @pytest.mark.asyncio
    async def test_exact_threshold_continues(self, confidence_node) -> None:
        """Confidence exactly at 0.85 should continue (boundary)."""
        result = await confidence_node.execute(_make_state(0.85))
        assert result.get("processing_path") is None

    @pytest.mark.asyncio
    async def test_below_threshold_routes_to_path_c(self, confidence_node) -> None:
        """Confidence 0.84 should route to Path C."""
        result = await confidence_node.execute(_make_state(0.84))
        assert result["processing_path"] == "C"
        assert result["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_very_low_confidence_routes_to_path_c(self, confidence_node) -> None:
        """Confidence 0.30 (fallback) should route to Path C."""
        result = await confidence_node.execute(_make_state(0.30))
        assert result["processing_path"] == "C"
        assert result["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_zero_confidence_routes_to_path_c(self, confidence_node) -> None:
        """Confidence 0.0 should route to Path C."""
        result = await confidence_node.execute(_make_state(0.0))
        assert result["processing_path"] == "C"
        assert result["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_perfect_confidence_continues(self, confidence_node) -> None:
        """Confidence 1.0 should continue."""
        result = await confidence_node.execute(_make_state(1.0))
        assert result.get("processing_path") is None
