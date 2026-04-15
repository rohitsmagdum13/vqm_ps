"""Tests for AcknowledgmentNode (Path B — Step 10B).

All tests mock the LLM gateway. No real Bedrock/OpenAI calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestration.nodes.acknowledgment import AcknowledgmentNode
from orchestration.prompts.prompt_manager import PromptManager
from utils.exceptions import BedrockTimeoutError


# ===========================
# Fixtures
# ===========================


@pytest.fixture
def prompt_manager() -> PromptManager:
    """Real PromptManager that loads Jinja2 templates."""
    return PromptManager()


@pytest.fixture
def mock_llm() -> AsyncMock:
    """Mock LLM gateway with default successful acknowledgment response."""
    llm = AsyncMock()
    llm.llm_complete.return_value = {
        "response_text": _sample_ack_response(),
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 900,
        "tokens_out": 350,
        "cost_usd": 0.008,
        "latency_ms": 2100,
    }
    return llm


@pytest.fixture
def ack_node(mock_llm, prompt_manager, mock_settings) -> AcknowledgmentNode:
    """AcknowledgmentNode with mocked LLM."""
    return AcknowledgmentNode(mock_llm, prompt_manager, mock_settings)


@pytest.fixture
def pipeline_state_path_b() -> dict:
    """Pipeline state that has been routed to Path B."""
    return {
        "query_id": "VQ-2026-0002",
        "correlation_id": "test-corr-002",
        "execution_id": "exec-002",
        "source": "email",
        "unified_payload": {
            "subject": "Missing shipment for order ORD-9876",
            "body": "We have not received the shipment for our order.",
        },
        "vendor_context": {
            "vendor_profile": {
                "vendor_id": "V-002",
                "vendor_name": "GlobalParts Inc",
                "tier": {"tier_name": "SILVER"},
            },
            "recent_interactions": [],
        },
        "analysis_result": {
            "intent_classification": "delivery_inquiry",
            "extracted_entities": {"order_number": "ORD-9876"},
            "urgency_level": "HIGH",
            "sentiment": "FRUSTRATED",
            "confidence_score": 0.90,
        },
        "routing_decision": {
            "assigned_team": "logistics-ops",
            "category": "delivery",
            "priority": "HIGH",
            "sla_target": {"total_hours": 8},
            "requires_human_investigation": True,
        },
        "kb_search_result": {
            "has_sufficient_match": False,
            "best_match_score": 0.55,
            "matches": [],
        },
        "processing_path": "B",
        "status": "DRAFTING",
        "created_at": "2026-04-15T11:00:00",
        "updated_at": "2026-04-15T11:01:00",
    }


def _sample_ack_response() -> str:
    """Realistic LLM JSON response for acknowledgment."""
    return """{
  "subject": "Re: Missing shipment for order ORD-9876 [PENDING]",
  "body_html": "<html><body><p>Dear GlobalParts Inc,</p><p>Thank you for reaching out. We have received your query regarding the missing shipment for order ORD-9876.</p><p>Your request has been assigned ticket number <strong>PENDING</strong> and our logistics-ops team is actively reviewing it.</p><p>We are handling your request within our standard service agreement and you can expect an update soon.</p><p><strong>Next Steps:</strong> Our team will investigate the shipment status and provide you with a detailed update.</p><p>Best regards,<br>Vendor Support Team</p></body></html>",
  "confidence": 0.95,
  "sources": []
}"""


# ===========================
# Tests: Successful Draft
# ===========================


class TestAcknowledgmentDraft:
    """Tests for successful acknowledgment drafting."""

    async def test_returns_acknowledgment_draft(
        self, ack_node, pipeline_state_path_b
    ) -> None:
        """Successful draft returns an ACKNOWLEDGMENT type."""
        result = await ack_node.execute(pipeline_state_path_b)

        draft = result["draft_response"]
        assert draft is not None
        assert draft["draft_type"] == "ACKNOWLEDGMENT"

    async def test_sources_always_empty(
        self, ack_node, pipeline_state_path_b
    ) -> None:
        """Path B drafts never have KB sources."""
        result = await ack_node.execute(pipeline_state_path_b)

        draft = result["draft_response"]
        assert draft["sources"] == []

    async def test_draft_includes_model_metadata(
        self, ack_node, pipeline_state_path_b
    ) -> None:
        """Draft includes model_id, tokens_in, tokens_out."""
        result = await ack_node.execute(pipeline_state_path_b)

        draft = result["draft_response"]
        assert draft["model_id"] == "anthropic.claude-3-5-sonnet"
        assert draft["tokens_in"] == 900
        assert draft["tokens_out"] == 350
        assert draft["draft_duration_ms"] >= 0

    async def test_status_set_to_validating(
        self, ack_node, pipeline_state_path_b
    ) -> None:
        """Status transitions to VALIDATING after draft."""
        result = await ack_node.execute(pipeline_state_path_b)
        assert result["status"] == "VALIDATING"

    async def test_prompt_includes_vendor_name(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """Rendered prompt includes the vendor name."""
        await ack_node.execute(pipeline_state_path_b)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "GlobalParts Inc" in prompt

    async def test_prompt_includes_assigned_team(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """Rendered prompt includes the assigned team name."""
        await ack_node.execute(pipeline_state_path_b)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "logistics-ops" in prompt

    async def test_prompt_uses_pending_ticket_number(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """Prompt uses PENDING as ticket number placeholder."""
        await ack_node.execute(pipeline_state_path_b)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "PENDING" in prompt

    async def test_prompt_includes_sla_statement(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """Prompt includes tier-appropriate SLA statement."""
        await ack_node.execute(pipeline_state_path_b)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        # SILVER tier SLA statement
        assert "standard service agreement" in prompt


# ===========================
# Tests: LLM Failure
# ===========================


class TestAcknowledgmentLLMFailure:
    """Tests for LLM call failures."""

    async def test_llm_timeout_returns_draft_failed(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """BedrockTimeoutError results in DRAFT_FAILED status."""
        mock_llm.llm_complete.side_effect = BedrockTimeoutError("test-model", 30.0)

        result = await ack_node.execute(pipeline_state_path_b)

        assert result["draft_response"] is None
        assert result["status"] == "DRAFT_FAILED"

    async def test_invalid_json_returns_draft_failed(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """Unparseable LLM response results in DRAFT_FAILED."""
        mock_llm.llm_complete.return_value = {
            "response_text": "I'm sorry, I cannot process this request.",
            "model_id": "test",
            "tokens_in": 100,
            "tokens_out": 20,
            "cost_usd": 0.001,
            "latency_ms": 500,
        }

        result = await ack_node.execute(pipeline_state_path_b)

        assert result["draft_response"] is None
        assert result["status"] == "DRAFT_FAILED"


# ===========================
# Tests: Edge Cases
# ===========================


class TestAcknowledgmentEdgeCases:
    """Tests for missing or partial state data."""

    async def test_missing_vendor_context_uses_defaults(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """Missing vendor_context uses defaults."""
        pipeline_state_path_b["vendor_context"] = None

        await ack_node.execute(pipeline_state_path_b)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "Valued Vendor" in prompt

    async def test_missing_routing_uses_default_team(
        self, ack_node, pipeline_state_path_b, mock_llm
    ) -> None:
        """Missing routing_decision uses 'support team' as default."""
        pipeline_state_path_b["routing_decision"] = None

        await ack_node.execute(pipeline_state_path_b)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "support team" in prompt
