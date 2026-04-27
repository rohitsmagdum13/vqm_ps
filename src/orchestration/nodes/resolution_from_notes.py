"""Module: orchestration/nodes/resolution_from_notes.py

Resolution-from-Notes Node — Step 15 in the VQMS pipeline (Path B).

Path B's first delivery sends an acknowledgment email only; the human
team then investigates and writes up the resolution in ServiceNow work
notes. When ServiceNow marks the ticket RESOLVED, its webhook re-enters
the graph at this node (via PipelineState.resolution_mode=True).

This node:
  1. Reads the existing ticket_number from state (set during the first
     delivery of the acknowledgment email).
  2. Fetches the team's work_notes from ServiceNow.
  3. Renders resolution_from_notes_v1.j2 with vendor + notes + intent.
  4. Calls the LLM (temperature 0.3) — LLM Call #3 for Path B.
  5. Parses the JSON response into a DraftResponse-shaped dict.
  6. Hands the dict off to the Quality Gate via state["draft_response"].

Corresponds to Step 15 in the VQMS Architecture Document.
"""

from __future__ import annotations

import json
import re
import time

import structlog

from adapters.llm_gateway import LLMGateway
from adapters.servicenow import ServiceNowConnector
from config.settings import Settings
from models.workflow import PipelineState
from orchestration.prompts.prompt_manager import PromptManager
from utils.exceptions import BedrockTimeoutError, LLMProviderError
from utils.helpers import TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)

# Mirrors resolution.py's SLA_STATEMENTS so the vendor-facing copy is
# consistent across Path A resolutions and Path B resolution-from-notes.
SLA_STATEMENTS = {
    "PLATINUM": "Our Platinum team has completed the investigation of your request.",
    "GOLD": "Our Gold-tier team has completed the investigation of your request.",
    "SILVER": "Our team has completed the investigation of your request.",
    "BRONZE": "We have completed the investigation of your request.",
}


class ResolutionFromNotesNode:
    """Drafts a resolution email from human investigation notes (Path B Step 15)."""

    def __init__(
        self,
        llm_gateway: LLMGateway,
        prompt_manager: PromptManager,
        servicenow: ServiceNowConnector,
        settings: Settings,
    ) -> None:
        """Initialize with the dependencies needed to fetch notes + draft.

        Args:
            llm_gateway: LLM gateway for the resolution-from-notes LLM call.
            prompt_manager: PromptManager for rendering the Jinja template.
            servicenow: ServiceNow client — used to fetch work notes by ticket.
            settings: Application settings.
        """
        self._llm = llm_gateway
        self._prompt_manager = prompt_manager
        self._servicenow = servicenow
        self._settings = settings

    async def execute(self, state: PipelineState) -> PipelineState:
        """Fetch work notes, draft the resolution email, update the state."""
        correlation_id = state.get("correlation_id", "")
        query_id = state.get("query_id", "")
        start_time = time.perf_counter()

        ticket_info = state.get("ticket_info") or {}
        ticket_number = ticket_info.get("ticket_number", "")
        if not ticket_number:
            logger.error(
                "Resolution-from-notes missing ticket_number — cannot fetch work notes",
                step="resolution_from_notes",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="resolution_from_notes",
                status="failed",
                details={"error_type": "missing_ticket_number"},
            )
            return {
                "draft_response": None,
                "status": "DRAFT_FAILED",
                "error": "ticket_number missing for resolution-from-notes",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        # Step 1: Fetch work notes from ServiceNow. Non-critical failure
        # means we produce a low-confidence draft the Quality Gate rejects.
        try:
            work_notes = await self._servicenow.get_work_notes(
                ticket_number, correlation_id=correlation_id
            )
        except Exception:
            logger.warning(
                "Failed to fetch ServiceNow work notes — using empty notes",
                step="resolution_from_notes",
                ticket_number=ticket_number,
                correlation_id=correlation_id,
            )
            work_notes = ""

        # Extract context
        vendor_context = state.get("vendor_context") or {}
        analysis_result = state.get("analysis_result") or {}
        payload = state.get("unified_payload") or {}

        vendor_profile = vendor_context.get("vendor_profile", {})
        vendor_name = vendor_profile.get("vendor_name", "Valued Vendor")
        vendor_tier = vendor_profile.get("tier", {}).get("tier_name", "BRONZE")
        sla_statement = SLA_STATEMENTS.get(vendor_tier, SLA_STATEMENTS["BRONZE"])

        # Step 2: Render the prompt with all required variables
        rendered_prompt = self._prompt_manager.render(
            "resolution_from_notes_v1.j2",
            vendor_name=vendor_name,
            vendor_tier=vendor_tier,
            original_query=payload.get("subject", "Vendor Query"),
            intent=analysis_result.get("intent_classification", "general_inquiry"),
            ticket_number=ticket_number,
            sla_statement=sla_statement,
            work_notes=work_notes or "No investigation notes were provided.",
        )

        # Step 3: LLM call + parse. Mirrors resolution.py so output is
        # compatible with the Quality Gate and Delivery nodes.
        draft_data = await self._call_and_parse(
            rendered_prompt, correlation_id, start_time
        )
        if draft_data is None:
            logger.error(
                "Resolution-from-notes draft failed — no valid LLM response",
                step="resolution_from_notes",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="resolution_from_notes",
                status="failed",
                details={
                    "ticket_number": ticket_number,
                    "error_type": "llm_or_parse_failure",
                },
            )
            return {
                "draft_response": None,
                "status": "DRAFT_FAILED",
                "error": "Resolution-from-notes LLM call failed",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        draft_response = {
            "draft_type": "RESOLUTION",
            "subject": draft_data.get("subject", f"Re: Update on {ticket_number}"),
            "body": draft_data.get("body_html", ""),
            "confidence": draft_data.get("confidence", 0.0),
            "sources": draft_data.get("sources", []),
            "model_id": draft_data.get("model_id", "unknown"),
            "tokens_in": draft_data.get("tokens_in", 0),
            "tokens_out": draft_data.get("tokens_out", 0),
            "draft_duration_ms": duration_ms,
        }

        logger.info(
            "Resolution-from-notes draft complete",
            step="resolution_from_notes",
            query_id=query_id,
            ticket_number=ticket_number,
            confidence=draft_response["confidence"],
            work_notes_length=len(work_notes),
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="resolution_from_notes",
            status="success",
            duration_ms=duration_ms,
            details={
                "ticket_number": ticket_number,
                "draft_type": "RESOLUTION",
                "draft_confidence": draft_response["confidence"],
                "work_notes_length": len(work_notes),
                "model_id": draft_response["model_id"],
                "tokens_in": draft_response["tokens_in"],
                "tokens_out": draft_response["tokens_out"],
            },
        )

        return {
            "draft_response": draft_response,
            "work_notes": work_notes,
            "status": "VALIDATING",
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    async def _call_and_parse(
        self, prompt: str, correlation_id: str, start_time: float
    ) -> dict | None:
        """Call LLM and parse the JSON response (mirrors ResolutionNode)."""
        try:
            llm_result = await self._llm.llm_complete(
                prompt=prompt,
                system_prompt=(
                    "You are the Communication Drafting Agent for VQMS. "
                    "Draft a professional resolution email from internal "
                    "investigation notes. Return ONLY valid JSON."
                ),
                temperature=0.3,
                correlation_id=correlation_id,
            )
        except (BedrockTimeoutError, LLMProviderError) as exc:
            logger.error(
                "Resolution-from-notes LLM call failed",
                step="resolution_from_notes",
                error=str(exc),
                correlation_id=correlation_id,
            )
            return None

        raw_response = llm_result["response_text"]
        parsed = self._parse_json_from_response(raw_response)
        if parsed is None:
            logger.warning(
                "Resolution-from-notes JSON parsing failed",
                step="resolution_from_notes",
                raw_length=len(raw_response),
                correlation_id=correlation_id,
            )
            return None

        parsed["model_id"] = llm_result["model_id"]
        parsed["tokens_in"] = llm_result["tokens_in"]
        parsed["tokens_out"] = llm_result["tokens_out"]
        return parsed

    def _parse_json_from_response(self, response_text: str) -> dict | None:
        """Extract JSON from LLM response (raw, markdown fence, or first {...})."""
        text = response_text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None
