"""Tests for the Query Analysis Node (Step 8).

Tests the 8-layer defense strategy: happy path, JSON parsing
variants, self-correction, safe fallback, and error handling.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from orchestration.nodes.query_analysis import QueryAnalysisNode
from orchestration.prompts.prompt_manager import PromptManager
from utils.exceptions import BedrockTimeoutError


@pytest.fixture
def mock_bedrock_for_analysis() -> AsyncMock:
    """Mock BedrockConnector that returns valid analysis JSON."""
    mock = AsyncMock()
    mock.llm_complete.return_value = {
        "response_text": json.dumps({
            "intent_classification": "invoice_inquiry",
            "extracted_entities": {"invoice_numbers": ["INV-5678"], "po_numbers": ["PO-2026-1234"]},
            "urgency_level": "HIGH",
            "sentiment": "NEGATIVE",
            "confidence_score": 0.92,
            "multi_issue_detected": False,
            "suggested_category": "billing",
        }),
        "tokens_in": 1500,
        "tokens_out": 450,
        "cost_usd": 0.012,
        "latency_ms": 2500,
        "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    }
    return mock


@pytest.fixture
def analysis_node(mock_settings, mock_bedrock_for_analysis) -> QueryAnalysisNode:
    """Create a QueryAnalysisNode with mocked dependencies."""
    pm = PromptManager()
    return QueryAnalysisNode(
        bedrock=mock_bedrock_for_analysis,
        prompt_manager=pm,
        settings=mock_settings,
    )


@pytest.fixture
def analysis_state() -> dict:
    """Pipeline state for analysis tests."""
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "test-corr-123",
        "execution_id": "test-exec-123",
        "source": "email",
        "unified_payload": {
            "query_id": "VQ-2026-0001",
            "vendor_id": "V-001",
            "subject": "Invoice discrepancy for PO-2026-1234",
            "body": (
                "We noticed a discrepancy between invoice #INV-5678 "
                "and PO-2026-1234. The invoice shows $15,000 but the PO "
                "was approved for $12,500."
            ),
            "source": "email",
            "attachments": [],
        },
        "vendor_context": {
            "vendor_id": "V-001",
            "vendor_profile": {
                "vendor_name": "TechNova Solutions",
                "tier": {"tier_name": "GOLD", "sla_hours": 8, "priority_multiplier": 1.0},
            },
            "recent_interactions": [],
            "open_tickets": [],
        },
    }


class TestQueryAnalysisHappyPath:
    """Tests for successful query analysis."""

    @pytest.mark.asyncio
    async def test_valid_response_produces_correct_analysis(
        self, analysis_node, analysis_state
    ) -> None:
        """Valid LLM response is parsed into AnalysisResult."""
        result = await analysis_node.execute(analysis_state)

        analysis = result["analysis_result"]
        assert analysis["intent_classification"] == "invoice_inquiry"
        assert analysis["confidence_score"] == 0.92
        assert analysis["urgency_level"] == "HIGH"
        assert analysis["sentiment"] == "NEGATIVE"
        assert analysis["suggested_category"] == "billing"
        assert "INV-5678" in analysis["extracted_entities"]["invoice_numbers"]

    @pytest.mark.asyncio
    async def test_analysis_includes_llm_metrics(
        self, analysis_node, analysis_state
    ) -> None:
        """Analysis result includes token counts and model info."""
        result = await analysis_node.execute(analysis_state)

        analysis = result["analysis_result"]
        assert analysis["tokens_in"] == 1500
        assert analysis["tokens_out"] == 450
        assert analysis["model_id"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        assert analysis["analysis_duration_ms"] > 0


class TestQueryAnalysisJsonParsing:
    """Tests for JSON parsing from various LLM response formats."""

    @pytest.mark.asyncio
    async def test_json_in_markdown_fences(
        self, analysis_node, analysis_state, mock_bedrock_for_analysis
    ) -> None:
        """JSON wrapped in markdown fences is parsed correctly."""
        mock_bedrock_for_analysis.llm_complete.return_value["response_text"] = (
            "```json\n"
            '{"intent_classification": "delivery_status", "extracted_entities": {}, '
            '"urgency_level": "MEDIUM", "sentiment": "NEUTRAL", '
            '"confidence_score": 0.88, "multi_issue_detected": false, '
            '"suggested_category": "delivery"}\n'
            "```"
        )

        result = await analysis_node.execute(analysis_state)
        assert result["analysis_result"]["intent_classification"] == "delivery_status"

    @pytest.mark.asyncio
    async def test_json_with_preamble_text(
        self, analysis_node, analysis_state, mock_bedrock_for_analysis
    ) -> None:
        """JSON preceded by explanation text is parsed correctly."""
        mock_bedrock_for_analysis.llm_complete.return_value["response_text"] = (
            "Here is the analysis of the vendor query:\n"
            '{"intent_classification": "payment_issue", "extracted_entities": {}, '
            '"urgency_level": "HIGH", "sentiment": "FRUSTRATED", '
            '"confidence_score": 0.85, "multi_issue_detected": false, '
            '"suggested_category": "billing"}'
        )

        result = await analysis_node.execute(analysis_state)
        assert result["analysis_result"]["intent_classification"] == "payment_issue"


class TestQueryAnalysisSelfCorrection:
    """Tests for self-correction (Layer 6)."""

    @pytest.mark.asyncio
    async def test_self_correction_on_invalid_json(
        self, analysis_node, analysis_state, mock_bedrock_for_analysis
    ) -> None:
        """When first response is invalid JSON, self-correction is attempted."""
        # First call returns invalid JSON, second returns valid
        mock_bedrock_for_analysis.llm_complete.side_effect = [
            {
                "response_text": "This is not JSON at all!",
                "tokens_in": 1500, "tokens_out": 50,
                "cost_usd": 0.005, "latency_ms": 1000,
                "model_id": "test-model",
            },
            {
                "response_text": json.dumps({
                    "intent_classification": "general_inquiry",
                    "extracted_entities": {},
                    "urgency_level": "LOW",
                    "sentiment": "NEUTRAL",
                    "confidence_score": 0.75,
                    "multi_issue_detected": False,
                    "suggested_category": "general",
                }),
                "tokens_in": 500, "tokens_out": 200,
                "cost_usd": 0.004, "latency_ms": 800,
                "model_id": "test-model",
            },
        ]

        result = await analysis_node.execute(analysis_state)

        # Self-correction should have succeeded
        assert result["analysis_result"]["intent_classification"] == "general_inquiry"
        assert mock_bedrock_for_analysis.llm_complete.call_count == 2


class TestQueryAnalysisSafeFallback:
    """Tests for safe fallback (Layer 7)."""

    @pytest.mark.asyncio
    async def test_fallback_on_self_correction_failure(
        self, analysis_node, analysis_state, mock_bedrock_for_analysis
    ) -> None:
        """When both attempts fail, safe fallback is used."""
        mock_bedrock_for_analysis.llm_complete.side_effect = [
            {
                "response_text": "Not JSON",
                "tokens_in": 100, "tokens_out": 10,
                "cost_usd": 0.001, "latency_ms": 500,
                "model_id": "test-model",
            },
            {
                "response_text": "Still not JSON",
                "tokens_in": 100, "tokens_out": 10,
                "cost_usd": 0.001, "latency_ms": 500,
                "model_id": "test-model",
            },
        ]

        result = await analysis_node.execute(analysis_state)

        analysis = result["analysis_result"]
        assert analysis["intent_classification"] == "UNKNOWN"
        assert analysis["confidence_score"] == 0.3
        assert analysis["urgency_level"] == "MEDIUM"

    @pytest.mark.asyncio
    async def test_fallback_on_bedrock_timeout(
        self, analysis_node, analysis_state, mock_bedrock_for_analysis
    ) -> None:
        """BedrockTimeoutError triggers safe fallback."""
        mock_bedrock_for_analysis.llm_complete.side_effect = BedrockTimeoutError(
            model_id="test-model",
            timeout_seconds=30,
            correlation_id="test-123",
        )

        result = await analysis_node.execute(analysis_state)

        analysis = result["analysis_result"]
        assert analysis["intent_classification"] == "UNKNOWN"
        assert analysis["confidence_score"] == 0.3

    @pytest.mark.asyncio
    async def test_fallback_on_empty_body(self, mock_settings) -> None:
        """Empty body triggers safe fallback."""
        pm = PromptManager()
        mock_bedrock = AsyncMock()
        node = QueryAnalysisNode(bedrock=mock_bedrock, prompt_manager=pm, settings=mock_settings)

        state = {
            "correlation_id": "test-123",
            "unified_payload": {"body": "", "subject": "", "source": "email", "attachments": []},
            "vendor_context": None,
        }

        result = await node.execute(state)

        analysis = result["analysis_result"]
        assert analysis["confidence_score"] == 0.3
        # LLM should NOT have been called
        mock_bedrock.llm_complete.assert_not_called()
