"""Module: orchestration/nodes/resolution.py

Resolution Node — Step 10A in the VQMS pipeline (Path A only).

When the KB search finds relevant articles with specific facts,
this node drafts a full resolution email using the KB articles
as source material. The Resolution Agent (LLM Call #2) generates
a professional email with the actual answer to the vendor's query.

The draft uses "PENDING" as the ticket number placeholder. The
Delivery node (Step 12) creates the real ticket in ServiceNow,
then replaces "PENDING" with the actual INC-XXXXXXX number before
sending the email.

Corresponds to Step 10A in the VQMS Architecture Document.
"""

from __future__ import annotations

import json
import re
import time

import structlog

from adapters.llm_gateway import LLMGateway
from config.settings import Settings
from models.workflow import PipelineState
from orchestration.prompts.prompt_manager import PromptManager
from utils.exceptions import BedrockTimeoutError, LLMProviderError
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# SLA statement templates by vendor tier
# Delivery node will set real SLA based on routing, but the draft
# needs a human-readable statement for the email body
SLA_STATEMENTS = {
    "PLATINUM": "Our Platinum team is prioritizing your request.",
    "GOLD": "Your request is being handled with Gold-tier priority.",
    "SILVER": "We are handling your request within our standard service agreement.",
    "BRONZE": "We have received your request and it is being processed.",
}


class ResolutionNode:
    """Drafts a full resolution email using KB articles (Path A).

    Uses the Resolution Agent prompt (resolution_v1.j2) with
    vendor context, KB articles, and query details to generate
    a professional email that directly answers the vendor's query.
    """

    def __init__(
        self,
        llm_gateway: LLMGateway,
        prompt_manager: PromptManager,
        settings: Settings,
    ) -> None:
        """Initialize with LLM gateway and prompt manager.

        Args:
            llm_gateway: LLM gateway for inference calls.
            prompt_manager: PromptManager for rendering prompt templates.
            settings: Application settings.
        """
        self._llm = llm_gateway
        self._prompt_manager = prompt_manager
        self._settings = settings

    async def execute(self, state: PipelineState) -> PipelineState:
        """Draft a resolution email using KB articles.

        Reads analysis_result, vendor_context, kb_search_result,
        and routing_decision from state. Renders the resolution
        prompt, calls the LLM, parses the JSON response, and
        returns a DraftResponse dict in the state.

        Args:
            state: Current pipeline state (Path A confirmed).

        Returns:
            Updated state with draft_response dict.
        """
        correlation_id = state.get("correlation_id", "")
        query_id = state.get("query_id", "")
        start_time = time.perf_counter()

        logger.info(
            "Resolution drafting started",
            step="resolution",
            query_id=query_id,
            correlation_id=correlation_id,
        )

        # Extract data from state
        vendor_context = state.get("vendor_context") or {}
        analysis_result = state.get("analysis_result") or {}
        kb_result = state.get("kb_search_result") or {}
        payload = state.get("unified_payload") or {}

        vendor_profile = vendor_context.get("vendor_profile", {})
        vendor_name = vendor_profile.get("vendor_name", "Valued Vendor")
        vendor_tier = vendor_profile.get("tier", {}).get("tier_name", "BRONZE")

        # Build KB articles list for the prompt
        kb_articles = self._format_kb_articles(kb_result)

        # Build entities string from analysis
        entities = analysis_result.get("extracted_entities", {})
        entities_text = json.dumps(entities, indent=2) if entities else "None extracted"

        # SLA statement based on vendor tier
        sla_statement = SLA_STATEMENTS.get(vendor_tier, SLA_STATEMENTS["BRONZE"])

        # Render the resolution prompt
        rendered_prompt = self._prompt_manager.render(
            "resolution_v1.j2",
            vendor_name=vendor_name,
            vendor_tier=vendor_tier,
            original_query=payload.get("subject", "Vendor Query"),
            intent=analysis_result.get("intent_classification", "general_inquiry"),
            entities=entities_text,
            kb_articles=kb_articles,
            ticket_number="PENDING",
            sla_statement=sla_statement,
        )

        # Call the LLM
        draft_data = await self._call_and_parse(
            rendered_prompt, correlation_id, start_time
        )

        if draft_data is None:
            # LLM call or parsing failed — return error state
            # Quality gate will catch this and route to human review
            logger.error(
                "Resolution draft failed — no valid response from LLM",
                step="resolution",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return {
                "draft_response": None,
                "status": "DRAFT_FAILED",
                "error": "Resolution LLM call failed after parsing attempts",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Build the DraftResponse dict (matches models/communication.py)
        draft_response = {
            "draft_type": "RESOLUTION",
            "subject": draft_data.get("subject", "Re: Your Query"),
            "body": draft_data.get("body_html", ""),
            "confidence": draft_data.get("confidence", 0.0),
            "sources": draft_data.get("sources", []),
            "model_id": draft_data.get("model_id", "unknown"),
            "tokens_in": draft_data.get("tokens_in", 0),
            "tokens_out": draft_data.get("tokens_out", 0),
            "draft_duration_ms": duration_ms,
        }

        logger.info(
            "Resolution draft complete",
            step="resolution",
            query_id=query_id,
            confidence=draft_response["confidence"],
            sources_count=len(draft_response["sources"]),
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

        return {
            "draft_response": draft_response,
            "status": "VALIDATING",
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    async def _call_and_parse(
        self, prompt: str, correlation_id: str, start_time: float
    ) -> dict | None:
        """Call LLM and parse the JSON response.

        Follows the same parsing pattern as QueryAnalysisNode:
        try direct parse, markdown fences, then brace extraction.

        Returns:
            Parsed dict with subject, body_html, confidence, sources,
            plus model_id, tokens_in, tokens_out from LLM result.
            None if LLM call or all parsing attempts fail.
        """
        try:
            llm_result = await self._llm.llm_complete(
                prompt=prompt,
                system_prompt=(
                    "You are the Resolution Agent for VQMS. "
                    "Draft a professional email that resolves the vendor's query. "
                    "Return ONLY valid JSON."
                ),
                temperature=0.3,
                correlation_id=correlation_id,
            )
        except (BedrockTimeoutError, LLMProviderError) as exc:
            logger.error(
                "Resolution LLM call failed",
                step="resolution",
                error=str(exc),
                correlation_id=correlation_id,
            )
            return None

        raw_response = llm_result["response_text"]
        parsed = self._parse_json_from_response(raw_response)

        if parsed is None:
            logger.warning(
                "Resolution JSON parsing failed",
                step="resolution",
                raw_length=len(raw_response),
                correlation_id=correlation_id,
            )
            return None

        # Attach LLM metadata to the parsed dict
        parsed["model_id"] = llm_result["model_id"]
        parsed["tokens_in"] = llm_result["tokens_in"]
        parsed["tokens_out"] = llm_result["tokens_out"]
        return parsed

    def _parse_json_from_response(self, response_text: str) -> dict | None:
        """Extract JSON from LLM response.

        Handles three formats:
        1. Raw JSON: { ... }
        2. Markdown fences: ```json\n{ ... }\n```
        3. JSON with preamble text before it
        """
        text = response_text.strip()

        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Markdown fences
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # First { ... } block
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _format_kb_articles(self, kb_result: dict) -> list[dict]:
        """Format KB matches for the prompt template.

        The Jinja2 template expects a list of dicts with
        'title' and 'content_snippet' keys.
        """
        matches = kb_result.get("matches", [])
        articles = []
        for match in matches:
            articles.append({
                "title": match.get("title", "Untitled"),
                "content_snippet": match.get("content_snippet", ""),
                "article_id": match.get("article_id", ""),
            })
        return articles
