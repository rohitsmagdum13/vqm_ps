"""Tests for ResolutionFromNotesNode (Path B — Step 15).

Covers:
- Happy path: valid work notes + valid LLM JSON → DraftResponse with VALIDATING
- Missing ticket_number → early return DRAFT_FAILED, no ServiceNow or LLM call
- ServiceNow get_work_notes failure → draft still produced with empty notes
- LLM timeout → DRAFT_FAILED
- Malformed LLM JSON → DRAFT_FAILED
- work_notes preserved in output state
- Rendered prompt includes vendor name, ticket number, and tier-based SLA
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestration.nodes.resolution_from_notes import ResolutionFromNotesNode
from orchestration.prompts.prompt_manager import PromptManager
from utils.exceptions import BedrockTimeoutError


# ===========================
# Fixtures
# ===========================


@pytest.fixture
def prompt_manager() -> PromptManager:
    """Real PromptManager that loads the Jinja2 template."""
    return PromptManager()


@pytest.fixture
def mock_llm() -> AsyncMock:
    """Mock LLM gateway with a default valid resolution-from-notes response."""
    llm = AsyncMock()
    llm.llm_complete.return_value = {
        "response_text": _sample_llm_response(),
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 2100,
        "tokens_out": 620,
        "cost_usd": 0.019,
        "latency_ms": 3100,
    }
    return llm


@pytest.fixture
def mock_servicenow() -> AsyncMock:
    """Mock ServiceNow connector that returns realistic work notes."""
    snow = AsyncMock()
    snow.get_work_notes.return_value = (
        "2026-04-18 10:15 [finance-ops] Verified invoice INV-5678 against "
        "PO-2026-1234. Amounts differ by $2,500 (scope expansion approved "
        "in change order CO-0042). Credit memo CM-0077 issued to vendor; "
        "revised invoice should reference PO-2026-1234 + CO-0042."
    )
    return snow


@pytest.fixture
def resolution_from_notes_node(
    mock_llm: AsyncMock,
    prompt_manager: PromptManager,
    mock_servicenow: AsyncMock,
    mock_settings,
) -> ResolutionFromNotesNode:
    """Node under test with mocked LLM, real PromptManager, mocked ServiceNow."""
    return ResolutionFromNotesNode(
        mock_llm, prompt_manager, mock_servicenow, mock_settings
    )


@pytest.fixture
def pipeline_state_resolution() -> dict:
    """Pipeline state re-entering the graph for Path B Step 15."""
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "test-corr-015",
        "execution_id": "exec-015",
        "source": "email",
        "resolution_mode": True,
        "unified_payload": {
            "subject": "Invoice discrepancy for PO-2026-1234",
            "body": "We noticed a mismatch between invoice and PO amounts.",
        },
        "vendor_context": {
            "vendor_profile": {
                "vendor_id": "V-001",
                "vendor_name": "TechNova Solutions",
                "tier": {"tier_name": "GOLD"},
            }
        },
        "analysis_result": {
            "intent_classification": "invoice_discrepancy",
        },
        "ticket_info": {
            "ticket_number": "INC1234567",
        },
        "status": "DRAFTING",
    }


def _sample_llm_response() -> str:
    """Realistic LLM JSON for a resolution drafted from team notes."""
    return """{
  "subject": "Re: Invoice discrepancy for PO-2026-1234 [INC1234567]",
  "body_html": "<html><body><p>Dear TechNova Solutions,</p><p>Thank you for your patience while our team reviewed the invoice discrepancy for PO-2026-1234.</p><p>Our investigation confirmed that the $2,500 difference on invoice INV-5678 reflects approved additional scope. We have issued credit memo CM-0077. Please submit a revised invoice referencing PO-2026-1234 and change order CO-0042.</p><p>Reference ticket: INC1234567</p><p>Best regards,<br>Vendor Support Team</p></body></html>",
  "confidence": 0.91,
  "sources": ["team-notes"]
}"""


# ===========================
# Tests: Happy Path
# ===========================


class TestResolutionFromNotesHappyPath:
    """Valid work notes + valid LLM response produces a DraftResponse."""

    async def test_returns_draft_response(
        self, resolution_from_notes_node, pipeline_state_resolution
    ) -> None:
        """Successful draft returns a RESOLUTION DraftResponse dict."""
        result = await resolution_from_notes_node.execute(pipeline_state_resolution)

        draft = result["draft_response"]
        assert draft is not None
        assert draft["draft_type"] == "RESOLUTION"
        assert draft["confidence"] == 0.91
        assert "INC1234567" in draft["subject"]

    async def test_status_transitions_to_validating(
        self, resolution_from_notes_node, pipeline_state_resolution
    ) -> None:
        """Status moves to VALIDATING so Quality Gate can pick it up."""
        result = await resolution_from_notes_node.execute(pipeline_state_resolution)
        assert result["status"] == "VALIDATING"

    async def test_work_notes_preserved_in_output(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_servicenow
    ) -> None:
        """Fetched work_notes make it into the output state unchanged."""
        result = await resolution_from_notes_node.execute(pipeline_state_resolution)
        assert (
            result["work_notes"]
            == mock_servicenow.get_work_notes.return_value
        )

    async def test_draft_includes_model_metadata(
        self, resolution_from_notes_node, pipeline_state_resolution
    ) -> None:
        """Draft carries through the LLM token counts and model id."""
        result = await resolution_from_notes_node.execute(pipeline_state_resolution)

        draft = result["draft_response"]
        assert draft["model_id"] == "anthropic.claude-3-5-sonnet"
        assert draft["tokens_in"] == 2100
        assert draft["tokens_out"] == 620
        assert draft["draft_duration_ms"] >= 0

    async def test_llm_called_with_temperature_03(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """Resolution-from-notes uses temperature 0.3, same as Path A."""
        await resolution_from_notes_node.execute(pipeline_state_resolution)

        call_args = mock_llm.llm_complete.call_args
        assert call_args.kwargs["temperature"] == 0.3


# ===========================
# Tests: Prompt Rendering
# ===========================


class TestResolutionFromNotesPrompt:
    """The rendered prompt includes all required vendor + ticket context."""

    async def test_prompt_includes_vendor_name(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """Prompt includes the vendor name for the greeting."""
        await resolution_from_notes_node.execute(pipeline_state_resolution)

        prompt = mock_llm.llm_complete.call_args.kwargs["prompt"]
        assert "TechNova Solutions" in prompt

    async def test_prompt_includes_ticket_number(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """Prompt includes the existing ticket_number from state."""
        await resolution_from_notes_node.execute(pipeline_state_resolution)

        prompt = mock_llm.llm_complete.call_args.kwargs["prompt"]
        assert "INC1234567" in prompt

    async def test_prompt_includes_work_notes(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """Prompt carries the team's work notes as context."""
        await resolution_from_notes_node.execute(pipeline_state_resolution)

        prompt = mock_llm.llm_complete.call_args.kwargs["prompt"]
        assert "Credit memo CM-0077" in prompt

    async def test_prompt_uses_gold_tier_sla_statement(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """GOLD-tier vendor gets the Gold-tier SLA statement."""
        await resolution_from_notes_node.execute(pipeline_state_resolution)

        prompt = mock_llm.llm_complete.call_args.kwargs["prompt"]
        assert "Gold-tier team" in prompt


# ===========================
# Tests: ServiceNow Failure
# ===========================


class TestResolutionFromNotesServiceNowFailure:
    """ServiceNow is non-critical — failure uses empty notes and continues."""

    async def test_servicenow_failure_uses_empty_notes(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_servicenow
    ) -> None:
        """A get_work_notes exception is swallowed; draft still produced."""
        mock_servicenow.get_work_notes.side_effect = RuntimeError(
            "ServiceNow unreachable"
        )

        result = await resolution_from_notes_node.execute(pipeline_state_resolution)

        # Draft still produced because LLM was given the fallback text
        assert result["draft_response"] is not None
        assert result["status"] == "VALIDATING"
        # work_notes preserved as empty string (what was handed to the LLM)
        assert result["work_notes"] == ""

    async def test_servicenow_failure_passes_fallback_to_llm(
        self,
        resolution_from_notes_node,
        pipeline_state_resolution,
        mock_servicenow,
        mock_llm,
    ) -> None:
        """Empty notes → prompt still renders with the fallback placeholder."""
        mock_servicenow.get_work_notes.side_effect = RuntimeError("down")

        await resolution_from_notes_node.execute(pipeline_state_resolution)

        prompt = mock_llm.llm_complete.call_args.kwargs["prompt"]
        assert "No investigation notes were provided" in prompt


# ===========================
# Tests: LLM Failure
# ===========================


class TestResolutionFromNotesLLMFailure:
    """LLM timeouts and malformed JSON produce DRAFT_FAILED."""

    async def test_llm_timeout_returns_draft_failed(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """BedrockTimeoutError → DRAFT_FAILED, no draft_response."""
        mock_llm.llm_complete.side_effect = BedrockTimeoutError("test-model", 30.0)

        result = await resolution_from_notes_node.execute(pipeline_state_resolution)

        assert result["draft_response"] is None
        assert result["status"] == "DRAFT_FAILED"

    async def test_malformed_json_returns_draft_failed(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """Unparseable LLM response → DRAFT_FAILED."""
        mock_llm.llm_complete.return_value = {
            "response_text": "not json at all, just plain prose",
            "model_id": "test-model",
            "tokens_in": 100,
            "tokens_out": 20,
            "cost_usd": 0.001,
            "latency_ms": 400,
        }

        result = await resolution_from_notes_node.execute(pipeline_state_resolution)

        assert result["draft_response"] is None
        assert result["status"] == "DRAFT_FAILED"

    async def test_malformed_json_error_message_set(
        self, resolution_from_notes_node, pipeline_state_resolution, mock_llm
    ) -> None:
        """DRAFT_FAILED result includes a human-readable error string."""
        mock_llm.llm_complete.return_value = {
            "response_text": "",
            "model_id": "test",
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "latency_ms": 10,
        }

        result = await resolution_from_notes_node.execute(pipeline_state_resolution)

        assert "error" in result
        assert result["error"]


# ===========================
# Tests: Missing Ticket Number
# ===========================


class TestResolutionFromNotesMissingTicket:
    """Without a ticket_number we can't fetch notes — early exit."""

    async def test_missing_ticket_number_returns_draft_failed(
        self, resolution_from_notes_node, pipeline_state_resolution
    ) -> None:
        """Missing ticket_info entirely → DRAFT_FAILED without LLM call."""
        pipeline_state_resolution["ticket_info"] = {}

        result = await resolution_from_notes_node.execute(pipeline_state_resolution)

        assert result["draft_response"] is None
        assert result["status"] == "DRAFT_FAILED"
        assert "ticket_number" in result["error"]

    async def test_missing_ticket_skips_servicenow_and_llm(
        self,
        resolution_from_notes_node,
        pipeline_state_resolution,
        mock_servicenow,
        mock_llm,
    ) -> None:
        """Early return means no ServiceNow fetch and no LLM call."""
        pipeline_state_resolution["ticket_info"] = {}

        await resolution_from_notes_node.execute(pipeline_state_resolution)

        mock_servicenow.get_work_notes.assert_not_called()
        mock_llm.llm_complete.assert_not_called()
