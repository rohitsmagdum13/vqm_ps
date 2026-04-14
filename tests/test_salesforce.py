"""Tests for SalesforceConnector.

All tests mock the simple-salesforce client. No real Salesforce
API calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adapters.salesforce import SalesforceConnector


@pytest.fixture
def sf_connector(mock_settings) -> SalesforceConnector:
    """Create a SalesforceConnector with a mocked SF client."""
    connector = SalesforceConnector(mock_settings)

    # Create a mock Salesforce client
    mock_sf = MagicMock()
    connector._sf = mock_sf
    return connector


def _sf_query_result(records: list[dict]) -> dict:
    """Build a Salesforce query result dict."""
    return {
        "totalSize": len(records),
        "done": True,
        "records": records,
    }


class TestFindVendorByEmail:
    """Tests for find_vendor_by_email method."""

    async def test_found_returns_vendor_match(self, sf_connector) -> None:
        """Matching email returns VendorMatch with exact_email method."""
        sf_connector._sf.query.return_value = _sf_query_result(
            [
                {
                    "Vendor_Account__r": {"Id": "001ABC", "Name": "TechNova Solutions"},
                    "Vendor_Account__c": "001ABC",
                }
            ]
        )

        result = await sf_connector.find_vendor_by_email(
            "rajesh@technova.com", correlation_id="test-sf-001"
        )

        assert result is not None
        assert result.vendor_id == "001ABC"
        assert result.vendor_name == "TechNova Solutions"
        assert result.match_method == "exact_email"
        assert result.confidence == 1.0

    async def test_not_found_returns_none(self, sf_connector) -> None:
        """No matching email returns None."""
        sf_connector._sf.query.return_value = _sf_query_result([])

        result = await sf_connector.find_vendor_by_email(
            "unknown@nowhere.com", correlation_id="test-sf-002"
        )
        assert result is None

    async def test_sf_exception_returns_none(self, sf_connector) -> None:
        """Salesforce API error returns None (not raised)."""
        sf_connector._sf.query.side_effect = Exception("SF API timeout")

        result = await sf_connector.find_vendor_by_email(
            "rajesh@technova.com", correlation_id="test-sf-003"
        )
        assert result is None


class TestFuzzyNameMatch:
    """Tests for fuzzy_name_match method."""

    async def test_found_returns_vendor_match(self, sf_connector) -> None:
        """Matching name returns VendorMatch with fuzzy_name method."""
        sf_connector._sf.query.return_value = _sf_query_result(
            [{"Id": "001DEF", "Name": "Acme Corporation"}]
        )

        result = await sf_connector.fuzzy_name_match(
            "Acme", correlation_id="test-sf-010"
        )

        assert result is not None
        assert result.vendor_id == "001DEF"
        assert result.match_method == "fuzzy_name"
        assert result.confidence == 0.6

    async def test_empty_name_returns_none(self, sf_connector) -> None:
        """Empty or whitespace-only name returns None immediately."""
        result = await sf_connector.fuzzy_name_match("", correlation_id="test-sf-011")
        assert result is None

        result = await sf_connector.fuzzy_name_match("   ", correlation_id="test-sf-012")
        assert result is None

    async def test_not_found_returns_none(self, sf_connector) -> None:
        """No matching name returns None."""
        sf_connector._sf.query.return_value = _sf_query_result([])

        result = await sf_connector.fuzzy_name_match("NonexistentCorp")
        assert result is None


class TestIdentifyVendor:
    """Tests for the 3-step identify_vendor fallback chain."""

    async def test_step1_email_match_succeeds(self, sf_connector) -> None:
        """Step 1 succeeds — returns immediately without trying steps 2-3."""
        sf_connector._sf.query.return_value = _sf_query_result(
            [
                {
                    "Vendor_Account__r": {"Id": "001ABC", "Name": "TechNova Solutions"},
                    "Vendor_Account__c": "001ABC",
                }
            ]
        )

        result = await sf_connector.identify_vendor(
            sender_email="rajesh@technova.com",
            sender_name="Rajesh Kumar",
            correlation_id="test-sf-020",
        )

        assert result is not None
        assert result.match_method == "exact_email"
        # Only one query should have been made (step 1)
        assert sf_connector._sf.query.call_count == 1

    async def test_fallback_to_fuzzy_name(self, sf_connector) -> None:
        """Steps 1-2 fail, step 3 (fuzzy name) succeeds."""
        # First call (email lookup) returns empty
        # Second call (fuzzy name) returns a match
        sf_connector._sf.query.side_effect = [
            _sf_query_result([]),  # Step 1: no email match
            _sf_query_result([{"Id": "001XYZ", "Name": "Kumar Industries"}]),  # Step 3: fuzzy match
        ]

        result = await sf_connector.identify_vendor(
            sender_email="unknown@gmail.com",
            sender_name="Kumar",
            correlation_id="test-sf-021",
        )

        assert result is not None
        assert result.match_method == "fuzzy_name"
        assert result.vendor_id == "001XYZ"

    async def test_all_steps_fail_returns_none(self, sf_connector) -> None:
        """All 3 steps fail — returns None."""
        sf_connector._sf.query.return_value = _sf_query_result([])

        result = await sf_connector.identify_vendor(
            sender_email="nobody@nowhere.com",
            sender_name="Nobody",
            correlation_id="test-sf-022",
        )
        assert result is None

    async def test_body_extraction_finds_vendor(self, sf_connector) -> None:
        """Step 2 extracts an email from the body text and finds a match."""
        # First call (sender email) returns empty
        # Second call (extracted email from body) returns a match
        sf_connector._sf.query.side_effect = [
            _sf_query_result([]),  # Step 1: sender email not found
            _sf_query_result(  # Step 2: extracted email found
                [
                    {
                        "Vendor_Account__r": {"Id": "001BODY", "Name": "BodyCorp"},
                        "Vendor_Account__c": "001BODY",
                    }
                ]
            ),
        ]

        result = await sf_connector.identify_vendor(
            sender_email="personal@gmail.com",
            sender_name="Someone",
            body_text="Please contact us at official@bodycorp.com for details.",
            correlation_id="test-sf-023",
        )

        assert result is not None
        assert result.vendor_id == "001BODY"
        assert result.match_method == "body_extraction"
        assert result.confidence == 0.8

    async def test_no_sender_name_skips_step3(self, sf_connector) -> None:
        """When sender_name is None, step 3 is skipped."""
        sf_connector._sf.query.return_value = _sf_query_result([])

        result = await sf_connector.identify_vendor(
            sender_email="nobody@nowhere.com",
            sender_name=None,
            correlation_id="test-sf-024",
        )
        assert result is None
