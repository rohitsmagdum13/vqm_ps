"""Tests for the OpenAI LLM Connector.

Tests LLM completion, embedding, cost calculation, and error handling.
All OpenAI API calls are mocked via AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.openai_llm import (
    OPENAI_COST_PER_1M_INPUT_TOKENS,
    OPENAI_COST_PER_1M_OUTPUT_TOKENS,
    OpenAIConnector,
)
from utils.exceptions import LLMProviderError


@pytest.fixture
def openai_settings(mock_settings):
    """Settings with OpenAI API key configured."""
    mock_settings.openai_api_key = "sk-test-key-123"
    mock_settings.openai_model_id = "gpt-4o"
    mock_settings.openai_embedding_model_id = "text-embedding-3-small"
    mock_settings.openai_embedding_dimensions = 1024
    mock_settings.openai_max_tokens = 4096
    mock_settings.openai_temperature = 0.1
    mock_settings.openai_api_base_url = "https://api.openai.com/v1"
    return mock_settings


@pytest.fixture
def mock_openai_client():
    """Mock AsyncOpenAI client with chat completions and embeddings."""
    client = AsyncMock()

    # Mock chat completions response
    usage_mock = MagicMock()
    usage_mock.prompt_tokens = 1200
    usage_mock.completion_tokens = 400

    message_mock = MagicMock()
    message_mock.content = '{"intent_classification": "billing", "confidence_score": 0.92}'

    choice_mock = MagicMock()
    choice_mock.message = message_mock

    completion_mock = MagicMock()
    completion_mock.choices = [choice_mock]
    completion_mock.usage = usage_mock

    client.chat.completions.create = AsyncMock(return_value=completion_mock)

    # Mock embeddings response
    embedding_data = MagicMock()
    embedding_data.embedding = [0.1] * 1024

    embedding_response = MagicMock()
    embedding_response.data = [embedding_data]

    client.embeddings.create = AsyncMock(return_value=embedding_response)

    return client


@pytest.fixture
def openai_connector(openai_settings, mock_openai_client):
    """Create OpenAIConnector with mocked client."""
    with patch("adapters.openai_llm.AsyncOpenAI", return_value=mock_openai_client):
        connector = OpenAIConnector(openai_settings)
    # Replace the client with our mock directly
    connector._client = mock_openai_client
    return connector


class TestOpenAIInit:
    """Tests for OpenAI connector initialization."""

    def test_missing_api_key_raises(self, mock_settings) -> None:
        """Missing API key should raise LLMProviderError."""
        mock_settings.openai_api_key = None
        with pytest.raises(LLMProviderError, match="OPENAI_API_KEY"):
            OpenAIConnector(mock_settings)


class TestOpenAILLMComplete:
    """Tests for OpenAI chat completion."""

    @pytest.mark.asyncio
    async def test_success_returns_correct_shape(
        self, openai_connector, mock_openai_client
    ) -> None:
        """Successful call returns dict with expected keys."""
        result = await openai_connector.llm_complete(
            "Test prompt", system_prompt="You are a helper.", correlation_id="test-123"
        )

        assert "response_text" in result
        assert result["tokens_in"] == 1200
        assert result["tokens_out"] == 400
        assert result["model_id"] == "gpt-4o"
        assert result["latency_ms"] >= 0
        assert result["cost_usd"] > 0

    @pytest.mark.asyncio
    async def test_system_prompt_included(
        self, openai_connector, mock_openai_client
    ) -> None:
        """System prompt should be passed as a system message."""
        await openai_connector.llm_complete(
            "Test prompt", system_prompt="Be concise.", correlation_id="test-123"
        )

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        messages = call_kwargs.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be concise."
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_no_system_prompt_omits_system_message(
        self, openai_connector, mock_openai_client
    ) -> None:
        """No system prompt should produce only a user message."""
        await openai_connector.llm_complete("Test prompt", correlation_id="test-123")

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        messages = call_kwargs.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_failure_raises_llm_provider_error(
        self, openai_connector, mock_openai_client
    ) -> None:
        """API failure should raise LLMProviderError."""
        mock_openai_client.chat.completions.create.side_effect = Exception("API down")

        with pytest.raises(LLMProviderError, match="openai"):
            await openai_connector.llm_complete("fail", correlation_id="test-123")


class TestOpenAIEmbed:
    """Tests for OpenAI embeddings."""

    @pytest.mark.asyncio
    async def test_embed_returns_vector(
        self, openai_connector, mock_openai_client
    ) -> None:
        """Successful embed returns 1024-dimension vector."""
        result = await openai_connector.llm_embed("hello world", correlation_id="test-123")

        assert len(result) == 1024
        assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_embed_failure_raises_llm_provider_error(
        self, openai_connector, mock_openai_client
    ) -> None:
        """Embedding failure should raise LLMProviderError."""
        mock_openai_client.embeddings.create.side_effect = Exception("Embed failed")

        with pytest.raises(LLMProviderError, match="openai"):
            await openai_connector.llm_embed("fail", correlation_id="test-123")


class TestOpenAICostCalculation:
    """Tests for cost calculation."""

    def test_cost_1000_tokens(self, openai_connector) -> None:
        """1000 input + 500 output should cost correctly."""
        cost = openai_connector._calculate_cost(1000, 500)

        expected_in = (1000 / 1_000_000) * OPENAI_COST_PER_1M_INPUT_TOKENS
        expected_out = (500 / 1_000_000) * OPENAI_COST_PER_1M_OUTPUT_TOKENS
        assert abs(cost - (expected_in + expected_out)) < 1e-10

    def test_cost_zero_tokens(self, openai_connector) -> None:
        """Zero tokens should cost zero."""
        assert openai_connector._calculate_cost(0, 0) == 0.0
