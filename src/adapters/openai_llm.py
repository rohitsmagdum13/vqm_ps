"""Module: connectors/openai_llm.py

OpenAI connector for VQMS.

Provides the same interface as BedrockConnector (llm_complete, llm_embed)
so the LLM Gateway can swap between providers transparently. Used as
a fallback when Bedrock is unavailable, or as the primary provider
when llm_provider is set to "openai_only".

Supports:
- LLM inference via GPT-4o (Chat Completions API)
- Text embeddings via text-embedding-3-small (1024 dimensions)
- Retry with exponential backoff on transient errors (429, 500, 502, 503)
- Cost tracking per call

Usage:
    from connectors.openai_llm import OpenAIConnector
    from config.settings import get_settings

    connector = OpenAIConnector(get_settings())
    result = await connector.llm_complete("What is 2+2?", correlation_id="abc")
    embedding = await connector.llm_embed("hello world", correlation_id="abc")
"""

from __future__ import annotations

import time

import structlog
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import Settings
from utils.decorators import log_llm_call, log_service_call
from utils.exceptions import LLMProviderError

logger = structlog.get_logger(__name__)

# GPT-4o pricing (USD per 1M tokens) — as of 2025
OPENAI_COST_PER_1M_INPUT_TOKENS = 2.50
OPENAI_COST_PER_1M_OUTPUT_TOKENS = 10.00

# Transient error types that warrant a retry
RETRYABLE_EXCEPTIONS = (RateLimitError, APIConnectionError, APITimeoutError)


class OpenAIConnector:
    """OpenAI connector for LLM inference and embeddings.

    Same interface as BedrockConnector — llm_complete() and llm_embed()
    return identical dict/list shapes so the LLM Gateway can route
    calls to either provider without the pipeline knowing.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with OpenAI configuration from settings.

        Args:
            settings: Application settings with openai_* fields.

        Raises:
            LLMProviderError: If openai_api_key is not set.
        """
        if not settings.openai_api_key:
            raise LLMProviderError(
                provider="openai",
                message="OPENAI_API_KEY is not set in environment",
            )

        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base_url,
        )
        self._model_id = settings.openai_model_id
        self._temperature = settings.openai_temperature
        self._max_tokens = settings.openai_max_tokens
        self._embedding_model_id = settings.openai_embedding_model_id
        self._embedding_dimensions = settings.openai_embedding_dimensions
        self._max_retries = settings.bedrock_max_retries  # reuse same retry count

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
        """Invoke OpenAI Chat Completions API.

        Same signature and return shape as BedrockConnector.llm_complete().

        Args:
            prompt: The user message to send.
            system_prompt: Optional system prompt for instructions.
            temperature: Override default temperature.
            max_tokens: Override default max output tokens.
            correlation_id: Tracing ID for this request.

        Returns:
            Dict with: response_text, tokens_in, tokens_out,
            cost_usd, latency_ms, model_id.

        Raises:
            LLMProviderError: If all retries are exhausted.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start_time = time.perf_counter()

        try:
            response = await self._chat_with_retry(
                messages=messages,
                temperature=temperature if temperature is not None else self._temperature,
                max_tokens=max_tokens or self._max_tokens,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "OpenAI LLM call failed after retries",
                tool="openai",
                model_id=self._model_id,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
            )
            raise LLMProviderError(
                provider="openai",
                message=f"LLM call failed: {exc}",
                correlation_id=correlation_id,
            ) from exc

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        response_text = response.choices[0].message.content or ""
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0
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
        """Generate a text embedding via OpenAI Embeddings API.

        Same signature and return shape as BedrockConnector.llm_embed().

        Args:
            text: The text to embed.
            correlation_id: Tracing ID for this request.

        Returns:
            List of floats (1024 dimensions by default).

        Raises:
            LLMProviderError: If all retries are exhausted.
        """
        try:
            response = await self._embed_with_retry(text)
        except Exception as exc:
            logger.error(
                "OpenAI embedding call failed after retries",
                tool="openai",
                model_id=self._embedding_model_id,
                correlation_id=correlation_id,
            )
            raise LLMProviderError(
                provider="openai",
                message=f"Embedding call failed: {exc}",
                correlation_id=correlation_id,
            ) from exc

        return response.data[0].embedding

    @retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _chat_with_retry(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ):
        """Call Chat Completions with retry on transient errors."""
        return await self._client.chat.completions.create(
            model=self._model_id,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_tokens,
        )

    @retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _embed_with_retry(self, text: str):
        """Call Embeddings API with retry on transient errors."""
        return await self._client.embeddings.create(
            model=self._embedding_model_id,
            input=text,
            dimensions=self._embedding_dimensions,
        )

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate USD cost for a GPT-4o call.

        Pricing: $2.50 per 1M input tokens, $10.00 per 1M output tokens.
        """
        input_cost = (tokens_in / 1_000_000) * OPENAI_COST_PER_1M_INPUT_TOKENS
        output_cost = (tokens_out / 1_000_000) * OPENAI_COST_PER_1M_OUTPUT_TOKENS
        return input_cost + output_cost
