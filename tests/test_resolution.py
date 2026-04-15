"""Tests for ResolutionNode (Path A — Step 10A).

All tests mock the LLM gateway. No real Bedrock/OpenAI calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestration.nodes.resolution import ResolutionNode
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
    """Mock LLM gateway with default successful response."""
    llm = AsyncMock()
    llm.llm_complete.return_value = {
        "response_text": _sample_llm_response(),
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 2800,
        "tokens_out": 650,
        "cost_usd": 0.021,
        "latency_ms": 3200,
    }
    return llm


@pytest.fixture
def resolution_node(mock_llm, prompt_manager, mock_settings) -> ResolutionNode:
    """ResolutionNode with mocked LLM."""
    return ResolutionNode(mock_llm, prompt_manager, mock_settings)


@pytest.fixture
def pipeline_state_path_a() -> dict:
    """Pipeline state that has been routed to Path A."""
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "test-corr-001",
        "execution_id": "exec-001",
        "source": "email",
        "unified_payload": {
            "subject": "Invoice discrepancy for PO-2026-1234",
            "body": "We noticed a mismatch between invoice and PO amounts.",
        },
        "vendor_context": {
            "vendor_profile": {
                "vendor_id": "V-001",
                "vendor_name": "TechNova Solutions",
                "tier": {"tier_name": "GOLD"},
            },
            "recent_interactions": [],
        },
        "analysis_result": {
            "intent_classification": "invoice_inquiry",
            "extracted_entities": {
                "invoice_number": "INV-5678",
                "po_number": "PO-2026-1234",
                "amount": "$15,000",
            },
            "urgency_level": "HIGH",
            "sentiment": "NEUTRAL",
            "confidence_score": 0.92,
        },
        "routing_decision": {
            "assigned_team": "finance-ops",
            "category": "billing",
            "priority": "HIGH",
            "sla_target": {"total_hours": 4},
        },
        "kb_search_result": {
            "has_sufficient_match": True,
            "best_match_score": 0.91,
            "matches": [
                {
                    "article_id": "KB-001",
                    "title": "Invoice Discrepancy Resolution Process",
                    "content_snippet": (
                        "When a vendor reports an invoice discrepancy, verify the PO amount "
                        "against the invoice. If amounts differ, check for approved change orders. "
                        "Standard resolution: issue a credit memo or revised invoice."
                    ),
                    "similarity_score": 0.91,
                    "category": "billing",
                },
                {
                    "article_id": "KB-002",
                    "title": "PO Amendment Procedures",
                    "content_snippet": (
                        "Purchase orders can be amended if the original scope changed. "
                        "The vendor should submit a change request referencing the original PO."
                    ),
                    "similarity_score": 0.84,
                    "category": "billing",
                },
            ],
        },
        "processing_path": "A",
        "status": "DRAFTING",
        "created_at": "2026-04-15T10:00:00",
        "updated_at": "2026-04-15T10:01:00",
    }


def _sample_llm_response() -> str:
    """Realistic LLM JSON response for resolution."""
    return """{
  "subject": "Re: Invoice discrepancy for PO-2026-1234 [PENDING]",
  "body_html": "<html><body><p>Dear TechNova Solutions,</p><p>Thank you for reaching out regarding the invoice discrepancy for PO-2026-1234.</p><p>Based on our records, the PO was originally approved for $12,500. If the invoice amount of $15,000 reflects additional work, a change order would need to be submitted referencing PO-2026-1234. Otherwise, we can issue a credit memo to align the amounts.</p><p><strong>Next Steps:</strong></p><ul><li>If a change order was approved, please send us the reference number.</li><li>Otherwise, a revised invoice for $12,500 can be submitted.</li></ul><p>Your ticket number is PENDING for reference.</p><p>Best regards,<br>Vendor Support Team</p></body></html>",
  "confidence": 0.89,
  "sources": ["KB-001", "KB-002"]
}"""


# ===========================
# Tests: Successful Draft
# ===========================


class TestResolutionDraft:
    """Tests for successful resolution drafting."""

    async def test_returns_draft_response(
        self, resolution_node, pipeline_state_path_a
    ) -> None:
        """Successful draft returns a DraftResponse dict."""
        result = await resolution_node.execute(pipeline_state_path_a)

        draft = result["draft_response"]
        assert draft is not None
        assert draft["draft_type"] == "RESOLUTION"
        assert "subject" in draft
        assert "body" in draft
        assert draft["confidence"] == 0.89

    async def test_draft_includes_sources(
        self, resolution_node, pipeline_state_path_a
    ) -> None:
        """Draft includes KB article sources."""
        result = await resolution_node.execute(pipeline_state_path_a)

        draft = result["draft_response"]
        assert draft["sources"] == ["KB-001", "KB-002"]

    async def test_draft_includes_model_metadata(
        self, resolution_node, pipeline_state_path_a
    ) -> None:
        """Draft includes model_id, tokens_in, tokens_out."""
        result = await resolution_node.execute(pipeline_state_path_a)

        draft = result["draft_response"]
        assert draft["model_id"] == "anthropic.claude-3-5-sonnet"
        assert draft["tokens_in"] == 2800
        assert draft["tokens_out"] == 650
        assert draft["draft_duration_ms"] >= 0

    async def test_status_set_to_validating(
        self, resolution_node, pipeline_state_path_a
    ) -> None:
        """Status transitions to VALIDATING after draft."""
        result = await resolution_node.execute(pipeline_state_path_a)
        assert result["status"] == "VALIDATING"

    async def test_llm_called_with_temperature_03(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """Resolution uses temperature 0.3 for creativity in drafting."""
        await resolution_node.execute(pipeline_state_path_a)

        call_args = mock_llm.llm_complete.call_args
        assert call_args.kwargs["temperature"] == 0.3

    async def test_prompt_includes_vendor_name(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """Rendered prompt includes the vendor name."""
        await resolution_node.execute(pipeline_state_path_a)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "TechNova Solutions" in prompt

    async def test_prompt_includes_kb_articles(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """Rendered prompt includes KB article titles and content."""
        await resolution_node.execute(pipeline_state_path_a)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "Invoice Discrepancy Resolution Process" in prompt
        assert "PO Amendment Procedures" in prompt

    async def test_prompt_uses_pending_ticket_number(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """Prompt uses PENDING as ticket number placeholder."""
        await resolution_node.execute(pipeline_state_path_a)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "PENDING" in prompt


# ===========================
# Tests: LLM Failure
# ===========================


class TestResolutionLLMFailure:
    """Tests for LLM call failures."""

    async def test_llm_timeout_returns_draft_failed(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """BedrockTimeoutError results in DRAFT_FAILED status."""
        mock_llm.llm_complete.side_effect = BedrockTimeoutError("test-model", 30.0)

        result = await resolution_node.execute(pipeline_state_path_a)

        assert result["draft_response"] is None
        assert result["status"] == "DRAFT_FAILED"

    async def test_invalid_json_returns_draft_failed(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """Unparseable LLM response results in DRAFT_FAILED."""
        mock_llm.llm_complete.return_value = {
            "response_text": "Sorry, I cannot generate a response.",
            "model_id": "test",
            "tokens_in": 100,
            "tokens_out": 20,
            "cost_usd": 0.001,
            "latency_ms": 500,
        }

        result = await resolution_node.execute(pipeline_state_path_a)

        assert result["draft_response"] is None
        assert result["status"] == "DRAFT_FAILED"


# ===========================
# Tests: JSON Parsing
# ===========================


class TestResolutionJsonParsing:
    """Tests for JSON extraction from LLM response."""

    async def test_parses_json_in_markdown_fences(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """LLM response wrapped in markdown fences is parsed correctly."""
        mock_llm.llm_complete.return_value = {
            "response_text": '```json\n{"subject": "Re: Test", "body_html": "<p>Hello</p>", "confidence": 0.85, "sources": ["KB-001"]}\n```',
            "model_id": "test",
            "tokens_in": 100,
            "tokens_out": 50,
            "cost_usd": 0.001,
            "latency_ms": 500,
        }

        result = await resolution_node.execute(pipeline_state_path_a)
        assert result["draft_response"] is not None
        assert result["draft_response"]["subject"] == "Re: Test"

    async def test_parses_json_with_preamble(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """LLM response with preamble text before JSON is parsed."""
        mock_llm.llm_complete.return_value = {
            "response_text": 'Here is the resolution:\n{"subject": "Re: Query", "body_html": "<p>Hi</p>", "confidence": 0.90, "sources": []}',
            "model_id": "test",
            "tokens_in": 100,
            "tokens_out": 50,
            "cost_usd": 0.001,
            "latency_ms": 500,
        }

        result = await resolution_node.execute(pipeline_state_path_a)
        assert result["draft_response"] is not None
        assert result["draft_response"]["confidence"] == 0.90


# ===========================
# Tests: Edge Cases
# ===========================


class TestResolutionEdgeCases:
    """Tests for missing or partial state data."""

    async def test_missing_vendor_context_uses_defaults(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """Missing vendor_context uses 'Valued Vendor' and BRONZE tier."""
        pipeline_state_path_a["vendor_context"] = None

        await resolution_node.execute(pipeline_state_path_a)

        call_args = mock_llm.llm_complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "Valued Vendor" in prompt

    async def test_empty_kb_matches_produces_empty_articles(
        self, resolution_node, pipeline_state_path_a, mock_llm
    ) -> None:
        """Empty KB matches list still renders the prompt (no articles)."""
        pipeline_state_path_a["kb_search_result"] = {
            "has_sufficient_match": True,
            "matches": [],
        }

        # Should still call LLM and return a draft
        result = await resolution_node.execute(pipeline_state_path_a)
        assert result["draft_response"] is not None
