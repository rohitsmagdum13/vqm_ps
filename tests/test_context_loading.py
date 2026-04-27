"""Tests for the Context Loading Node (Step 7).

Tests vendor profile loading (cache hit, cache miss, no vendor_id),
episodic memory loading, and status update to ANALYZING.
"""

from __future__ import annotations

import pytest

from orchestration.nodes.context_loading import ContextLoadingNode


@pytest.fixture
def context_node(mock_settings, mock_postgres, mock_salesforce) -> ContextLoadingNode:
    """Create a ContextLoadingNode with mocked connectors."""
    return ContextLoadingNode(
        postgres=mock_postgres,
        salesforce=mock_salesforce,
        settings=mock_settings,
    )


@pytest.fixture
def base_state() -> dict:
    """Minimal pipeline state for testing."""
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "test-corr-123",
        "execution_id": "test-exec-123",
        "source": "email",
        "unified_payload": {
            "query_id": "VQ-2026-0001",
            "vendor_id": "V-001",
            "subject": "Invoice question",
            "body": "I have a question about invoice INV-5678.",
            "source": "email",
        },
    }


class TestContextLoading:
    """Tests for ContextLoadingNode.execute."""

    @pytest.mark.asyncio
    async def test_no_vendor_id_returns_none_context(
        self, context_node, mock_postgres
    ) -> None:
        """When vendor_id is None, vendor_context should be None."""
        state = {
            "correlation_id": "test-123",
            "unified_payload": {"vendor_id": None, "subject": "Test"},
        }

        result = await context_node.execute(state)

        assert result["vendor_context"] is None
        assert result["status"] == "ANALYZING"
        # Salesforce should NOT be called
        mock_postgres.cache_read.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_salesforce(
        self, context_node, base_state, mock_postgres, mock_salesforce
    ) -> None:
        """When vendor is in cache, Salesforce should not be called."""
        mock_postgres.cache_read.return_value = {
            "vendor_id": "V-001",
            "vendor_name": "TechNova Solutions",
            "tier": {"tier_name": "GOLD", "sla_hours": 8, "priority_multiplier": 1.0},
            "primary_contact_email": "rajesh@technova.com",
            "is_active": True,
        }

        result = await context_node.execute(base_state)

        assert result["vendor_context"] is not None
        assert result["vendor_context"]["vendor_id"] == "V-001"
        assert result["vendor_context"]["vendor_profile"]["vendor_name"] == "TechNova Solutions"
        assert result["status"] == "ANALYZING"
        mock_salesforce.find_vendor_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_salesforce(
        self, context_node, base_state, mock_postgres, mock_salesforce
    ) -> None:
        """When cache is empty, Salesforce should be called."""
        mock_postgres.cache_read.return_value = None
        mock_salesforce.find_vendor_by_id.return_value = {
            "Name": "TechNova Solutions",
            "Email": "rajesh@technova.com",
        }

        result = await context_node.execute(base_state)

        assert result["vendor_context"] is not None
        assert result["status"] == "ANALYZING"
        mock_salesforce.find_vendor_by_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_sources_fail_uses_default_profile(
        self, context_node, base_state, mock_postgres, mock_salesforce
    ) -> None:
        """When both cache and Salesforce fail, default BRONZE profile is used."""
        mock_postgres.cache_read.side_effect = Exception("DB error")
        mock_salesforce.find_vendor_by_id.side_effect = Exception("SF error")

        result = await context_node.execute(base_state)

        assert result["vendor_context"] is not None
        profile = result["vendor_context"]["vendor_profile"]
        assert profile["vendor_name"] == "Unknown Vendor"
        assert profile["tier"]["tier_name"] == "BRONZE"

    @pytest.mark.asyncio
    async def test_episodic_memory_loaded(
        self, context_node, base_state, mock_postgres
    ) -> None:
        """Episodic memory is loaded from PostgreSQL."""
        mock_postgres.cache_read.return_value = {
            "vendor_id": "V-001",
            "vendor_name": "TechNova",
            "tier": {"tier_name": "GOLD", "sla_hours": 8, "priority_multiplier": 1.0},
            "primary_contact_email": "test@test.com",
            "is_active": True,
        }
        mock_postgres.fetch.return_value = [
            {"memory_id": "M-1", "vendor_id": "V-001", "query_id": "VQ-0001",
             "intent": "billing", "resolution_path": "A", "outcome": "resolved",
             "resolved_at": "2026-04-10T14:30:00", "summary": "Resolved billing query about INV-1234"},
            {"memory_id": "M-2", "vendor_id": "V-001", "query_id": "VQ-0002",
             "intent": "delivery", "resolution_path": "B", "outcome": "resolved",
             "resolved_at": "2026-04-08T10:15:00", "summary": "Delivery delay for PO-5678 escalated to team"},
        ]

        result = await context_node.execute(base_state)

        interactions = result["vendor_context"]["recent_interactions"]
        assert len(interactions) == 2

    @pytest.mark.asyncio
    async def test_episodic_memory_failure_returns_empty(
        self, context_node, base_state, mock_postgres
    ) -> None:
        """Failed memory load returns empty list, pipeline continues."""
        mock_postgres.cache_read.return_value = {
            "vendor_id": "V-001",
            "vendor_name": "TechNova",
            "tier": {"tier_name": "GOLD", "sla_hours": 8, "priority_multiplier": 1.0},
            "primary_contact_email": "test@test.com",
            "is_active": True,
        }
        mock_postgres.fetch.side_effect = Exception("Memory table error")

        result = await context_node.execute(base_state)

        # Should still succeed with empty interactions
        assert result["vendor_context"] is not None
        assert result["vendor_context"]["recent_interactions"] == []
        assert result["status"] == "ANALYZING"

    @pytest.mark.asyncio
    async def test_additional_context_surfaced_when_present(
        self, context_node, base_state, mock_postgres
    ) -> None:
        """Follow-up info appended by ClosureService.handle_followup_info
        is surfaced into the pipeline state for Query Analysis."""
        followup_entries = [
            {
                "source_query_id": "VQ-2026-0099",
                "received_at": "2026-04-26T11:00:00+05:30",
                "body_text": "Sorry, attaching the missing PDF",
                "attachments": [
                    {
                        "filename": "invoice.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 12345,
                        "s3_key": "attachments/VQ-2026-0099/invoice.pdf",
                        "extraction_status": "success",
                    }
                ],
            }
        ]
        # Cache hit so the vendor branch is exercised, AND follow-up rows present.
        mock_postgres.cache_read.return_value = {
            "vendor_id": "V-001",
            "vendor_name": "TechNova",
            "tier": {"tier_name": "GOLD", "sla_hours": 8, "priority_multiplier": 1.0},
            "primary_contact_email": "test@test.com",
            "is_active": True,
        }
        mock_postgres.fetchrow.return_value = {
            "additional_context": followup_entries
        }

        result = await context_node.execute(base_state)

        assert result["additional_context"] == followup_entries

    @pytest.mark.asyncio
    async def test_additional_context_omitted_when_empty(
        self, context_node, base_state, mock_postgres
    ) -> None:
        """No follow-up info → key is absent from result (graph stays terse)."""
        mock_postgres.cache_read.return_value = {
            "vendor_id": "V-001",
            "vendor_name": "TechNova",
            "tier": {"tier_name": "GOLD", "sla_hours": 8, "priority_multiplier": 1.0},
            "primary_contact_email": "test@test.com",
            "is_active": True,
        }
        mock_postgres.fetchrow.return_value = None

        result = await context_node.execute(base_state)

        assert "additional_context" not in result
