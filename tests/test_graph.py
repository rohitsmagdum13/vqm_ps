"""Tests for the LangGraph Pipeline Orchestrator.

Tests all three processing paths (A, B, C) with mocked nodes
to verify correct routing through the graph.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestration.graph import build_pipeline_graph
from utils.helpers import TimeHelper


def _make_mock_node(return_updates: dict) -> AsyncMock:
    """Create a mock node whose execute() returns the given state updates."""
    mock = AsyncMock()
    mock.execute.return_value = return_updates
    return mock


def _base_state() -> dict:
    """Minimal pipeline state to start graph execution."""
    now = TimeHelper.ist_now().isoformat()
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "test-corr-001",
        "execution_id": "test-exec-001",
        "source": "email",
        "unified_payload": {
            "query_id": "VQ-2026-0001",
            "vendor_id": "V-001",
            "subject": "Invoice question",
            "body": "I have a question about invoice INV-5678.",
            "source": "email",
            "attachments": [],
        },
        "status": "RECEIVED",
        "created_at": now,
        "updated_at": now,
    }


class TestPathA:
    """Tests for Path A (AI-resolved) flow through the graph."""

    @pytest.mark.asyncio
    async def test_path_a_reaches_delivery(self) -> None:
        """High confidence + sufficient KB match → Path A → delivery."""
        now = TimeHelper.ist_now().isoformat()

        context_node = _make_mock_node({
            "vendor_context": {"vendor_id": "V-001", "vendor_profile": {"vendor_name": "TechNova"}},
            "status": "ANALYZING",
            "updated_at": now,
        })
        analysis_node = _make_mock_node({
            "analysis_result": {
                "intent_classification": "invoice_inquiry",
                "confidence_score": 0.92,
                "urgency_level": "HIGH",
                "sentiment": "NEGATIVE",
                "suggested_category": "billing",
                "extracted_entities": {},
                "multi_issue_detected": False,
                "tokens_in": 1500,
                "tokens_out": 450,
                "model_id": "test-model",
                "analysis_duration_ms": 2500,
            },
            "updated_at": now,
        })
        # Confidence >= 0.85 → no processing_path set → continue
        confidence_node = _make_mock_node({"updated_at": now})
        routing_node = _make_mock_node({
            "routing_decision": {
                "assigned_team": "finance-ops",
                "category": "billing",
                "priority": "HIGH",
                "sla_target": {"total_hours": 4},
                "routing_reason": "Billing query routed to finance-ops",
                "requires_human_investigation": False,
            },
            "status": "ROUTING",
            "updated_at": now,
        })
        kb_node = _make_mock_node({
            "kb_search_result": {
                "matches": [{"article_id": "KB-001", "content_snippet": "x" * 200, "similarity_score": 0.92}],
                "best_match_score": 0.92,
                "has_sufficient_match": True,
                "search_duration_ms": 500,
                "query_embedding_model": "titan-embed-v2",
            },
            "updated_at": now,
        })
        path_node = _make_mock_node({
            "processing_path": "A",
            "status": "DRAFTING",
            "updated_at": now,
        })

        resolution_node = _make_mock_node({
            "draft_response": {"draft_type": "RESOLUTION", "subject": "Re: Test", "body": "test", "confidence": 0.9, "sources": ["KB-001"]},
            "status": "VALIDATING",
            "updated_at": now,
        })
        acknowledgment_node = _make_mock_node({
            "draft_response": {"draft_type": "ACKNOWLEDGMENT", "subject": "Re: Test", "body": "test", "confidence": 0.9, "sources": []},
            "status": "VALIDATING",
            "updated_at": now,
        })
        quality_gate_node = _make_mock_node({
            "quality_gate_result": {"passed": True, "checks_run": 7, "checks_passed": 7, "failed_checks": []},
            "status": "DELIVERING",
            "updated_at": now,
        })
        delivery_node = _make_mock_node({
            "ticket_info": {"ticket_id": "INC-0000001"},
            "status": "RESOLVED",
            "updated_at": now,
        })

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
        )

        result = await compiled.ainvoke(_base_state())

        # Should reach delivery and be RESOLVED
        assert result["processing_path"] == "A"
        assert result["status"] == "RESOLVED"

        # All real nodes should have been called
        context_node.execute.assert_called_once()
        analysis_node.execute.assert_called_once()
        confidence_node.execute.assert_called_once()
        routing_node.execute.assert_called_once()
        kb_node.execute.assert_called_once()
        path_node.execute.assert_called_once()
        resolution_node.execute.assert_called_once()
        quality_gate_node.execute.assert_called_once()
        delivery_node.execute.assert_called_once()


class TestPathB:
    """Tests for Path B (human-team-resolved) flow through the graph."""

    @pytest.mark.asyncio
    async def test_path_b_reaches_delivery(self) -> None:
        """High confidence + no KB match → Path B → delivery."""
        now = TimeHelper.ist_now().isoformat()

        context_node = _make_mock_node({
            "vendor_context": {"vendor_id": "V-001", "vendor_profile": {"vendor_name": "TechNova"}},
            "status": "ANALYZING",
            "updated_at": now,
        })
        analysis_node = _make_mock_node({
            "analysis_result": {
                "intent_classification": "delivery_status",
                "confidence_score": 0.90,
                "urgency_level": "MEDIUM",
                "sentiment": "NEUTRAL",
                "suggested_category": "delivery",
                "extracted_entities": {},
                "multi_issue_detected": False,
                "tokens_in": 1500,
                "tokens_out": 450,
                "model_id": "test-model",
                "analysis_duration_ms": 2500,
            },
            "updated_at": now,
        })
        confidence_node = _make_mock_node({"updated_at": now})
        routing_node = _make_mock_node({
            "routing_decision": {
                "assigned_team": "supply-chain",
                "category": "delivery",
                "priority": "MEDIUM",
                "sla_target": {"total_hours": 8},
                "routing_reason": "Delivery query routed to supply-chain",
                "requires_human_investigation": False,
            },
            "status": "ROUTING",
            "updated_at": now,
        })
        kb_node = _make_mock_node({
            "kb_search_result": {
                "matches": [],
                "best_match_score": None,
                "has_sufficient_match": False,
                "search_duration_ms": 500,
                "query_embedding_model": "titan-embed-v2",
            },
            "updated_at": now,
        })
        path_node = _make_mock_node({
            "processing_path": "B",
            "status": "DRAFTING",
            "updated_at": now,
        })

        resolution_node = _make_mock_node({"updated_at": now})
        acknowledgment_node = _make_mock_node({
            "draft_response": {"draft_type": "ACKNOWLEDGMENT", "subject": "Re: Test", "body": "test", "confidence": 0.9, "sources": []},
            "status": "VALIDATING",
            "updated_at": now,
        })
        quality_gate_node = _make_mock_node({
            "quality_gate_result": {"passed": True, "checks_run": 7, "checks_passed": 7, "failed_checks": []},
            "status": "DELIVERING",
            "updated_at": now,
        })
        delivery_node = _make_mock_node({
            "ticket_info": {"ticket_id": "INC-0000001"},
            "status": "RESOLVED",
            "updated_at": now,
        })

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
        )

        result = await compiled.ainvoke(_base_state())

        assert result["processing_path"] == "B"
        assert result["status"] == "RESOLVED"
        routing_node.execute.assert_called_once()
        kb_node.execute.assert_called_once()
        acknowledgment_node.execute.assert_called_once()
        delivery_node.execute.assert_called_once()


class TestPathC:
    """Tests for Path C (low-confidence) flow through the graph."""

    @pytest.mark.asyncio
    async def test_path_c_pauses_at_triage(self) -> None:
        """Low confidence → Path C → triage → END (workflow pauses)."""
        now = TimeHelper.ist_now().isoformat()

        context_node = _make_mock_node({
            "vendor_context": None,
            "status": "ANALYZING",
            "updated_at": now,
        })
        analysis_node = _make_mock_node({
            "analysis_result": {
                "intent_classification": "UNKNOWN",
                "confidence_score": 0.30,
                "urgency_level": "MEDIUM",
                "sentiment": "NEUTRAL",
                "suggested_category": "general",
                "extracted_entities": {},
                "multi_issue_detected": False,
                "tokens_in": 1500,
                "tokens_out": 50,
                "model_id": "test-model",
                "analysis_duration_ms": 1000,
            },
            "updated_at": now,
        })
        # Confidence < 0.85 → Path C
        confidence_node = _make_mock_node({
            "processing_path": "C",
            "status": "PAUSED",
            "updated_at": now,
        })
        # These should NOT be called for Path C
        routing_node = _make_mock_node({})
        kb_node = _make_mock_node({})
        path_node = _make_mock_node({})

        resolution_node = _make_mock_node({})
        acknowledgment_node = _make_mock_node({})
        quality_gate_node = _make_mock_node({})
        delivery_node = _make_mock_node({})

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
        )

        result = await compiled.ainvoke(_base_state())

        assert result["processing_path"] == "C"
        assert result["status"] == "PAUSED"

        # Routing, KB search, and Phase 4 nodes should NOT have been called
        routing_node.execute.assert_not_called()
        kb_node.execute.assert_not_called()
        path_node.execute.assert_not_called()
        resolution_node.execute.assert_not_called()
        delivery_node.execute.assert_not_called()


class TestGraphStructure:
    """Tests for graph structure and edge wiring."""

    @pytest.mark.asyncio
    async def test_graph_compiles_without_error(self) -> None:
        """Graph should compile successfully with mock nodes."""
        mock_node = _make_mock_node({})
        compiled = build_pipeline_graph(
            context_loading_node=mock_node,
            query_analysis_node=mock_node,
            confidence_check_node=mock_node,
            routing_node=mock_node,
            kb_search_node=mock_node,
            path_decision_node=mock_node,
            resolution_node=mock_node,
            acknowledgment_node=mock_node,
            quality_gate_node=mock_node,
            delivery_node=mock_node,
        )
        # compiled graph should have an ainvoke method
        assert hasattr(compiled, "ainvoke")
