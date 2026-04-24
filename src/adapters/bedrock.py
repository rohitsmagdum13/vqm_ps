"""Module: connectors/bedrock.py

Amazon Bedrock connector for VQMS.

THE single gateway for all LLM inference and embedding calls in the
entire system. No other module calls Bedrock directly — all calls
go through this connector.

Supports:
- LLM inference via Claude Sonnet 3.5 (Messages API format)
- Text embeddings via Titan Embed v2 (1024 dimensions)
- Retry with exponential backoff on transient errors
- Cost tracking per call

Usage:
    from connectors.bedrock import BedrockConnector
    from config import get_settings

    connector = BedrockConnector(get_settings())
    result = await connector.llm_complete("What is 2+2?", correlation_id="abc")
    embedding = await connector.llm_embed("hello world", correlation_id="abc")
"""

from __future__ import annotations

import asyncio
import json
import time

import boto3
import structlog
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import Settings
from utils.decorators import log_llm_call, log_service_call
from utils.exceptions import BedrockTimeoutError

logger = structlog.get_logger(__name__)

# Claude Sonnet 3.5 pricing (USD per 1M tokens)
COST_PER_1M_INPUT_TOKENS = 3.00
COST_PER_1M_OUTPUT_TOKENS = 15.00

# Error codes that warrant a retry
RETRYABLE_ERROR_CODES = frozenset({
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
})


def _is_retryable_bedrock_error(exception: BaseException) -> bool:
    """Check if a ClientError has a retryable error code.

    Bedrock raises botocore ClientError for all API errors.
    We only retry on transient errors (throttling, service
    unavailable, model timeout) — not on validation errors
    or access denied.
    """
    if not isinstance(exception, ClientError):
        return False
    error_code = exception.response.get("Error", {}).get("Code", "")
    return error_code in RETRYABLE_ERROR_CODES


class BedrockConnector:
    """Amazon Bedrock connector for LLM inference and embeddings.

    All LLM calls in VQMS go through this connector. It handles
    the Bedrock InvokeModel API, retry logic, cost calculation,
    and structured logging.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with Bedrock configuration from settings.

        Creates the boto3 bedrock-runtime client. Does NOT make
        any API calls until llm_complete or llm_embed is called.
        """
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.bedrock_region,
            **settings.aws_credentials_kwargs(),
        )
        self._model_id = settings.bedrock_model_id
        self._temperature = settings.bedrock_temperature
        self._max_tokens = settings.bedrock_max_tokens
        self._max_retries = settings.bedrock_max_retries
        self._timeout_seconds = settings.bedrock_timeout_seconds
        self._embedding_model_id = settings.bedrock_embedding_model_id
        self._embedding_dimensions = settings.bedrock_embedding_dimensions

    @log_llm_call
    async def llm_complete(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Invoke Claude Sonnet 3.5 via Bedrock InvokeModel API.

        Args:
            prompt: The user message to send to Claude.
            system_prompt: Optional system prompt for instructions.
            temperature: Override default temperature (0.1 for analysis,
                0.3 for resolution — caller passes explicitly).
            max_tokens: Override default max output tokens (4096).
            correlation_id: Tracing ID for this request.

        Returns:
            Dict with: response_text, tokens_in, tokens_out,
            cost_usd, latency_ms, model_id.

        Raises:
            BedrockTimeoutError: If all retries are exhausted.
        """
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature if temperature is not None else self._temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Only include system if provided — empty string is omitted
        if system_prompt:
            request_body["system"] = system_prompt

        start_time = time.perf_counter()

        try:
            response_body = await self._invoke_with_retry(
                model_id=self._model_id,
                body=json.dumps(request_body),
            )
        except ClientError as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "Bedrock LLM call failed after retries",
                tool="bedrock",
                model_id=self._model_id,
                latency_ms=latency_ms,
                error_code=exc.response.get("Error", {}).get("Code", ""),
                correlation_id=correlation_id,
            )
            raise BedrockTimeoutError(
                model_id=self._model_id,
                timeout_seconds=self._timeout_seconds,
                correlation_id=correlation_id,
            ) from exc

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Parse the Claude Messages API response
        response_text = response_body["content"][0]["text"]
        tokens_in = response_body["usage"]["input_tokens"]
        tokens_out = response_body["usage"]["output_tokens"]
        cost_usd = self._calculate_cost(tokens_in, tokens_out)

        return {
            "response_text": response_text,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost_usd, 6),
            "latency_ms": latency_ms,
            "model_id": self._model_id,
        }

    @log_service_call
    async def llm_embed(
        self,
        text: str,
        *,
        correlation_id: str = "",
    ) -> list[float]:
        """Generate a text embedding via Titan Embed v2.

        Args:
            text: The text to embed.
            correlation_id: Tracing ID for this request.

        Returns:
            List of floats (1024 dimensions).

        Raises:
            BedrockTimeoutError: If all retries are exhausted.
        """
        request_body = {
            "inputText": text,
            "dimensions": self._embedding_dimensions,
            "normalize": True,
        }

        try:
            response_body = await self._invoke_with_retry(
                model_id=self._embedding_model_id,
                body=json.dumps(request_body),
            )
        except ClientError as exc:
            logger.error(
                "Bedrock embedding call failed after retries",
                tool="bedrock",
                model_id=self._embedding_model_id,
                error_code=exc.response.get("Error", {}).get("Code", ""),
                correlation_id=correlation_id,
            )
            raise BedrockTimeoutError(
                model_id=self._embedding_model_id,
                timeout_seconds=self._timeout_seconds,
                correlation_id=correlation_id,
            ) from exc

        return response_body["embedding"]

    async def _invoke_with_retry(self, model_id: str, body: str) -> dict:
        """Call InvokeModel with tenacity retry on transient errors.

        Uses asyncio.to_thread because boto3 is synchronous.
        Retries on ThrottlingException, ServiceUnavailableException,
        and ModelTimeoutException with exponential backoff.
        """

        @retry(
            retry=retry_if_exception(_is_retryable_bedrock_error),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            stop=stop_after_attempt(self._max_retries),
            reraise=True,
        )
        def _sync_invoke() -> dict:
            response = self._client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            return json.loads(response["body"].read())

        return await asyncio.to_thread(_sync_invoke)

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate USD cost for a Claude Sonnet 3.5 call.

        Pricing: $3.00 per 1M input tokens, $15.00 per 1M output tokens.
        """
        input_cost = (tokens_in / 1_000_000) * COST_PER_1M_INPUT_TOKENS
        output_cost = (tokens_out / 1_000_000) * COST_PER_1M_OUTPUT_TOKENS
        return input_cost + output_cost
