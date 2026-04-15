"""Tests for QualityGateNode (Step 11).

Tests all 7 quality checks with passing and failing drafts.
"""

from __future__ import annotations

import pytest

from orchestration.nodes.quality_gate import QualityGateNode


# ===========================
# Fixtures
# ===========================


@pytest.fixture
def gate_node(mock_settings) -> QualityGateNode:
    """QualityGateNode with test settings."""
    return QualityGateNode(mock_settings)


def _passing_draft_path_a() -> dict:
    """A draft that passes all 7 checks (Path A resolution)."""
    return {
        "draft_type": "RESOLUTION",
        "subject": "Re: Invoice discrepancy for PO-2026-1234 [PENDING]",
        "body": (
            "Dear TechNova Solutions,\n\n"
            "Thank you for reaching out regarding the invoice discrepancy "
            "for PO-2026-1234. Based on our records, the purchase order was "
            "originally approved for $12,500. The invoice amount of $15,000 "
            "reflects additional work that requires a change order.\n\n"
            "According to our billing policy (KB-001), if the invoice amount "
            "differs from the approved PO, a revised invoice or credit memo "
            "should be issued. The PO amendment procedure (KB-002) allows "
            "vendors to submit a change request referencing the original PO.\n\n"
            "Next Steps:\n"
            "- If a change order was approved, please send us the reference number.\n"
            "- Otherwise, please submit a revised invoice for $12,500.\n\n"
            "Your ticket number is PENDING for reference. "
            "We are handling your request with Gold-tier priority.\n\n"
            "Best regards,\nVendor Support Team"
        ),
        "confidence": 0.89,
        "sources": ["KB-001", "KB-002"],
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 2800,
        "tokens_out": 650,
        "draft_duration_ms": 3200,
    }


def _passing_draft_path_b() -> dict:
    """A draft that passes all checks (Path B acknowledgment)."""
    return {
        "draft_type": "ACKNOWLEDGMENT",
        "subject": "Re: Missing shipment for order ORD-9876 [PENDING]",
        "body": (
            "Dear GlobalParts Inc,\n\n"
            "Thank you for reaching out. We have received your query "
            "regarding the missing shipment for order ORD-9876.\n\n"
            "Your request has been assigned ticket number PENDING and "
            "our logistics-ops team is actively reviewing it. "
            "We are handling your request within our standard service "
            "agreement and you can expect an update soon.\n\n"
            "Next Steps: Our team will investigate the shipment status "
            "and provide you with a detailed update. If you have any "
            "additional information, please reply to this email.\n\n"
            "Best regards,\nVendor Support Team"
        ),
        "confidence": 0.95,
        "sources": [],
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 900,
        "tokens_out": 350,
        "draft_duration_ms": 2100,
    }


def _base_state(draft: dict, path: str = "A") -> dict:
    """Build a pipeline state for quality gate testing."""
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "test-corr-001",
        "draft_response": draft,
        "processing_path": path,
        "status": "VALIDATING",
    }


# ===========================
# Tests: All Checks Pass
# ===========================


class TestQualityGatePassing:
    """Tests where all checks pass."""

    async def test_path_a_draft_passes(self, gate_node) -> None:
        """Valid Path A draft passes all 7 checks."""
        state = _base_state(_passing_draft_path_a(), "A")
        result = await gate_node.execute(state)

        gate = result["quality_gate_result"]
        assert gate["passed"] is True
        assert gate["checks_run"] == 7
        assert gate["checks_passed"] == 7
        assert gate["failed_checks"] == []

    async def test_path_b_draft_passes(self, gate_node) -> None:
        """Valid Path B draft passes all 7 checks."""
        state = _base_state(_passing_draft_path_b(), "B")
        result = await gate_node.execute(state)

        gate = result["quality_gate_result"]
        assert gate["passed"] is True
        assert gate["checks_passed"] == 7

    async def test_status_set_to_delivering(self, gate_node) -> None:
        """Passing gate sets status to DELIVERING."""
        state = _base_state(_passing_draft_path_a(), "A")
        result = await gate_node.execute(state)
        assert result["status"] == "DELIVERING"


# ===========================
# Tests: Check 1 — Ticket Number
# ===========================


class TestTicketNumberCheck:
    """Check 1: Ticket number presence."""

    async def test_missing_ticket_number_fails(self, gate_node) -> None:
        """Draft without PENDING or INC number fails check 1."""
        draft = _passing_draft_path_a()
        draft["body"] = draft["body"].replace("PENDING", "")
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert gate["passed"] is False
        assert any("ticket_number" in f for f in gate["failed_checks"])

    async def test_real_inc_number_passes(self, gate_node) -> None:
        """Draft with real INC-XXXXXXX number passes check 1."""
        draft = _passing_draft_path_a()
        draft["body"] = draft["body"].replace("PENDING", "INC-0000001")
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert "ticket_number_missing" not in gate["failed_checks"]


# ===========================
# Tests: Check 2 — SLA Wording
# ===========================


class TestSLAWordingCheck:
    """Check 2: SLA wording presence."""

    async def test_missing_sla_wording_fails(self, gate_node) -> None:
        """Draft without any SLA wording fails check 2."""
        draft = _passing_draft_path_a()
        # Replace all SLA-related words
        draft["body"] = (
            "Dear Vendor,\n\n"
            "Your ticket is PENDING. "
            "We got your message about the invoice.\n\n"
            "Next steps: send us the documents.\n\n"
            "Best regards,\nTeam "
        ) + " ".join(["word"] * 40)  # pad to meet minimum word count
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert any("sla_wording" in f for f in gate["failed_checks"])


# ===========================
# Tests: Check 3 — Required Sections
# ===========================


class TestRequiredSectionsCheck:
    """Check 3: Greeting, next steps, closing present."""

    async def test_missing_greeting_fails(self, gate_node) -> None:
        """Draft without greeting keyword fails."""
        draft = _passing_draft_path_a()
        draft["body"] = draft["body"].replace("Dear TechNova Solutions", "TechNova Solutions")
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert any("greeting" in f for f in gate["failed_checks"])

    async def test_missing_closing_fails(self, gate_node) -> None:
        """Draft without closing sign-off fails."""
        draft = _passing_draft_path_a()
        # Remove all closing keywords: "regards", "sincerely", "best", "thank you", "thanks"
        draft["body"] = (
            "Dear Vendor,\n\n"
            "Your ticket is PENDING. We are reviewing your invoice discrepancy "
            "for PO-2026-1234 with Gold-tier priority. "
            "According to our billing policy (KB-001), the amounts differ.\n\n"
            "Next steps: Please submit the documents.\n\n"
            "End of message.\nVendor Support Team"
        )
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert any("closing" in f for f in gate["failed_checks"])


# ===========================
# Tests: Check 4 — Restricted Terms
# ===========================


class TestRestrictedTermsCheck:
    """Check 4: No restricted/internal terms."""

    async def test_restricted_term_detected(self, gate_node) -> None:
        """Draft containing 'internal only' fails check 4."""
        draft = _passing_draft_path_a()
        draft["body"] = draft["body"].replace(
            "Best regards", "This is internal only. Best regards"
        )
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert any("restricted_terms" in f for f in gate["failed_checks"])

    async def test_jira_reference_detected(self, gate_node) -> None:
        """Draft mentioning 'Jira' fails check 4."""
        draft = _passing_draft_path_a()
        draft["body"] = draft["body"].replace(
            "Best regards", "See Jira ticket for details. Best regards"
        )
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert any("restricted_terms" in f for f in gate["failed_checks"])


# ===========================
# Tests: Check 5 — Word Count
# ===========================


class TestWordCountCheck:
    """Check 5: Response length between 50-500 words."""

    async def test_too_short_fails(self, gate_node) -> None:
        """Draft with fewer than 50 words fails."""
        draft = _passing_draft_path_a()
        draft["body"] = "Dear Vendor, PENDING ticket. Best regards."
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert any("too_short" in f for f in gate["failed_checks"])

    async def test_too_long_fails(self, gate_node) -> None:
        """Draft with more than 500 words fails."""
        draft = _passing_draft_path_a()
        # Generate 600 words
        draft["body"] = "Dear Vendor, PENDING. " + " ".join(["word"] * 600) + " Next steps: do it. Best regards."
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert any("too_long" in f for f in gate["failed_checks"])


# ===========================
# Tests: Check 6 — Source Citations (Path A)
# ===========================


class TestSourceCitationsCheck:
    """Check 6: Source citations required for Path A only."""

    async def test_path_a_no_sources_fails(self, gate_node) -> None:
        """Path A draft without source citations fails."""
        draft = _passing_draft_path_a()
        draft["sources"] = []
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert "no_source_citations" in gate["failed_checks"]

    async def test_path_b_no_sources_ok(self, gate_node) -> None:
        """Path B draft without sources passes (expected)."""
        draft = _passing_draft_path_b()
        assert draft["sources"] == []
        state = _base_state(draft, "B")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert "no_source_citations" not in gate["failed_checks"]


# ===========================
# Tests: Check 7 — PII Stub
# ===========================


class TestPIICheck:
    """Check 7: PII detection (stub)."""

    async def test_ssn_detected(self, gate_node) -> None:
        """SSN pattern in body triggers PII check failure."""
        draft = _passing_draft_path_a()
        draft["body"] = draft["body"].replace(
            "Best regards", "SSN: 123-45-6789. Best regards"
        )
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert "pii_detected" in gate["failed_checks"]

    async def test_credit_card_detected(self, gate_node) -> None:
        """Credit card number in body triggers PII check."""
        draft = _passing_draft_path_a()
        draft["body"] = draft["body"].replace(
            "Best regards", "Card: 4111 1111 1111 1111. Best regards"
        )
        state = _base_state(draft, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert "pii_detected" in gate["failed_checks"]


# ===========================
# Tests: No Draft
# ===========================


class TestNoDraft:
    """Tests for missing draft."""

    async def test_no_draft_fails_immediately(self, gate_node) -> None:
        """None draft returns immediate failure."""
        state = _base_state(None, "A")

        result = await gate_node.execute(state)
        gate = result["quality_gate_result"]
        assert gate["passed"] is False
        assert gate["checks_run"] == 0
        assert "no_draft" in gate["failed_checks"]

    async def test_no_draft_sets_rejected_status(self, gate_node) -> None:
        """None draft sets DRAFT_REJECTED status."""
        state = _base_state(None, "A")
        result = await gate_node.execute(state)
        assert result["status"] == "DRAFT_REJECTED"
