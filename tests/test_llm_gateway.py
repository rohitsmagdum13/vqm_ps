"""Tests for the LLM Gateway.

Tests provider routing (bedrock_only, openai_only, fallback modes)
and fallback behavior when primary provider fails.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from adapters.llm_gateway import LLMGateway
from utils.exceptions import BedrockTimeoutError, LLMProviderError


@pytest.fixture
def bedrock_only_settings(mock_settings):
    """Settings for Bedrock-only mode."""
    mock_settings.llm_provider = "bedrock_only"
    mock_settings.embedding_provider = "bedrock_only"
    mock_settings.openai_api_key = None
    return mock_settings


@pytest.fixture
def openai_only_settings(mock_settings):
    """Settings for OpenAI-only mode."""
    mock_settings.llm_provider = "openai_only"
    mock_settings.embedding_provider = "openai_only"
    mock_settings.openai_api_key = "sk-test-key"
    return mock_settings


@pytest.fixture
def fallback_settings(mock_settings):
    """Settings for Bedrock with OpenAI fallback."""
    mock_settings.llm_provider = "bedrock_with_openai_fallback"
    mock_settings.embedding_provider = "bedrock_with_openai_fallback"
    mock_settings.openai_api_key = "sk-test-key"
    return mock_settings


@pytest.fixture
def mock_bedrock():
    """Mock BedrockConnector."""
    mock = AsyncMock()
    mock.llm_complete.return_value = {
        "response_text": "Bedrock response",
        "tokens_in": 1000,
        "tokens_out": 300,
        "cost_usd": 0.0075,
        "latency_ms": 2000,
        "model_id": "anthropic.claude-3-5-sonnet",
    }
    mock.llm_embed.return_value = [0.1] * 1024
    return mock


@pytest.fixture
def mock_openai():
    """Mock OpenAIConnector."""
    mock = AsyncMock()
    mock.llm_complete.return_value = {
        "response_text": "OpenAI response",
        "tokens_in": 1000,
        "tokens_out": 300,
        "cost_usd": 0.0055,
        "latency_ms": 1500,
        "model_id": "gpt-4o",
    }
    mock.llm_embed.return_value = [0.2] * 1024
    return mock


def _make_gateway(settings, mock_bedrock, mock_openai=None):
    """Create an LLMGateway with mocked providers injected directly.

    We bypass __init__ entirely and set internal state manually
    since __init__ creates real connectors which we don't want.
    """
    gateway = object.__new__(LLMGateway)
    gateway._settings = settings
    gateway._llm_provider = settings.llm_provider
    gateway._embedding_provider = settings.embedding_provider
    gateway._bedrock = mock_bedrock
    gateway._openai = mock_openai if settings.openai_api_key else None
    return gateway


class TestBedrockOnlyMode:
    """Tests for bedrock_only provider mode."""

    @pytest.mark.asyncio
    async def test_llm_complete_uses_bedrock(
        self, bedrock_only_settings, mock_bedrock
    ) -> None:
        """Bedrock-only mode routes to Bedrock."""
        gateway = _make_gateway(bedrock_only_settings, mock_bedrock)

        result = await gateway.llm_complete("test", correlation_id="c-1")

        assert result["model_id"] == "anthropic.claude-3-5-sonnet"
        mock_bedrock.llm_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_embed_uses_bedrock(
        self, bedrock_only_settings, mock_bedrock
    ) -> None:
        """Bedrock-only mode routes embeddings to Bedrock."""
        gateway = _make_gateway(bedrock_only_settings, mock_bedrock)

        result = await gateway.llm_embed("test", correlation_id="c-1")

        assert result == [0.1] * 1024
        mock_bedrock.llm_embed.assert_called_once()

    @pytest.mark.asyncio
    async def test_bedrock_failure_raises_without_fallback(
        self, bedrock_only_settings, mock_bedrock
    ) -> None:
        """Bedrock failure with no fallback should raise."""
        mock_bedrock.llm_complete.side_effect = BedrockTimeoutError(
            model_id="test", timeout_seconds=30, correlation_id="c-1"
        )
        gateway = _make_gateway(bedrock_only_settings, mock_bedrock)

        with pytest.raises(BedrockTimeoutError):
            await gateway.llm_complete("test", correlation_id="c-1")


class TestOpenAIOnlyMode:
    """Tests for openai_only provider mode."""

    @pytest.mark.asyncio
    async def test_llm_complete_uses_openai(
        self, openai_only_settings, mock_bedrock, mock_openai
    ) -> None:
        """OpenAI-only mode routes to OpenAI."""
        gateway = _make_gateway(openai_only_settings, mock_bedrock, mock_openai)

        result = await gateway.llm_complete("test", correlation_id="c-1")

        assert result["model_id"] == "gpt-4o"
        mock_openai.llm_complete.assert_called_once()
        mock_bedrock.llm_complete.assert_not_called()

    def test_openai_only_without_key_raises(
        self, mock_settings, mock_bedrock
    ) -> None:
        """OpenAI-only mode without API key should raise on call."""
        mock_settings.llm_provider = "openai_only"
        mock_settings.openai_api_key = None
        gateway = _make_gateway(mock_settings, mock_bedrock)

        with pytest.raises(LLMProviderError, match="OPENAI_API_KEY"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                gateway.llm_complete("test", correlation_id="c-1")
            )


class TestFallbackMode:
    """Tests for bedrock_with_openai_fallback mode."""

    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(
        self, fallback_settings, mock_bedrock, mock_openai
    ) -> None:
        """When primary succeeds, fallback is not called."""
        gateway = _make_gateway(fallback_settings, mock_bedrock, mock_openai)

        result = await gateway.llm_complete("test", correlation_id="c-1")

        assert result["model_id"] == "anthropic.claude-3-5-sonnet"
        mock_bedrock.llm_complete.assert_called_once()
        mock_openai.llm_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_primary_fails_uses_fallback(
        self, fallback_settings, mock_bedrock, mock_openai
    ) -> None:
        """When Bedrock fails, OpenAI fallback should be used."""
        mock_bedrock.llm_complete.side_effect = BedrockTimeoutError(
            model_id="test", timeout_seconds=30, correlation_id="c-1"
        )
        gateway = _make_gateway(fallback_settings, mock_bedrock, mock_openai)

        result = await gateway.llm_complete("test", correlation_id="c-1")

        assert result["model_id"] == "gpt-4o"
        mock_bedrock.llm_complete.assert_called_once()
        mock_openai.llm_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_fail_raises_llm_provider_error(
        self, fallback_settings, mock_bedrock, mock_openai
    ) -> None:
        """When both providers fail, LLMProviderError is raised."""
        mock_bedrock.llm_complete.side_effect = BedrockTimeoutError(
            model_id="test", timeout_seconds=30, correlation_id="c-1"
        )
        mock_openai.llm_complete.side_effect = LLMProviderError(
            provider="openai", message="API down"
        )
        gateway = _make_gateway(fallback_settings, mock_bedrock, mock_openai)

        with pytest.raises(LLMProviderError, match="Both providers failed"):
            await gateway.llm_complete("test", correlation_id="c-1")

    @pytest.mark.asyncio
    async def test_embed_fallback_works(
        self, fallback_settings, mock_bedrock, mock_openai
    ) -> None:
        """Embedding fallback should work when primary fails."""
        mock_bedrock.llm_embed.side_effect = BedrockTimeoutError(
            model_id="titan", timeout_seconds=30, correlation_id="c-1"
        )
        gateway = _make_gateway(fallback_settings, mock_bedrock, mock_openai)

        result = await gateway.llm_embed("test", correlation_id="c-1")

        assert result == [0.2] * 1024
        mock_openai.llm_embed.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_none_when_openai_not_configured(
        self, mock_settings, mock_bedrock
    ) -> None:
        """Fallback mode without OpenAI key falls back to Bedrock only."""
        mock_settings.llm_provider = "bedrock_with_openai_fallback"
        mock_settings.openai_api_key = None
        gateway = _make_gateway(mock_settings, mock_bedrock)

        # Primary (Bedrock) works, no fallback needed
        result = await gateway.llm_complete("test", correlation_id="c-1")
        assert result["model_id"] == "anthropic.claude-3-5-sonnet"


class TestOpenAIWithBedrockFallback:
    """Tests for openai_with_bedrock_fallback mode."""

    @pytest.mark.asyncio
    async def test_openai_primary_bedrock_fallback(
        self, mock_settings, mock_bedrock, mock_openai
    ) -> None:
        """OpenAI primary, Bedrock fallback when OpenAI fails."""
        mock_settings.llm_provider = "openai_with_bedrock_fallback"
        mock_settings.embedding_provider = "openai_with_bedrock_fallback"
        mock_settings.openai_api_key = "sk-test"
        mock_openai.llm_complete.side_effect = LLMProviderError(
            provider="openai", message="Rate limited"
        )
        gateway = _make_gateway(mock_settings, mock_bedrock, mock_openai)

        result = await gateway.llm_complete("test", correlation_id="c-1")

        assert result["model_id"] == "anthropic.claude-3-5-sonnet"
        mock_openai.llm_complete.assert_called_once()
        mock_bedrock.llm_complete.assert_called_once()
