"""Tests for the Bedrock connector.

Tests LLM completion, embedding, retry logic, cost calculation,
and error handling with mocked boto3 clients.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from adapters.bedrock import BedrockConnector, _is_retryable_bedrock_error
from utils.exceptions import BedrockTimeoutError


@pytest.fixture
def bedrock_connector(mock_settings) -> BedrockConnector:
    """Create a BedrockConnector with mocked boto3 client."""
    with patch("adapters.bedrock.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        connector = BedrockConnector(mock_settings)
        # Store the mock for test access
        connector._mock_client = mock_client
        return connector


def _make_llm_response(text: str = "Hello", tokens_in: int = 10, tokens_out: int = 5) -> dict:
    """Build a realistic Claude Messages API response body."""
    body_bytes = json.dumps({
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
        "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "stop_reason": "end_turn",
    }).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes
    return {"body": mock_body}


def _make_embed_response(dimensions: int = 1024) -> dict:
    """Build a realistic Titan Embed v2 response body."""
    embedding = [0.1] * dimensions
    body_bytes = json.dumps({"embedding": embedding}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes
    return {"body": mock_body}


def _make_client_error(code: str) -> ClientError:
    """Build a botocore ClientError with a specific error code."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": f"Simulated {code}"}},
        operation_name="InvokeModel",
    )


# ===========================
# Retryable Error Predicate
# ===========================


class TestRetryablePredicate:
    """Tests for _is_retryable_bedrock_error."""

    def test_throttling_is_retryable(self) -> None:
        exc = _make_client_error("ThrottlingException")
        assert _is_retryable_bedrock_error(exc) is True

    def test_service_unavailable_is_retryable(self) -> None:
        exc = _make_client_error("ServiceUnavailableException")
        assert _is_retryable_bedrock_error(exc) is True

    def test_model_timeout_is_retryable(self) -> None:
        exc = _make_client_error("ModelTimeoutException")
        assert _is_retryable_bedrock_error(exc) is True

    def test_access_denied_is_not_retryable(self) -> None:
        exc = _make_client_error("AccessDeniedException")
        assert _is_retryable_bedrock_error(exc) is False

    def test_validation_error_is_not_retryable(self) -> None:
        exc = _make_client_error("ValidationException")
        assert _is_retryable_bedrock_error(exc) is False

    def test_non_client_error_is_not_retryable(self) -> None:
        assert _is_retryable_bedrock_error(ValueError("oops")) is False


# ===========================
# LLM Complete
# ===========================


class TestLLMComplete:
    """Tests for BedrockConnector.llm_complete."""

    @pytest.mark.asyncio
    async def test_successful_call_returns_correct_structure(self, bedrock_connector) -> None:
        """Valid LLM call returns dict with all expected keys."""
        bedrock_connector._mock_client.invoke_model.return_value = _make_llm_response(
            text="The answer is 4.",
            tokens_in=100,
            tokens_out=50,
        )

        result = await bedrock_connector.llm_complete(
            prompt="What is 2+2?",
            system_prompt="You are a math tutor.",
            correlation_id="test-123",
        )

        assert result["response_text"] == "The answer is 4."
        assert result["tokens_in"] == 100
        assert result["tokens_out"] == 50
        assert result["model_id"] == bedrock_connector._model_id
        assert isinstance(result["cost_usd"], float)
        assert isinstance(result["latency_ms"], int)

    @pytest.mark.asyncio
    async def test_request_body_uses_messages_api_format(self, bedrock_connector) -> None:
        """Verify the request body uses Anthropic Messages API format."""
        bedrock_connector._mock_client.invoke_model.return_value = _make_llm_response()

        await bedrock_connector.llm_complete(
            prompt="Hello",
            system_prompt="Be helpful",
            temperature=0.3,
            max_tokens=1000,
            correlation_id="test-123",
        )

        call_args = bedrock_connector._mock_client.invoke_model.call_args
        body = json.loads(call_args[1]["body"])
        assert body["anthropic_version"] == "bedrock-2023-05-31"
        assert body["messages"] == [{"role": "user", "content": "Hello"}]
        assert body["system"] == "Be helpful"
        assert body["temperature"] == 0.3
        assert body["max_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_system_prompt_omitted_when_empty(self, bedrock_connector) -> None:
        """Empty system_prompt should not be included in the request body."""
        bedrock_connector._mock_client.invoke_model.return_value = _make_llm_response()

        await bedrock_connector.llm_complete(
            prompt="Hello",
            correlation_id="test-123",
        )

        call_args = bedrock_connector._mock_client.invoke_model.call_args
        body = json.loads(call_args[1]["body"])
        assert "system" not in body

    @pytest.mark.asyncio
    async def test_retry_on_throttling_then_success(self, bedrock_connector) -> None:
        """First call fails with ThrottlingException, second succeeds."""
        bedrock_connector._mock_client.invoke_model.side_effect = [
            _make_client_error("ThrottlingException"),
            _make_llm_response(text="Retried successfully"),
        ]

        result = await bedrock_connector.llm_complete(
            prompt="Hello",
            correlation_id="test-retry",
        )

        assert result["response_text"] == "Retried successfully"
        assert bedrock_connector._mock_client.invoke_model.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_bedrock_timeout_after_max_retries(self, bedrock_connector) -> None:
        """All retries exhausted raises BedrockTimeoutError."""
        bedrock_connector._mock_client.invoke_model.side_effect = _make_client_error(
            "ThrottlingException"
        )

        with pytest.raises(BedrockTimeoutError) as exc_info:
            await bedrock_connector.llm_complete(
                prompt="Hello",
                correlation_id="test-timeout",
            )

        assert exc_info.value.model_id == bedrock_connector._model_id
        assert exc_info.value.correlation_id == "test-timeout"

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self, bedrock_connector) -> None:
        """AccessDeniedException should not be retried."""
        bedrock_connector._mock_client.invoke_model.side_effect = _make_client_error(
            "AccessDeniedException"
        )

        with pytest.raises(BedrockTimeoutError):
            await bedrock_connector.llm_complete(
                prompt="Hello",
                correlation_id="test-access",
            )

        # Should only be called once — no retries for non-retryable errors
        assert bedrock_connector._mock_client.invoke_model.call_count == 1


# ===========================
# LLM Embed
# ===========================


class TestLLMEmbed:
    """Tests for BedrockConnector.llm_embed."""

    @pytest.mark.asyncio
    async def test_successful_embed_returns_1024_vector(self, bedrock_connector) -> None:
        """Valid embedding call returns a list of 1024 floats."""
        bedrock_connector._mock_client.invoke_model.return_value = _make_embed_response(1024)

        result = await bedrock_connector.llm_embed(
            text="hello world",
            correlation_id="test-embed",
        )

        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_embed_request_body_format(self, bedrock_connector) -> None:
        """Verify the request body uses Titan Embed v2 format."""
        bedrock_connector._mock_client.invoke_model.return_value = _make_embed_response()

        await bedrock_connector.llm_embed(text="test text", correlation_id="test-123")

        call_args = bedrock_connector._mock_client.invoke_model.call_args
        body = json.loads(call_args[1]["body"])
        assert body["inputText"] == "test text"
        assert body["dimensions"] == bedrock_connector._embedding_dimensions
        assert body["normalize"] is True

    @pytest.mark.asyncio
    async def test_embed_retry_on_service_unavailable(self, bedrock_connector) -> None:
        """Embedding retries on ServiceUnavailableException."""
        bedrock_connector._mock_client.invoke_model.side_effect = [
            _make_client_error("ServiceUnavailableException"),
            _make_embed_response(),
        ]

        result = await bedrock_connector.llm_embed(text="hello", correlation_id="test-retry")

        assert len(result) == 1024
        assert bedrock_connector._mock_client.invoke_model.call_count == 2

    @pytest.mark.asyncio
    async def test_embed_raises_timeout_after_max_retries(self, bedrock_connector) -> None:
        """All retries exhausted raises BedrockTimeoutError."""
        bedrock_connector._mock_client.invoke_model.side_effect = _make_client_error(
            "ModelTimeoutException"
        )

        with pytest.raises(BedrockTimeoutError) as exc_info:
            await bedrock_connector.llm_embed(text="hello", correlation_id="test-timeout")

        assert exc_info.value.model_id == bedrock_connector._embedding_model_id


# ===========================
# Cost Calculation
# ===========================


class TestCostCalculation:
    """Tests for _calculate_cost."""

    def test_cost_1000_in_500_out(self, bedrock_connector) -> None:
        """1000 input + 500 output tokens cost calculation."""
        cost = bedrock_connector._calculate_cost(tokens_in=1000, tokens_out=500)
        # (1000/1M)*3.00 + (500/1M)*15.00 = 0.003 + 0.0075 = 0.0105
        assert abs(cost - 0.0105) < 1e-6

    def test_cost_zero_tokens(self, bedrock_connector) -> None:
        """Zero tokens should cost zero."""
        cost = bedrock_connector._calculate_cost(tokens_in=0, tokens_out=0)
        assert cost == 0.0

    def test_cost_reference_scenario(self, bedrock_connector) -> None:
        """Reference: ~1500 in, ~500 out for analysis call ≈ $0.012."""
        cost = bedrock_connector._calculate_cost(tokens_in=1500, tokens_out=500)
        # (1500/1M)*3.00 + (500/1M)*15.00 = 0.0045 + 0.0075 = 0.012
        assert abs(cost - 0.012) < 1e-6
