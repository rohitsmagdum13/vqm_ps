"""Module: orchestration/nodes/quality_gate.py

Quality Gate Node — Step 11 in the VQMS pipeline.

Every outbound email draft (Path A resolution or Path B acknowledgment)
must pass 7 deterministic checks before being sent to the vendor.
If checks fail, the draft is regenerated up to 2 times. After max
re-drafts, the email is routed to human review.

7 Quality Checks:
1. Ticket number — "PENDING" placeholder is present (real INC-XXXXXXX
   is substituted by the Delivery node after ticket creation)
2. SLA wording — tier-appropriate SLA statement present
3. Required sections — greeting, body, next steps, closing
4. Restricted terms — no internal jargon or competitor names
5. Response length — 50-500 words
6. Source citations — KB article IDs referenced (Path A only)
7. PII scan — stub for Phase 8 (Amazon Comprehend integration)

Corresponds to Step 11 in the VQMS Architecture Document.
"""

from __future__ import annotations

import re

import structlog

from config.settings import Settings
from models.workflow import PipelineState
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# Restricted terms that must NEVER appear in vendor-facing emails
# Internal team names, system names, competitor references
RESTRICTED_TERMS = [
    "internal only",
    "do not share",
    "confidential",
    "jira",
    "slack channel",
    "standup",
    "sprint",
    "backlog",
    "tech debt",
    "workaround",
    "hack",
    "TODO",
    "FIXME",
    "competitor",
]

# Minimum and maximum word count for outbound emails
MIN_WORD_COUNT = 50
MAX_WORD_COUNT = 500

# Number of quality checks executed
TOTAL_CHECKS = 7


class QualityGateNode:
    """Validates every outbound email draft before delivery.

    Runs 7 deterministic checks. If any check fails, the node
    returns the failure details so the orchestrator can decide
    whether to re-draft or route to human review.

    This node does NOT call the LLM for re-drafting — that
    responsibility belongs to the orchestrator or delivery node.
    The QualityGateResult includes the failure details and the
    redraft_count so the caller can decide.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Args:
            settings: Application settings.
        """
        self._settings = settings

    async def execute(self, state: PipelineState) -> PipelineState:
        """Run all 7 quality checks on the draft.

        Args:
            state: Current pipeline state with draft_response.

        Returns:
            Updated state with quality_gate_result dict.
        """
        correlation_id = state.get("correlation_id", "")
        query_id = state.get("query_id", "")
        draft = state.get("draft_response")
        processing_path = state.get("processing_path", "A")

        logger.info(
            "Quality gate validation started",
            step="quality_gate",
            query_id=query_id,
            draft_type=draft.get("draft_type") if draft else None,
            correlation_id=correlation_id,
        )

        # If no draft, fail immediately
        if draft is None:
            logger.error(
                "Quality gate — no draft to validate",
                step="quality_gate",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            gate_result = {
                "passed": False,
                "checks_run": 0,
                "checks_passed": 0,
                "failed_checks": ["no_draft"],
                "redraft_count": 0,
                "max_redrafts": 2,
            }
            return {
                "quality_gate_result": gate_result,
                "status": "DRAFT_REJECTED",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        body = draft.get("body", "")
        draft_type = draft.get("draft_type", "RESOLUTION")
        sources = draft.get("sources", [])

        # Run all 7 checks
        failed_checks: list[str] = []

        # Check 1: Ticket number placeholder present
        if not self._check_ticket_number(body):
            failed_checks.append("ticket_number_missing")

        # Check 2: SLA wording present
        if not self._check_sla_wording(body):
            failed_checks.append("sla_wording_missing")

        # Check 3: Required sections present
        missing_sections = self._check_required_sections(body)
        if missing_sections:
            failed_checks.append(f"missing_sections:{','.join(missing_sections)}")

        # Check 4: Restricted terms scan
        found_terms = self._check_restricted_terms(body)
        if found_terms:
            failed_checks.append(f"restricted_terms:{','.join(found_terms)}")

        # Check 5: Response length (word count)
        word_count = len(body.split())
        if word_count < MIN_WORD_COUNT:
            failed_checks.append(f"too_short:{word_count}_words")
        elif word_count > MAX_WORD_COUNT:
            failed_checks.append(f"too_long:{word_count}_words")

        # Check 6: Source citations (Path A only)
        if processing_path == "A" and draft_type == "RESOLUTION":
            if not sources:
                failed_checks.append("no_source_citations")

        # Check 7: PII scan (stub — Phase 8 will integrate Comprehend)
        pii_found = self._check_pii_stub(body)
        if pii_found:
            failed_checks.append("pii_detected")

        checks_passed = TOTAL_CHECKS - len(failed_checks)
        passed = len(failed_checks) == 0

        gate_result = {
            "passed": passed,
            "checks_run": TOTAL_CHECKS,
            "checks_passed": checks_passed,
            "failed_checks": failed_checks,
            "redraft_count": 0,
            "max_redrafts": 2,
        }

        if passed:
            logger.info(
                "Quality gate passed — all checks OK",
                step="quality_gate",
                query_id=query_id,
                checks_passed=checks_passed,
                correlation_id=correlation_id,
            )
            return {
                "quality_gate_result": gate_result,
                "status": "DELIVERING",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }
        else:
            logger.warning(
                "Quality gate failed",
                step="quality_gate",
                query_id=query_id,
                failed_checks=failed_checks,
                checks_passed=checks_passed,
                correlation_id=correlation_id,
            )
            return {
                "quality_gate_result": gate_result,
                "status": "DRAFT_REJECTED",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

    def _check_ticket_number(self, body: str) -> bool:
        """Check 1: Ticket number placeholder or real INC number present.

        The draft uses "PENDING" as placeholder. Delivery node will
        replace with the real ServiceNow incident number. ServiceNow
        returns the number without a hyphen (INC0010001); older VQMS
        fixtures used a hyphenated form (INC-0010001). Both pass.
        """
        if "PENDING" in body:
            return True
        # Accept both real ServiceNow (INC0010001) and legacy hyphenated
        # (INC-0010001) forms on the post-delivery re-check.
        if re.search(r"INC-?\d{7,}", body):
            return True
        return False

    def _check_sla_wording(self, body: str) -> bool:
        """Check 2: SLA-related wording present in the email.

        Checks for common SLA indicators — tier-specific statements
        or general SLA references.
        """
        sla_keywords = [
            "prioritizing",
            "priority",
            "service agreement",
            "response time",
            "expect",
            "update soon",
            "being processed",
            "being handled",
            "reviewing",
            "actively",
        ]
        body_lower = body.lower()
        return any(keyword in body_lower for keyword in sla_keywords)

    def _check_required_sections(self, body: str) -> list[str]:
        """Check 3: Required email sections present.

        Checks for greeting, body content, next steps, and closing.
        Uses simple heuristics on HTML/text content.
        """
        missing = []
        body_lower = body.lower()

        # Greeting: "dear", "hello", "hi "
        if not any(g in body_lower for g in ["dear ", "hello ", "hi ", "good morning", "good afternoon"]):
            missing.append("greeting")

        # Next steps: some indication of what happens next
        if not any(ns in body_lower for ns in ["next step", "next steps", "if you", "please", "you can"]):
            missing.append("next_steps")

        # Closing: sign-off
        if not any(c in body_lower for c in ["regards", "sincerely", "best", "thank you", "thanks"]):
            missing.append("closing")

        return missing

    def _check_restricted_terms(self, body: str) -> list[str]:
        """Check 4: Scan for restricted terms.

        Returns list of restricted terms found in the body.
        """
        body_lower = body.lower()
        found = []
        for term in RESTRICTED_TERMS:
            if term.lower() in body_lower:
                found.append(term)
        return found

    def _check_pii_stub(self, body: str) -> bool:
        """Check 7: PII detection stub.

        Phase 8 will integrate Amazon Comprehend for real PII detection.
        For now, check for obvious PII patterns:
        - SSN format (XXX-XX-XXXX)
        - Credit card patterns (16 digits)

        Returns True if PII is detected.
        """
        # SSN pattern
        if re.search(r"\b\d{3}-\d{2}-\d{4}\b", body):
            return True

        # Credit card pattern (basic: 16 consecutive digits or groups of 4)
        if re.search(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", body):
            return True

        return False
