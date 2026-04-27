"""Module: orchestration/nodes/acknowledgment.py

Acknowledgment Node — Step 10B in the VQMS pipeline (Path B only).

When the KB search does NOT find sufficient articles to resolve the
query, this node drafts an acknowledgment-only email. The email
confirms receipt, provides the ticket number, states the SLA
commitment, and tells the vendor that a human team is investigating.

IMPORTANT: This node NEVER attempts to answer the query. It only
acknowledges receipt and sets expectations. The human team will
investigate and resolve the ticket in ServiceNow. Once resolved,
Step 15 generates a resolution email from the team's work notes.

Uses "PENDING" as ticket number placeholder — Delivery node (Step 12)
replaces it with the real INC-XXXXXXX after creating the ticket.

Corresponds to Step 10B in the VQMS Architecture Document.
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
from utils.trail import record_node

logger = structlog.get_logger(__name__)

# SLA statement templates by vendor tier (same as resolution node)
SLA_STATEMENTS = {
    "PLATINUM": "Our Platinum team is prioritizing your request.",
    "GOLD": "Your request is being handled with Gold-tier priority.",
    "SILVER": "We are handling your request within our standard service agreement.",
    "BRONZE": "We have received your request and it is being processed.",
}


class AcknowledgmentNode:
    """Drafts an acknowledgment-only email (Path B).

    Does NOT answer the vendor's query. Only confirms receipt,
    provides ticket number, and states SLA commitment.
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
        """Draft an acknowledgment email for Path B.

        Reads vendor_context, analysis_result, and routing_decision
        from state. Renders the acknowledgment prompt, calls the LLM,
        parses the JSON response, and returns a DraftResponse dict.

        Args:
            state: Current pipeline state (Path B confirmed).

        Returns:
            Updated state with draft_response dict.
        """
        correlation_id = state.get("correlation_id", "")
        query_id = state.get("query_id", "")
        start_time = time.perf_counter()

        logger.info(
            "Acknowledgment drafting started",
            step="acknowledgment",
            query_id=query_id,
            correlation_id=correlation_id,
        )

        # Extract data from state
        vendor_context = state.get("vendor_context") or {}
        analysis_result = state.get("analysis_result") or {}
        routing_decision = state.get("routing_decision") or {}
        payload = state.get("unified_payload") or {}

        vendor_profile = vendor_context.get("vendor_profile", {})
        vendor_name = vendor_profile.get("vendor_name", "Valued Vendor")
        vendor_tier = vendor_profile.get("tier", {}).get("tier_name", "BRONZE")

        assigned_team = routing_decision.get("assigned_team", "support team")
        sla_statement = SLA_STATEMENTS.get(vendor_tier, SLA_STATEMENTS["BRONZE"])

        # Render the acknowledgment prompt
        rendered_prompt = self._prompt_manager.render(
            "acknowledgment_v1.j2",
            vendor_name=vendor_name,
            vendor_tier=vendor_tier,
            original_query=payload.get("subject", "Vendor Query"),
            intent=analysis_result.get("intent_classification", "general_inquiry"),
            ticket_number="PENDING",
            sla_statement=sla_statement,
            assigned_team=assigned_team,
        )

        # Call the LLM
        draft_data = await self._call_and_parse(
            rendered_prompt, correlation_id, start_time
        )

        if draft_data is None:
            logger.error(
                "Acknowledgment draft failed — no valid response from LLM",
                step="acknowledgment",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="acknowledgment",
                status="failed",
                details={
                    "draft_type": "ACKNOWLEDGMENT",
                    "error_type": "llm_or_parse_failure",
                },
            )
            return {
                "draft_response": None,
                "status": "DRAFT_FAILED",
                "error": "Acknowledgment LLM call failed after parsing attempts",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Build the DraftResponse dict
        # Path B: sources is always empty (no KB articles used)
        draft_response = {
            "draft_type": "ACKNOWLEDGMENT",
            "subject": draft_data.get("subject", "Re: Your Query"),
            "body": draft_data.get("body_html", ""),
            "confidence": draft_data.get("confidence", 0.0),
            "sources": [],
            "model_id": draft_data.get("model_id", "unknown"),
            "tokens_in": draft_data.get("tokens_in", 0),
            "tokens_out": draft_data.get("tokens_out", 0),
            "draft_duration_ms": duration_ms,
        }

        logger.info(
            "Acknowledgment draft complete",
            step="acknowledgment",
            query_id=query_id,
            confidence=draft_response["confidence"],
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="acknowledgment",
            status="success",
            duration_ms=duration_ms,
            details={
                "draft_type": "ACKNOWLEDGMENT",
                "draft_confidence": draft_response["confidence"],
                "model_id": draft_response["model_id"],
                "tokens_in": draft_response["tokens_in"],
                "tokens_out": draft_response["tokens_out"],
            },
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

        Returns:
            Parsed dict with subject, body_html, confidence, sources,
            plus LLM metadata. None if call or parsing fails.
        """
        try:
            llm_result = await self._llm.llm_complete(
                prompt=prompt,
                system_prompt=(
                    "You are the Communication Drafting Agent for VQMS. "
                    "Draft an acknowledgment-only email. Do NOT answer the query. "
                    "Return ONLY valid JSON."
                ),
                temperature=0.3,
                correlation_id=correlation_id,
            )
        except (BedrockTimeoutError, LLMProviderError) as exc:
            logger.error(
                "Acknowledgment LLM call failed",
                step="acknowledgment",
                error=str(exc),
                correlation_id=correlation_id,
            )
            return None

        raw_response = llm_result["response_text"]
        parsed = self._parse_json_from_response(raw_response)

        if parsed is None:
            logger.warning(
                "Acknowledgment JSON parsing failed",
                step="acknowledgment",
                raw_length=len(raw_response),
                correlation_id=correlation_id,
            )
            return None

        parsed["model_id"] = llm_result["model_id"]
        parsed["tokens_in"] = llm_result["tokens_in"]
        parsed["tokens_out"] = llm_result["tokens_out"]
        return parsed

    def _parse_json_from_response(self, response_text: str) -> dict | None:
        """Extract JSON from LLM response.

        Handles raw JSON, markdown fences, and preamble text.
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
