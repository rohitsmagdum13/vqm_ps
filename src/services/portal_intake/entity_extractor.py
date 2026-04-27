"""Module: services/portal_intake/entity_extractor.py

LLM-based entity extraction for portal queries.

Renders the entity_extraction_v1 prompt with the subject, description,
and concatenated attachment text, calls the LLM gateway with
temperature=0, parses the JSON response, and validates it against
the ExtractedEntities Pydantic model. On any parse / validation
failure it returns an empty ExtractedEntities so the pipeline does
not stall on a bad LLM response.
"""

from __future__ import annotations

import json
import re

import structlog
from pydantic import ValidationError

from models.query import ExtractedEntities, QueryAttachment, QuerySubmission
from orchestration.prompts.prompt_manager import PromptManager

logger = structlog.get_logger(__name__)

_PROMPT_TEMPLATE = "entity_extraction_v1.j2"
_SYSTEM_PROMPT = (
    "You are a structured-data extractor. Output ONLY valid JSON matching "
    "the schema. Use empty lists for missing fields. Never invent values."
)
# Some LLMs wrap JSON in ```json fences even when told not to. Strip them.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class EntityExtractor:
    """Extracts structured entities from a portal query via the LLM."""

    def __init__(self, llm_gateway: object) -> None:
        """Initialize with the LLM gateway used for the inference call."""
        self._llm_gateway = llm_gateway
        self._prompts = PromptManager()

    async def extract(
        self,
        submission: QuerySubmission,
        attachments: list[QueryAttachment],
        correlation_id: str,
    ) -> ExtractedEntities:
        """Run the LLM entity-extraction call and return the parsed JSON.

        Returns an empty ExtractedEntities when the LLM is unreachable
        or returns malformed JSON — entity extraction is non-critical
        for ingestion, so a failure here must not block the 201.
        """
        attachment_text = self._concatenate_attachment_text(attachments)

        prompt = self._prompts.render(
            _PROMPT_TEMPLATE,
            subject=submission.subject,
            description=submission.description,
            attachment_text=attachment_text,
        )

        try:
            result = await self._llm_gateway.llm_complete(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=2000,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "Entity extraction LLM call failed — returning empty entities",
                correlation_id=correlation_id,
            )
            return ExtractedEntities()

        raw = (result or {}).get("response_text", "")
        return self._parse_response(raw, correlation_id)

    @staticmethod
    def _concatenate_attachment_text(attachments: list[QueryAttachment]) -> str:
        """Join all extracted attachment text with file-name dividers."""
        parts: list[str] = []
        for att in attachments:
            if att.extracted_text:
                parts.append(f"--- {att.filename} ---\n{att.extracted_text}")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_response(raw: str, correlation_id: str) -> ExtractedEntities:
        """Parse the LLM response into ExtractedEntities, tolerantly."""
        if not raw:
            return ExtractedEntities()

        cleaned = _FENCE_RE.sub("", raw).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(
                "Entity extraction returned non-JSON output",
                correlation_id=correlation_id,
                preview=cleaned[:200],
            )
            return ExtractedEntities()

        try:
            return ExtractedEntities.model_validate(data)
        except ValidationError as exc:
            logger.warning(
                "Entity extraction JSON failed schema validation",
                correlation_id=correlation_id,
                error=str(exc),
            )
            return ExtractedEntities()
