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
        triage_node = _make_mock_node({})
        resolution_from_notes_node = _make_mock_node({})

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            triage_node=triage_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
            resolution_from_notes_node=resolution_from_notes_node,
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
        # Path A should never touch triage or resolution-from-notes
        triage_node.execute.assert_not_called()
        resolution_from_notes_node.execute.assert_not_called()


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
        triage_node = _make_mock_node({})
        resolution_from_notes_node = _make_mock_node({})

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            triage_node=triage_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
            resolution_from_notes_node=resolution_from_notes_node,
        )

        result = await compiled.ainvoke(_base_state())

        assert result["processing_path"] == "B"
        assert result["status"] == "RESOLVED"
        routing_node.execute.assert_called_once()
        kb_node.execute.assert_called_once()
        acknowledgment_node.execute.assert_called_once()
        delivery_node.execute.assert_called_once()
        # Path B should never touch triage or resolution-from-notes
        triage_node.execute.assert_not_called()
        resolution_from_notes_node.execute.assert_not_called()


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
        # Confidence < 0.85 → Path C. The confidence node sets the path;
        # the triage node then persists the package and marks PAUSED.
        confidence_node = _make_mock_node({
            "processing_path": "C",
            "updated_at": now,
        })
        triage_node = _make_mock_node({
            "triage_package": {
                "query_id": "VQ-2026-0001",
                "callback_token": "test-token-abc",
                "status": "PENDING",
            },
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
        resolution_from_notes_node = _make_mock_node({})

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            triage_node=triage_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
            resolution_from_notes_node=resolution_from_notes_node,
        )

        result = await compiled.ainvoke(_base_state())

        assert result["processing_path"] == "C"
        assert result["status"] == "PAUSED"
        assert result["triage_package"]["callback_token"] == "test-token-abc"

        # Triage runs once and workflow stops there
        triage_node.execute.assert_called_once()
        # Routing, KB search, and Phase 4 nodes should NOT have been called
        routing_node.execute.assert_not_called()
        kb_node.execute.assert_not_called()
        path_node.execute.assert_not_called()
        resolution_node.execute.assert_not_called()
        delivery_node.execute.assert_not_called()
        resolution_from_notes_node.execute.assert_not_called()


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
            triage_node=mock_node,
            routing_node=mock_node,
            kb_search_node=mock_node,
            path_decision_node=mock_node,
            resolution_node=mock_node,
            acknowledgment_node=mock_node,
            quality_gate_node=mock_node,
            delivery_node=mock_node,
            resolution_from_notes_node=mock_node,
        )
        # compiled graph should have an ainvoke method
        assert hasattr(compiled, "ainvoke")


class TestStep15ResolutionFromNotes:
    """Phase 6 Step 15 — resume_context routes directly to resolution_from_notes."""

    @pytest.mark.asyncio
    async def test_resume_skips_intake_and_goes_to_resolution_from_notes(self) -> None:
        """resume_context.action=prepare_resolution bypasses context/analysis/routing."""
        now = TimeHelper.ist_now().isoformat()

        # Nodes that MUST NOT run on the resume path
        context_node = _make_mock_node({})
        analysis_node = _make_mock_node({})
        confidence_node = _make_mock_node({})
        routing_node = _make_mock_node({})
        kb_node = _make_mock_node({})
        path_node = _make_mock_node({})
        resolution_node = _make_mock_node({})
        acknowledgment_node = _make_mock_node({})
        triage_node = _make_mock_node({})

        # Nodes that DO run on the resume path: resolution_from_notes → gate → delivery
        resolution_from_notes_node = _make_mock_node({
            "draft_response": {
                "draft_type": "RESOLUTION",
                "subject": "Re: Invoice discrepancy [INC1234567]",
                "body": "resolved",
                "confidence": 0.9,
                "sources": ["team-notes"],
            },
            "status": "VALIDATING",
            "updated_at": now,
        })
        quality_gate_node = _make_mock_node({
            "quality_gate_result": {
                "passed": True,
                "checks_run": 7,
                "checks_passed": 7,
                "failed_checks": [],
            },
            "status": "DELIVERING",
            "updated_at": now,
        })
        delivery_node = _make_mock_node({
            "ticket_info": {"ticket_id": "INC1234567"},
            "status": "RESOLVED",
            "updated_at": now,
        })

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            triage_node=triage_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
            resolution_from_notes_node=resolution_from_notes_node,
        )

        state = _base_state()
        state["resume_context"] = {
            "action": "prepare_resolution",
            "from_servicenow": True,
            "ticket_id": "INC1234567",
        }
        state["ticket_info"] = {"ticket_number": "INC1234567"}

        result = await compiled.ainvoke(state)

        # Resume branch ran end-to-end
        resolution_from_notes_node.execute.assert_called_once()
        quality_gate_node.execute.assert_called_once()
        delivery_node.execute.assert_called_once()

        # Intake-side nodes never touched
        context_node.execute.assert_not_called()
        analysis_node.execute.assert_not_called()
        confidence_node.execute.assert_not_called()
        routing_node.execute.assert_not_called()
        kb_node.execute.assert_not_called()
        path_node.execute.assert_not_called()
        resolution_node.execute.assert_not_called()
        acknowledgment_node.execute.assert_not_called()
        triage_node.execute.assert_not_called()

        assert result["status"] == "RESOLVED"

    @pytest.mark.asyncio
    async def test_resume_with_wrong_action_takes_normal_path(self) -> None:
        """An unrelated resume_context (e.g. is_reopen) takes the normal intake path."""
        now = TimeHelper.ist_now().isoformat()

        # Give the normal-path nodes realistic returns so the graph reaches delivery
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
                "sentiment": "NEUTRAL",
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
        confidence_node = _make_mock_node({"updated_at": now})
        routing_node = _make_mock_node({
            "routing_decision": {
                "assigned_team": "finance-ops",
                "category": "billing",
                "priority": "HIGH",
                "sla_target": {"total_hours": 4},
                "routing_reason": "test",
                "requires_human_investigation": False,
            },
            "updated_at": now,
        })
        kb_node = _make_mock_node({
            "kb_search_result": {
                "matches": [],
                "best_match_score": None,
                "has_sufficient_match": False,
                "search_duration_ms": 100,
                "query_embedding_model": "titan-embed-v2",
            },
            "updated_at": now,
        })
        path_node = _make_mock_node({
            "processing_path": "B",
            "status": "DRAFTING",
            "updated_at": now,
        })
        resolution_node = _make_mock_node({})
        acknowledgment_node = _make_mock_node({
            "draft_response": {
                "draft_type": "ACKNOWLEDGMENT",
                "subject": "Re: Test",
                "body": "ack",
                "confidence": 0.9,
                "sources": [],
            },
            "status": "VALIDATING",
            "updated_at": now,
        })
        quality_gate_node = _make_mock_node({
            "quality_gate_result": {"passed": True, "checks_run": 7, "checks_passed": 7, "failed_checks": []},
            "status": "DELIVERING",
            "updated_at": now,
        })
        delivery_node = _make_mock_node({
            "ticket_info": {"ticket_id": "INC-0000002"},
            "status": "RESOLVED",
            "updated_at": now,
        })
        triage_node = _make_mock_node({})
        resolution_from_notes_node = _make_mock_node({})

        compiled = build_pipeline_graph(
            context_loading_node=context_node,
            query_analysis_node=analysis_node,
            confidence_check_node=confidence_node,
            triage_node=triage_node,
            routing_node=routing_node,
            kb_search_node=kb_node,
            path_decision_node=path_node,
            resolution_node=resolution_node,
            acknowledgment_node=acknowledgment_node,
            quality_gate_node=quality_gate_node,
            delivery_node=delivery_node,
            resolution_from_notes_node=resolution_from_notes_node,
        )

        state = _base_state()
        # A reopen resume context does NOT go to resolution_from_notes — it
        # should walk through context_loading like a fresh run.
        state["resume_context"] = {"is_reopen": True}

        await compiled.ainvoke(state)

        context_node.execute.assert_called_once()
        analysis_node.execute.assert_called_once()
        # The resolution-from-notes branch must stay untouched
        resolution_from_notes_node.execute.assert_not_called()
