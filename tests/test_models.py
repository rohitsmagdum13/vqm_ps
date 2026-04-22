"""Tests for all VQMS Pydantic models.

Verifies that models accept valid data, reject invalid data,
and enforce immutability (frozen=True).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from models.workflow import AnalysisResult
from models.communication import DraftResponse, QualityGateResult
from models.email import EmailAttachment, ParsedEmailPayload
from models.memory import KBArticleMatch, KBSearchResult
from models.memory import EpisodicMemoryEntry, VendorContext
from models.workflow import PipelineState
from models.query import QuerySubmission, UnifiedQueryPayload
from models.ticket import RoutingDecision, SLATarget
from models.ticket import TicketCreateRequest, TicketInfo
from models.triage import ReviewerDecision, TriagePackage
from models.vendor import VendorMatch, VendorProfile, VendorTier

# ===========================
# Sample data factories
# ===========================

NOW = datetime(2026, 4, 12, 12, 0, 0)


def _make_attachment(**overrides) -> dict:
    data = {
        "attachment_id": "att-001",
        "filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 102400,
    }
    data.update(overrides)
    return data


def _make_parsed_email(**overrides) -> dict:
    data = {
        "message_id": "AAMkAGI2abc123",
        "correlation_id": "corr-001",
        "query_id": "VQ-2026-0001",
        "sender_email": "vendor@example.com",
        "recipients": ["support@company.com"],
        "subject": "Invoice #1234 payment status",
        "body_text": "Please check the status of invoice #1234.",
        "received_at": NOW,
        "parsed_at": NOW,
        "thread_status": "NEW",
    }
    data.update(overrides)
    return data


def _make_query_submission(**overrides) -> dict:
    data = {
        "query_type": "INVOICE_PAYMENT",
        "subject": "Invoice payment inquiry",
        "description": "I need to check the status of my recent invoice submission.",
    }
    data.update(overrides)
    return data


def _make_analysis_result(**overrides) -> dict:
    data = {
        "intent_classification": "invoice_inquiry",
        "urgency_level": "MEDIUM",
        "sentiment": "NEUTRAL",
        "confidence_score": 0.92,
        "suggested_category": "accounts_payable",
        "analysis_duration_ms": 3200,
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 1500,
        "tokens_out": 500,
    }
    data.update(overrides)
    return data


def _make_sla_target(**overrides) -> dict:
    data = {"total_hours": 24}
    data.update(overrides)
    return data


def _make_routing_decision(**overrides) -> dict:
    data = {
        "assigned_team": "accounts_payable",
        "sla_target": _make_sla_target(),
        "category": "invoice",
        "priority": "MEDIUM",
        "routing_reason": "Standard invoice inquiry, Silver tier vendor",
    }
    data.update(overrides)
    return data


def _make_vendor_tier(**overrides) -> dict:
    data = {"tier_name": "SILVER", "sla_hours": 24, "priority_multiplier": 1.0}
    data.update(overrides)
    return data


def _make_vendor_profile(**overrides) -> dict:
    data = {
        "vendor_id": "V-001",
        "vendor_name": "TechNova Solutions",
        "tier": _make_vendor_tier(),
        "primary_contact_email": "contact@technova.com",
        "is_active": True,
    }
    data.update(overrides)
    return data


def _make_draft_response(**overrides) -> dict:
    data = {
        "draft_type": "RESOLUTION",
        "subject": "Re: Invoice #1234 payment status",
        "body": "Dear Vendor, your invoice #1234 was processed on...",
        "confidence": 0.90,
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 3000,
        "tokens_out": 800,
        "draft_duration_ms": 4500,
    }
    data.update(overrides)
    return data


# ===========================
# EmailAttachment tests
# ===========================


class TestEmailAttachment:
    def test_valid_attachment(self):
        att = EmailAttachment(**_make_attachment())
        assert att.attachment_id == "att-001"
        assert att.extraction_status == "pending"

    def test_attachment_with_extracted_text(self):
        att = EmailAttachment(**_make_attachment(extracted_text="Invoice total: $5000", extraction_status="success"))
        assert att.extracted_text == "Invoice total: $5000"

    def test_frozen(self):
        att = EmailAttachment(**_make_attachment())
        with pytest.raises(ValidationError):
            att.filename = "changed.pdf"


# ===========================
# ParsedEmailPayload tests
# ===========================


class TestParsedEmailPayload:
    def test_valid_email(self):
        email = ParsedEmailPayload(**_make_parsed_email())
        assert email.source == "email"
        assert email.thread_status == "NEW"

    def test_email_with_attachments(self):
        email = ParsedEmailPayload(**_make_parsed_email(attachments=[_make_attachment()]))
        assert len(email.attachments) == 1

    def test_frozen(self):
        email = ParsedEmailPayload(**_make_parsed_email())
        with pytest.raises(ValidationError):
            email.subject = "changed"


# ===========================
# QuerySubmission tests
# ===========================


class TestQuerySubmission:
    def test_valid_submission(self):
        qs = QuerySubmission(**_make_query_submission())
        assert qs.priority == "MEDIUM"

    def test_subject_too_short(self):
        with pytest.raises(ValidationError, match="at least 5"):
            QuerySubmission(**_make_query_submission(subject="Hi"))

    def test_subject_too_long(self):
        with pytest.raises(ValidationError, match="at most 500"):
            QuerySubmission(**_make_query_submission(subject="x" * 501))

    def test_description_too_short(self):
        with pytest.raises(ValidationError, match="at least 10"):
            QuerySubmission(**_make_query_submission(description="Short"))

    def test_description_too_long(self):
        with pytest.raises(ValidationError, match="at most 5000"):
            QuerySubmission(**_make_query_submission(description="x" * 5001))

    def test_invalid_priority(self):
        with pytest.raises(ValidationError):
            QuerySubmission(**_make_query_submission(priority="URGENT"))

    def test_invalid_query_type_rejected(self):
        """Free-text query types are rejected — must be one of the 12 official types."""
        with pytest.raises(ValidationError):
            QuerySubmission(**_make_query_submission(query_type="billing"))

    def test_all_query_types_accepted(self):
        """All 12 official query types should be accepted."""
        from models.query import QUERY_TYPES
        for qt in QUERY_TYPES:
            qs = QuerySubmission(**_make_query_submission(query_type=qt))
            assert qs.query_type == qt


# ===========================
# UnifiedQueryPayload tests
# ===========================


class TestUnifiedQueryPayload:
    def test_valid_portal_payload(self):
        payload = UnifiedQueryPayload(
            query_id="VQ-2026-0001",
            correlation_id="corr-001",
            execution_id="exec-001",
            source="portal",
            subject="Test query",
            body="Full query details here.",
            received_at=NOW,
        )
        assert payload.source == "portal"
        assert payload.thread_status == "NEW"

    def test_valid_email_payload(self):
        payload = UnifiedQueryPayload(
            query_id="VQ-2026-0002",
            correlation_id="corr-002",
            execution_id="exec-002",
            source="email",
            subject="Re: Invoice",
            body="Please check invoice status.",
            received_at=NOW,
            thread_status="EXISTING_OPEN",
        )
        assert payload.source == "email"


# ===========================
# VendorTier / VendorProfile / VendorMatch tests
# ===========================


class TestVendorModels:
    def test_valid_tier(self):
        tier = VendorTier(**_make_vendor_tier())
        assert tier.tier_name == "SILVER"

    def test_invalid_tier_name(self):
        with pytest.raises(ValidationError):
            VendorTier(**_make_vendor_tier(tier_name="DIAMOND"))

    def test_valid_profile(self):
        profile = VendorProfile(**_make_vendor_profile())
        assert profile.vendor_name == "TechNova Solutions"
        assert profile.tier.tier_name == "SILVER"

    def test_valid_match(self):
        match = VendorMatch(
            vendor_id="V-001",
            vendor_name="TechNova",
            match_method="exact_email",
            confidence=0.95,
        )
        assert match.confidence == 0.95

    def test_match_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            VendorMatch(
                vendor_id="V-001",
                vendor_name="TechNova",
                match_method="exact_email",
                confidence=1.5,
            )


# ===========================
# AnalysisResult tests
# ===========================


class TestAnalysisResult:
    def test_valid_result(self):
        result = AnalysisResult(**_make_analysis_result())
        assert result.confidence_score == 0.92

    def test_confidence_below_zero(self):
        with pytest.raises(ValidationError):
            AnalysisResult(**_make_analysis_result(confidence_score=-0.1))

    def test_confidence_above_one(self):
        with pytest.raises(ValidationError):
            AnalysisResult(**_make_analysis_result(confidence_score=1.1))

    def test_invalid_urgency(self):
        with pytest.raises(ValidationError):
            AnalysisResult(**_make_analysis_result(urgency_level="EXTREME"))

    def test_invalid_sentiment(self):
        with pytest.raises(ValidationError):
            AnalysisResult(**_make_analysis_result(sentiment="ANGRY"))


# ===========================
# Routing tests
# ===========================


class TestRoutingModels:
    def test_valid_sla_target(self):
        sla = SLATarget(**_make_sla_target())
        assert sla.warning_at_percent == 70

    def test_valid_routing_decision(self):
        rd = RoutingDecision(**_make_routing_decision())
        assert rd.assigned_team == "accounts_payable"
        assert rd.sla_target.total_hours == 24


# ===========================
# KB search tests
# ===========================


class TestKBModels:
    def test_valid_article_match(self):
        match = KBArticleMatch(
            article_id="kb-001",
            title="Invoice Payment Process",
            content_snippet="To check invoice status...",
            similarity_score=0.87,
            category="accounts_payable",
        )
        assert match.similarity_score == 0.87

    def test_similarity_out_of_range(self):
        with pytest.raises(ValidationError):
            KBArticleMatch(
                article_id="kb-001",
                title="Test",
                content_snippet="Test",
                similarity_score=1.5,
                category="test",
            )

    def test_valid_search_result(self):
        result = KBSearchResult(
            search_duration_ms=150,
            query_embedding_model="amazon.titan-embed-text-v2",
            has_sufficient_match=True,
            best_match_score=0.87,
        )
        assert result.has_sufficient_match is True


# ===========================
# Ticket tests
# ===========================


class TestTicketModels:
    def test_valid_ticket_create_request(self):
        req = TicketCreateRequest(
            query_id="VQ-2026-0001",
            correlation_id="corr-001",
            subject="Invoice inquiry",
            description="Details...",
            priority="3",
            assigned_team="accounts_payable",
            category="invoice",
            sla_hours=24,
        )
        assert req.query_id == "VQ-2026-0001"

    def test_valid_ticket_info(self):
        ticket = TicketInfo(
            ticket_id="INC-0001234",
            query_id="VQ-2026-0001",
            status="New",
            created_at=NOW,
            assigned_team="accounts_payable",
            sla_deadline=NOW,
        )
        assert ticket.ticket_id == "INC-0001234"

    def test_invalid_ticket_id_format(self):
        # Validator message now references the real ServiceNow form
        # (INC0010001) rather than the old hyphenated placeholder.
        with pytest.raises(ValidationError, match="INC.*7\\+ digits"):
            TicketInfo(
                ticket_id="TICKET-001",
                query_id="VQ-2026-0001",
                status="New",
                created_at=NOW,
                assigned_team="team",
                sla_deadline=NOW,
            )


# ===========================
# Draft tests
# ===========================


class TestDraftModels:
    def test_valid_resolution_draft(self):
        draft = DraftResponse(**_make_draft_response())
        assert draft.draft_type == "RESOLUTION"

    def test_valid_acknowledgment_draft(self):
        draft = DraftResponse(**_make_draft_response(draft_type="ACKNOWLEDGMENT"))
        assert draft.draft_type == "ACKNOWLEDGMENT"

    def test_invalid_draft_type(self):
        with pytest.raises(ValidationError):
            DraftResponse(**_make_draft_response(draft_type="FOLLOW_UP"))

    def test_valid_quality_gate_result(self):
        qg = QualityGateResult(passed=True, checks_run=7, checks_passed=7)
        assert qg.passed is True
        assert qg.failed_checks == []

    def test_failed_quality_gate(self):
        qg = QualityGateResult(
            passed=False,
            checks_run=7,
            checks_passed=5,
            failed_checks=["ticket_format", "pii_scan"],
        )
        assert len(qg.failed_checks) == 2


# ===========================
# Triage tests
# ===========================


class TestTriageModels:
    def test_valid_triage_package(self):
        package = TriagePackage(
            query_id="VQ-2026-0001",
            correlation_id="corr-001",
            callback_token="cb-token-abc-123",
            original_query=UnifiedQueryPayload(
                query_id="VQ-2026-0001",
                correlation_id="corr-001",
                execution_id="exec-001",
                source="email",
                subject="Test",
                body="Test body text.",
                received_at=NOW,
            ),
            analysis_result=AnalysisResult(**_make_analysis_result()),
            suggested_routing=RoutingDecision(**_make_routing_decision()),
            created_at=NOW,
        )
        assert package.query_id == "VQ-2026-0001"
        assert package.callback_token == "cb-token-abc-123"

    def test_valid_reviewer_decision(self):
        decision = ReviewerDecision(
            query_id="VQ-2026-0001",
            reviewer_id="reviewer-001",
            corrected_intent="delivery_status",
            reviewer_notes="Intent was misclassified — this is about delivery, not invoice.",
            decided_at=NOW,
        )
        assert decision.corrected_intent == "delivery_status"


# ===========================
# Memory tests
# ===========================


class TestMemoryModels:
    def test_valid_episodic_memory(self):
        entry = EpisodicMemoryEntry(
            memory_id="mem-001",
            vendor_id="V-001",
            query_id="VQ-2026-0001",
            intent="invoice_inquiry",
            resolution_path="A",
            outcome="resolved",
            resolved_at=NOW,
            summary="Vendor asked about invoice #1234. Resolved via KB article.",
        )
        assert entry.resolution_path == "A"

    def test_invalid_resolution_path(self):
        with pytest.raises(ValidationError):
            EpisodicMemoryEntry(
                memory_id="mem-001",
                vendor_id="V-001",
                query_id="VQ-2026-0001",
                intent="test",
                resolution_path="D",
                outcome="resolved",
                resolved_at=NOW,
                summary="Test",
            )

    def test_valid_vendor_context(self):
        ctx = VendorContext(
            vendor_id="V-001",
            vendor_profile=VendorProfile(**_make_vendor_profile()),
        )
        assert ctx.vendor_id == "V-001"
        assert len(ctx.recent_interactions) == 0


# ===========================
# PipelineState tests
# ===========================


class TestPipelineState:
    def test_pipeline_state_is_typeddict(self):
        """PipelineState is a TypedDict, not a Pydantic model."""
        state: PipelineState = {
            "query_id": "VQ-2026-0001",
            "correlation_id": "corr-001",
            "execution_id": "exec-001",
            "source": "email",
            "status": "RECEIVED",
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        }
        assert state["query_id"] == "VQ-2026-0001"
        assert state["status"] == "RECEIVED"

    def test_pipeline_state_is_mutable(self):
        """TypedDict allows mutation (unlike frozen Pydantic models)."""
        state: PipelineState = {
            "query_id": "VQ-2026-0001",
            "status": "RECEIVED",
        }
        state["status"] = "ANALYZING"
        assert state["status"] == "ANALYZING"
