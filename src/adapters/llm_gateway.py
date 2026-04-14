"""Module: connectors/llm_gateway.py

Unified LLM Gateway for VQMS.

Routes LLM and embedding calls to the configured primary provider
and falls back to the secondary provider on failure. The pipeline
nodes call this gateway instead of BedrockConnector or OpenAIConnector
directly, so provider switching is transparent.

Routing is controlled by two settings:
- llm_provider: which provider to use for inference
- embedding_provider: which provider to use for embeddings

Each supports four modes:
- bedrock_only: Bedrock only, no fallback
- openai_only: OpenAI only, no fallback
- bedrock_with_openai_fallback: Bedrock primary, OpenAI fallback
- openai_with_bedrock_fallback: OpenAI primary, Bedrock fallback

Usage:
    from connectors.llm_gateway import LLMGateway
    gateway = LLMGateway(settings)
    result = await gateway.llm_complete("prompt", correlation_id="abc")
"""

from __future__ import annotations

from typing import Any

import structlog

from config.settings import Settings
from adapters.bedrock import BedrockConnector
from utils.exceptions import BedrockTimeoutError, LLMProviderError

logger = structlog.get_logger(__name__)


class LLMGateway:
    """Unified gateway that routes LLM calls with provider fallback.

    Both llm_complete() and llm_embed() have the same interface as
    BedrockConnector and OpenAIConnector, so pipeline nodes don't
    need to know which provider is handling the call.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with provider configuration from settings.

        Creates the Bedrock connector always (it doesn't need an
        API key — just AWS credentials). Creates the OpenAI connector
        only if openai_api_key is set.

        Args:
            settings: Application settings with llm_provider,
                embedding_provider, and provider-specific config.
        """
        self._settings = settings
        self._llm_provider = settings.llm_provider
        self._embedding_provider = settings.embedding_provider

        # Bedrock is always available (uses AWS credentials from env)
        self._bedrock = BedrockConnector(settings)

        # OpenAI is only available if API key is configured
        self._openai: Any = None
        if settings.openai_api_key:
            # Import here to avoid ImportError when openai package
            # is installed but not needed
            from adapters.openai_llm import OpenAIConnector

            self._openai = OpenAIConnector(settings)

    async def llm_complete(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Route LLM inference to configured provider with fallback.

        Returns the same dict shape regardless of provider:
        {response_text, tokens_in, tokens_out, cost_usd, latency_ms, model_id}

        Args:
            prompt: The user message to send.
            system_prompt: Optional system prompt.
            temperature: Override default temperature.
            max_tokens: Override default max output tokens.
            correlation_id: Tracing ID.

        Returns:
            Dict with response_text, tokens, cost, latency, model_id.

        Raises:
            BedrockTimeoutError: If Bedrock-only mode and Bedrock fails.
            LLMProviderError: If OpenAI-only mode and OpenAI fails,
                or if both providers fail in fallback mode.
        """
        call_kwargs = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "correlation_id": correlation_id,
        }

        primary, fallback = self._get_providers(self._llm_provider)
        return await self._call_with_fallback(
            "llm_complete", primary, fallback, call_kwargs, correlation_id
        )

    async def llm_embed(
        self,
        text: str,
        *,
        correlation_id: str = "",
    ) -> list[float]:
        """Route embedding call to configured provider with fallback.

        Returns the same list[float] shape regardless of provider.

        Args:
            text: The text to embed.
            correlation_id: Tracing ID.

        Returns:
            List of floats (1024 dimensions).

        Raises:
            BedrockTimeoutError: If Bedrock-only mode and Bedrock fails.
            LLMProviderError: If OpenAI-only mode and OpenAI fails,
                or if both providers fail in fallback mode.
        """
        call_kwargs = {"text": text, "correlation_id": correlation_id}

        primary, fallback = self._get_providers(self._embedding_provider)
        return await self._call_with_fallback(
            "llm_embed", primary, fallback, call_kwargs, correlation_id
        )

    async def _call_with_fallback(
        self,
        method_name: str,
        primary: Any,
        fallback: Any | None,
        call_kwargs: dict,
        correlation_id: str,
    ) -> Any:
        """Try primary provider, fall back to secondary on failure.

        Args:
            method_name: "llm_complete" or "llm_embed".
            primary: Primary provider connector.
            fallback: Fallback provider connector (None if no fallback).
            call_kwargs: Arguments to pass to the method.
            correlation_id: Tracing ID.

        Returns:
            Result from whichever provider succeeds.

        Raises:
            The primary provider's exception if no fallback is configured.
        """
        primary_name = self._provider_name(primary)

        try:
            method = getattr(primary, method_name)
            return await method(**call_kwargs)
        except (BedrockTimeoutError, LLMProviderError, Exception) as primary_error:
            if fallback is None:
                # No fallback configured — re-raise
                raise

            fallback_name = self._provider_name(fallback)
            logger.warning(
                f"Primary provider failed — falling back to {fallback_name}",
                tool="llm_gateway",
                primary=primary_name,
                fallback=fallback_name,
                method=method_name,
                error=str(primary_error),
                correlation_id=correlation_id,
            )

            try:
                method = getattr(fallback, method_name)
                return await method(**call_kwargs)
            except Exception as fallback_error:
                logger.error(
                    "Both LLM providers failed",
                    tool="llm_gateway",
                    primary=primary_name,
                    fallback=fallback_name,
                    method=method_name,
                    primary_error=str(primary_error),
                    fallback_error=str(fallback_error),
                    correlation_id=correlation_id,
                )
                # Raise the fallback error — it's the most recent failure
                raise LLMProviderError(
                    provider=f"{primary_name}+{fallback_name}",
                    message=f"Both providers failed. Primary: {primary_error}. Fallback: {fallback_error}",
                    correlation_id=correlation_id,
                ) from fallback_error

    def _get_providers(self, provider_setting: str) -> tuple[Any, Any | None]:
        """Determine primary and fallback providers from setting.

        Args:
            provider_setting: One of bedrock_only, openai_only,
                bedrock_with_openai_fallback, openai_with_bedrock_fallback.

        Returns:
            Tuple of (primary_connector, fallback_connector_or_None).
        """
        if provider_setting == "bedrock_only":
            return self._bedrock, None
        elif provider_setting == "openai_only":
            if self._openai is None:
                raise LLMProviderError(
                    provider="openai",
                    message="OpenAI provider requested but OPENAI_API_KEY is not set",
                )
            return self._openai, None
        elif provider_setting == "bedrock_with_openai_fallback":
            return self._bedrock, self._openai
        elif provider_setting == "openai_with_bedrock_fallback":
            if self._openai is None:
                # OpenAI not configured — fall back to Bedrock-only
                logger.warning(
                    "OpenAI primary requested but not configured — using Bedrock only",
                    tool="llm_gateway",
                )
                return self._bedrock, None
            return self._openai, self._bedrock
        else:
            # Unknown setting — default to Bedrock only
            return self._bedrock, None

    def _provider_name(self, provider: Any) -> str:
        """Return a human-readable name for logging."""
        if provider is self._bedrock:
            return "bedrock"
        elif provider is self._openai:
            return "openai"
        return "unknown"
