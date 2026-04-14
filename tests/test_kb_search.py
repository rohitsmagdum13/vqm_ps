"""Tests for the KB Search Node (Step 9B).

Tests embedding, pgvector search, threshold filtering, and
error handling (embedding failure → empty result → Path B).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestration.nodes.kb_search import KBSearchNode
from utils.exceptions import BedrockTimeoutError


@pytest.fixture
def mock_bedrock_embed() -> AsyncMock:
    """Mock BedrockConnector that returns a fixed embedding vector."""
    mock = AsyncMock()
    mock.llm_embed.return_value = [0.1] * 1024
    return mock


@pytest.fixture
def kb_node(mock_settings, mock_bedrock_embed, mock_postgres) -> KBSearchNode:
    """Create a KBSearchNode with mocked connectors."""
    return KBSearchNode(
        bedrock=mock_bedrock_embed,
        postgres=mock_postgres,
        settings=mock_settings,
    )


@pytest.fixture
def kb_state() -> dict:
    """Pipeline state for KB search tests."""
    return {
        "correlation_id": "test-123",
        "unified_payload": {
            "subject": "Invoice discrepancy",
            "body": "We noticed a discrepancy between invoice #INV-5678 and PO-2026-1234.",
        },
    }


class TestKBSearchHappyPath:
    """Tests for successful KB search."""

    @pytest.mark.asyncio
    async def test_high_match_returns_sufficient(
        self, kb_node, kb_state, mock_postgres
    ) -> None:
        """KB match above threshold returns has_sufficient_match=True."""
        mock_postgres.fetch.return_value = [
            {
                "article_id": "KB-001",
                "title": "Invoice Discrepancy Process",
                "content_snippet": "When an invoice amount differs from the PO, the vendor should..." * 5,
                "category": "billing",
                "source_url": "https://kb.example.com/001",
                "similarity_score": 0.92,
            },
        ]

        result = await kb_node.execute(kb_state)
        kb = result["kb_search_result"]

        assert kb["has_sufficient_match"] is True
        assert kb["best_match_score"] == 0.92
        assert len(kb["matches"]) == 1
        assert kb["matches"][0]["article_id"] == "KB-001"

    @pytest.mark.asyncio
    async def test_multiple_matches_ranked(
        self, kb_node, kb_state, mock_postgres
    ) -> None:
        """Multiple KB matches are returned in ranked order."""
        mock_postgres.fetch.return_value = [
            {"article_id": "KB-001", "title": "A", "content_snippet": "x" * 200,
             "category": "billing", "source_url": None, "similarity_score": 0.92},
            {"article_id": "KB-002", "title": "B", "content_snippet": "y" * 100,
             "category": "billing", "source_url": None, "similarity_score": 0.85},
            {"article_id": "KB-003", "title": "C", "content_snippet": "z" * 50,
             "category": "billing", "source_url": None, "similarity_score": 0.72},
        ]

        result = await kb_node.execute(kb_state)
        kb = result["kb_search_result"]

        assert len(kb["matches"]) == 3
        assert kb["best_match_score"] == 0.92


class TestKBSearchNoMatch:
    """Tests for no match or below threshold."""

    @pytest.mark.asyncio
    async def test_no_matches_returns_not_sufficient(
        self, kb_node, kb_state, mock_postgres
    ) -> None:
        """Empty search results returns has_sufficient_match=False."""
        mock_postgres.fetch.return_value = []

        result = await kb_node.execute(kb_state)
        kb = result["kb_search_result"]

        assert kb["has_sufficient_match"] is False
        assert kb["best_match_score"] is None
        assert len(kb["matches"]) == 0

    @pytest.mark.asyncio
    async def test_below_threshold_returns_not_sufficient(
        self, kb_node, kb_state, mock_postgres
    ) -> None:
        """Match below 0.80 threshold returns has_sufficient_match=False."""
        mock_postgres.fetch.return_value = [
            {"article_id": "KB-001", "title": "A", "content_snippet": "x" * 200,
             "category": "billing", "source_url": None, "similarity_score": 0.72},
        ]

        result = await kb_node.execute(kb_state)
        kb = result["kb_search_result"]

        assert kb["has_sufficient_match"] is False
        assert kb["best_match_score"] == 0.72


class TestKBSearchErrorHandling:
    """Tests for error handling → empty result → Path B."""

    @pytest.mark.asyncio
    async def test_embed_timeout_returns_empty(
        self, kb_node, kb_state, mock_bedrock_embed
    ) -> None:
        """BedrockTimeoutError on embedding returns empty KB result."""
        mock_bedrock_embed.llm_embed.side_effect = BedrockTimeoutError(
            model_id="titan-embed-v2", timeout_seconds=30, correlation_id="test-123"
        )

        result = await kb_node.execute(kb_state)
        kb = result["kb_search_result"]

        assert kb["has_sufficient_match"] is False
        assert len(kb["matches"]) == 0

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(
        self, kb_node, kb_state, mock_postgres
    ) -> None:
        """PostgreSQL error on vector search returns empty KB result."""
        mock_postgres.fetch.side_effect = Exception("pgvector query failed")

        result = await kb_node.execute(kb_state)
        kb = result["kb_search_result"]

        assert kb["has_sufficient_match"] is False
        assert len(kb["matches"]) == 0
