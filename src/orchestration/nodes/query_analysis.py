"""Module: orchestration/nodes/query_analysis.py

Query Analysis Node — Step 8 in the VQMS pipeline.

THE most critical node in the system. Every vendor query passes
through this node. Implements an 8-layer defense strategy to ensure
the system never crashes — it always produces a result, even if
that result routes to human review (Path C).

8-Layer Defense:
1. Input Validation — catch bad/empty data before calling LLM
2. Prompt Engineering — structured prompt with explicit JSON schema
3. LLM Call with Retry — handled by BedrockConnector
4. Output Parsing — extract JSON, handle markdown fences
5. Pydantic Validation — enforce schema and value ranges
6. Self-Correction — ask Claude to fix its own response (1 retry)
7. Safe Fallback — low-confidence result that routes to Path C
8. Audit and Monitoring — log everything for LLM audit trail

Corresponds to Step 8 in the VQMS Architecture Document.
"""

from __future__ import annotations

import json
import re
import time

import structlog

from config.settings import Settings
from adapters.llm_gateway import LLMGateway
from models.workflow import AnalysisResult
from models.workflow import PipelineState
from orchestration.prompts.prompt_manager import PromptManager
from utils.exceptions import BedrockTimeoutError, LLMProviderError
from utils.helpers import TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)

# Maximum body length sent to the LLM to prevent token overflow
MAX_BODY_LENGTH = 10_000

# Maximum attachment text length
MAX_ATTACHMENT_TEXT_LENGTH = 5_000


class QueryAnalysisNode:
    """Analyzes vendor queries using Claude via Bedrock.

    Produces an AnalysisResult with intent classification, entity
    extraction, urgency, sentiment, and confidence score. The
    confidence score determines the processing path:
    - >= 0.85: continue to routing + KB search
    - < 0.85: route to Path C (human review)
    """

    def __init__(
        self,
        bedrock: LLMGateway,
        prompt_manager: PromptManager,
        settings: Settings,
    ) -> None:
        """Initialize with LLM gateway and prompt manager.

        Args:
            bedrock: LLM gateway for inference calls (Bedrock primary, OpenAI fallback).
            prompt_manager: PromptManager for rendering prompt templates.
            settings: Application settings.
        """
        self._bedrock = bedrock
        self._prompt_manager = prompt_manager
        self._settings = settings

    async def execute(self, state: PipelineState) -> PipelineState:
        """Analyze the vendor query and produce an AnalysisResult.

        Implements the 8-layer defense strategy. Always returns
        a valid state update — never raises exceptions to the graph.

        Args:
            state: Current pipeline state with unified_payload.

        Returns:
            Updated state with analysis_result dict.
        """
        correlation_id = state.get("correlation_id", "")
        payload = state.get("unified_payload", {})
        start_time = time.perf_counter()

        logger.info(
            "Query analysis started",
            step="query_analysis",
            query_id=state.get("query_id", ""),
            correlation_id=correlation_id,
        )

        # Layer 1: Input Validation
        query_body = payload.get("body", "")
        query_subject = payload.get("subject", "")

        if not query_body and not query_subject:
            logger.warning(
                "Empty query body and subject — using safe fallback",
                step="query_analysis",
                layer="input_validation",
                correlation_id=correlation_id,
            )
            return self._safe_fallback_state(start_time, "empty_input")

        # Truncate to prevent token overflow
        if len(query_body) > MAX_BODY_LENGTH:
            query_body = query_body[:MAX_BODY_LENGTH]

        # Build attachment text
        attachment_text = self._extract_attachment_text(payload)

        # Layer 2: Prompt Engineering
        vendor_context = state.get("vendor_context") or {}
        vendor_profile = vendor_context.get("vendor_profile", {})
        recent_interactions = vendor_context.get("recent_interactions", [])

        rendered_prompt = self._prompt_manager.render(
            "query_analysis_v1.j2",
            vendor_name=vendor_profile.get("vendor_name", "Unknown"),
            vendor_tier=vendor_profile.get("tier", {}).get("tier_name", "BRONZE"),
            query_subject=query_subject,
            query_body=query_body,
            attachment_text=attachment_text,
            recent_interactions=recent_interactions,
            query_source=payload.get("source", "unknown"),
        )

        # Layers 3-6: LLM Call → Parse → Validate → Self-Correct
        analysis_result = await self._call_and_parse(
            rendered_prompt, correlation_id, start_time
        )

        logger.info(
            "Query analysis complete",
            step="query_analysis",
            intent=analysis_result.intent_classification,
            confidence=analysis_result.confidence_score,
            urgency=analysis_result.urgency_level,
            layer="success",
            correlation_id=correlation_id,
        )

        await record_node(
            query_id=state.get("query_id", ""),
            correlation_id=correlation_id,
            step_name="query_analysis",
            status="success",
            duration_ms=analysis_result.analysis_duration_ms,
            details={
                "intent": analysis_result.intent_classification,
                "urgency": analysis_result.urgency_level,
                "sentiment": analysis_result.sentiment,
                "confidence_score": analysis_result.confidence_score,
                "suggested_category": analysis_result.suggested_category,
                "multi_issue_detected": analysis_result.multi_issue_detected,
                "model_id": analysis_result.model_id,
                "tokens_in": analysis_result.tokens_in,
                "tokens_out": analysis_result.tokens_out,
            },
        )

        return {
            "analysis_result": analysis_result.model_dump(),
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    async def _call_and_parse(
        self, prompt: str, correlation_id: str, start_time: float
    ) -> AnalysisResult:
        """Execute layers 3-7: LLM call, parse, validate, self-correct, fallback.

        Returns a valid AnalysisResult in ALL cases — never raises.
        """
        # Layer 3: LLM Call
        try:
            llm_result = await self._bedrock.llm_complete(
                prompt=prompt,
                system_prompt="You are the Query Analysis Agent for VQMS. Return only valid JSON.",
                temperature=0.1,
                correlation_id=correlation_id,
            )
        except (BedrockTimeoutError, LLMProviderError) as exc:
            logger.error(
                "LLM call failed — using safe fallback",
                step="query_analysis",
                layer="llm_call",
                error=str(exc),
                correlation_id=correlation_id,
            )
            return self._safe_fallback(start_time, "llm_call_failed")

        raw_response = llm_result["response_text"]
        tokens_in = llm_result["tokens_in"]
        tokens_out = llm_result["tokens_out"]
        model_id = llm_result["model_id"]

        # Layer 4: Output Parsing
        parsed = self._parse_json_from_response(raw_response)
        if parsed is None:
            # Layer 6: Self-Correction (1 attempt)
            logger.warning(
                "JSON parsing failed — attempting self-correction",
                step="query_analysis",
                layer="output_parsing",
                correlation_id=correlation_id,
            )
            corrected = await self._self_correct(
                raw_response, "Failed to parse JSON from response", correlation_id
            )
            if corrected is not None:
                parsed = corrected
            else:
                return self._safe_fallback(start_time, "parse_failed")

        # Layer 5: Pydantic Validation
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        try:
            analysis_result = AnalysisResult(
                intent_classification=parsed.get("intent_classification", "UNKNOWN"),
                extracted_entities=parsed.get("extracted_entities", {}),
                urgency_level=parsed.get("urgency_level", "MEDIUM"),
                sentiment=parsed.get("sentiment", "NEUTRAL"),
                confidence_score=parsed.get("confidence_score", 0.3),
                multi_issue_detected=parsed.get("multi_issue_detected", False),
                suggested_category=parsed.get("suggested_category", "general"),
                analysis_duration_ms=duration_ms,
                model_id=model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            return analysis_result
        except Exception as exc:
            # Layer 6: Self-Correction for validation errors
            logger.warning(
                "Pydantic validation failed — attempting self-correction",
                step="query_analysis",
                layer="pydantic_validation",
                error=str(exc),
                correlation_id=correlation_id,
            )
            corrected = await self._self_correct(
                raw_response, f"Pydantic validation error: {exc}", correlation_id
            )
            if corrected is not None:
                try:
                    return AnalysisResult(
                        **corrected,
                        analysis_duration_ms=duration_ms,
                        model_id=model_id,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                except Exception:
                    pass

            # Layer 7: Safe Fallback
            return self._safe_fallback(start_time, "validation_failed")

    async def _self_correct(
        self, raw_response: str, error_message: str, correlation_id: str
    ) -> dict | None:
        """Ask Claude to fix its own response (Layer 6).

        Sends the error and original response back to Claude with
        instructions to fix the output. Returns parsed dict on
        success, None on failure.
        """
        correction_prompt = (
            f"Your previous response had the following error:\n"
            f"{error_message}\n\n"
            f"Your original response was:\n"
            f"{raw_response}\n\n"
            f"Please fix and return ONLY a valid JSON object with these fields:\n"
            f"intent_classification (string), extracted_entities (dict), "
            f"urgency_level (LOW/MEDIUM/HIGH/CRITICAL), "
            f"sentiment (POSITIVE/NEUTRAL/NEGATIVE/FRUSTRATED), "
            f"confidence_score (float 0.0-1.0), "
            f"multi_issue_detected (bool), suggested_category (string).\n"
            f"Return ONLY the JSON. No explanation."
        )

        try:
            correction_result = await self._bedrock.llm_complete(
                prompt=correction_prompt,
                system_prompt="Fix the JSON output. Return ONLY valid JSON.",
                temperature=0.0,
                correlation_id=correlation_id,
            )
            parsed = self._parse_json_from_response(correction_result["response_text"])
            if parsed is not None:
                logger.info(
                    "Self-correction succeeded",
                    step="query_analysis",
                    layer="self_correction",
                    correlation_id=correlation_id,
                )
            return parsed
        except Exception:
            logger.warning(
                "Self-correction failed",
                step="query_analysis",
                layer="self_correction",
                correlation_id=correlation_id,
            )
            return None

    def _parse_json_from_response(self, response_text: str) -> dict | None:
        """Extract and parse JSON from LLM response text.

        Handles three common formats:
        1. Raw JSON: { ... }
        2. JSON in markdown fences: ```json\n{ ... }\n```
        3. JSON with preamble: "Here is the analysis:\n{ ... }"
        """
        text = response_text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try removing markdown fences
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try extracting first { ... } block
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _extract_attachment_text(self, payload: dict) -> str:
        """Concatenate extracted text from all attachments."""
        attachments = payload.get("attachments", [])
        texts = []
        for att in attachments:
            extracted = att.get("extracted_text") or ""
            if extracted:
                texts.append(f"[{att.get('filename', 'attachment')}]: {extracted}")

        combined = "\n\n".join(texts)
        if len(combined) > MAX_ATTACHMENT_TEXT_LENGTH:
            combined = combined[:MAX_ATTACHMENT_TEXT_LENGTH]
        return combined

    def _safe_fallback(self, start_time: float, reason: str) -> AnalysisResult:
        """Create a low-confidence AnalysisResult (Layer 7).

        This ALWAYS routes to Path C (confidence < 0.85),
        ensuring the system never crashes — it always falls
        back to human review.
        """
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.warning(
            "Using safe fallback AnalysisResult",
            step="query_analysis",
            layer="safe_fallback",
            reason=reason,
        )
        return AnalysisResult(
            intent_classification="UNKNOWN",
            extracted_entities={},
            urgency_level="MEDIUM",
            sentiment="NEUTRAL",
            confidence_score=0.3,
            multi_issue_detected=False,
            suggested_category="general",
            analysis_duration_ms=duration_ms,
            model_id="fallback",
            tokens_in=0,
            tokens_out=0,
        )

    def _safe_fallback_state(self, start_time: float, reason: str) -> dict:
        """Return a complete state update with safe fallback analysis."""
        fallback = self._safe_fallback(start_time, reason)
        return {
            "analysis_result": fallback.model_dump(),
            "updated_at": TimeHelper.ist_now().isoformat(),
        }
