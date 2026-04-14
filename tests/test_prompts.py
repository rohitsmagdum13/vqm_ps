"""Tests for the PromptManager and Jinja2 templates.

Verifies that all templates render correctly with sample data,
raise errors on missing variables, and cache loaded templates.
"""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from orchestration.prompts.prompt_manager import PromptManager


@pytest.fixture
def prompt_manager() -> PromptManager:
    """Create a PromptManager instance."""
    return PromptManager()


@pytest.fixture
def analysis_variables() -> dict:
    """Sample variables for query_analysis_v1.j2."""
    return {
        "vendor_name": "TechNova Solutions",
        "vendor_tier": "GOLD",
        "query_subject": "Invoice discrepancy for PO-2026-1234",
        "query_body": (
            "We noticed a discrepancy between invoice #INV-5678 "
            "and PO-2026-1234. The invoice shows $15,000 but the PO "
            "was approved for $12,500. Please review."
        ),
        "attachment_text": "Invoice #INV-5678 Total: $15,000.00",
        "recent_interactions": [
            {
                "query_id": "VQ-2026-0001",
                "intent": "invoice_inquiry",
                "outcome": "resolved",
                "resolution_path": "A",
            },
        ],
        "query_source": "email",
    }


@pytest.fixture
def resolution_variables() -> dict:
    """Sample variables for resolution_v1.j2."""
    return {
        "vendor_name": "TechNova Solutions",
        "vendor_tier": "GOLD",
        "original_query": "Invoice discrepancy for PO-2026-1234",
        "intent": "invoice_inquiry",
        "entities": "Invoice: INV-5678, PO: PO-2026-1234, Amount: $15,000",
        "kb_articles": [
            {
                "title": "Invoice Discrepancy Resolution Process",
                "content_snippet": "When an invoice amount differs from the PO...",
            },
        ],
        "ticket_number": "INC-0001234",
        "sla_statement": "We will respond within 4 hours.",
    }


@pytest.fixture
def acknowledgment_variables() -> dict:
    """Sample variables for acknowledgment_v1.j2."""
    return {
        "vendor_name": "TechNova Solutions",
        "vendor_tier": "GOLD",
        "original_query": "Invoice discrepancy for PO-2026-1234",
        "intent": "invoice_inquiry",
        "ticket_number": "INC-0001234",
        "sla_statement": "We will respond within 4 hours.",
        "assigned_team": "finance-ops",
    }


@pytest.fixture
def resolution_notes_variables() -> dict:
    """Sample variables for resolution_from_notes_v1.j2."""
    return {
        "vendor_name": "TechNova Solutions",
        "vendor_tier": "GOLD",
        "original_query": "Invoice discrepancy for PO-2026-1234",
        "intent": "invoice_inquiry",
        "ticket_number": "INC-0001234",
        "work_notes": "Investigated and found PO was amended. Correct amount is $15,000.",
        "sla_statement": "Resolved within SLA.",
    }


# ===========================
# Render Tests
# ===========================


class TestRender:
    """Tests for PromptManager.render."""

    def test_query_analysis_renders_with_all_variables(
        self, prompt_manager, analysis_variables
    ) -> None:
        """query_analysis_v1.j2 renders without errors when all variables provided."""
        result = prompt_manager.render("query_analysis_v1.j2", **analysis_variables)

        assert "TechNova Solutions" in result
        assert "GOLD" in result
        assert "Invoice discrepancy" in result
        assert "INV-5678" in result
        assert "email" in result
        assert "{{" not in result  # No unrendered placeholders

    def test_query_analysis_renders_without_optional_sections(self, prompt_manager) -> None:
        """Template renders when optional sections (attachments, interactions) are empty."""
        result = prompt_manager.render(
            "query_analysis_v1.j2",
            vendor_name="Acme Corp",
            vendor_tier="BRONZE",
            query_subject="General question",
            query_body="I have a question about my account.",
            attachment_text="",
            recent_interactions=[],
            query_source="portal",
        )

        assert "Acme Corp" in result
        assert "{{" not in result

    def test_resolution_renders(self, prompt_manager, resolution_variables) -> None:
        """resolution_v1.j2 renders without errors."""
        result = prompt_manager.render("resolution_v1.j2", **resolution_variables)

        assert "TechNova Solutions" in result
        assert "INC-0001234" in result
        assert "Invoice Discrepancy Resolution Process" in result
        assert "{{" not in result

    def test_acknowledgment_renders(self, prompt_manager, acknowledgment_variables) -> None:
        """acknowledgment_v1.j2 renders without errors."""
        result = prompt_manager.render("acknowledgment_v1.j2", **acknowledgment_variables)

        assert "TechNova Solutions" in result
        assert "INC-0001234" in result
        assert "finance-ops" in result
        assert "{{" not in result

    def test_resolution_from_notes_renders(
        self, prompt_manager, resolution_notes_variables
    ) -> None:
        """resolution_from_notes_v1.j2 renders without errors."""
        result = prompt_manager.render(
            "resolution_from_notes_v1.j2", **resolution_notes_variables
        )

        assert "TechNova Solutions" in result
        assert "INC-0001234" in result
        assert "PO was amended" in result
        assert "{{" not in result

    def test_missing_required_variable_raises_undefined_error(self, prompt_manager) -> None:
        """Missing a required variable raises UndefinedError."""
        with pytest.raises(UndefinedError):
            prompt_manager.render(
                "query_analysis_v1.j2",
                vendor_name="Test",
                # Missing all other required variables
            )

    def test_render_returns_string(self, prompt_manager, analysis_variables) -> None:
        """Render always returns a string."""
        result = prompt_manager.render("query_analysis_v1.j2", **analysis_variables)
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================
# Metadata Tests
# ===========================


class TestGetMetadata:
    """Tests for PromptManager.get_metadata."""

    def test_metadata_extracts_version(self, prompt_manager) -> None:
        """Version is extracted from the _vN.j2 filename pattern."""
        metadata = prompt_manager.get_metadata("query_analysis_v1.j2")
        assert metadata["version"] == "1"

    def test_metadata_includes_template_name(self, prompt_manager) -> None:
        """Template name is included in metadata."""
        metadata = prompt_manager.get_metadata("resolution_v1.j2")
        assert metadata["template_name"] == "resolution_v1.j2"

    def test_metadata_lists_required_variables(self, prompt_manager) -> None:
        """Required variables are discovered from the template source."""
        metadata = prompt_manager.get_metadata("query_analysis_v1.j2")
        variables = metadata["required_variables"]

        # These are the top-level variables used directly in the template
        assert "vendor_name" in variables
        assert "vendor_tier" in variables
        assert "query_subject" in variables
        assert "query_body" in variables
        assert "query_source" in variables

    def test_acknowledgment_metadata_variables(self, prompt_manager) -> None:
        """Acknowledgment template should list its required variables."""
        metadata = prompt_manager.get_metadata("acknowledgment_v1.j2")
        variables = metadata["required_variables"]

        assert "vendor_name" in variables
        assert "ticket_number" in variables
        assert "assigned_team" in variables


# ===========================
# Caching Tests
# ===========================


class TestCaching:
    """Tests for template caching."""

    def test_template_is_cached_after_first_render(
        self, prompt_manager, analysis_variables
    ) -> None:
        """Second render of the same template uses the cache."""
        assert "query_analysis_v1.j2" not in prompt_manager._cache

        prompt_manager.render("query_analysis_v1.j2", **analysis_variables)
        assert "query_analysis_v1.j2" in prompt_manager._cache

        # Render again — should use cached template
        prompt_manager.render("query_analysis_v1.j2", **analysis_variables)
        assert len(prompt_manager._cache) == 1
