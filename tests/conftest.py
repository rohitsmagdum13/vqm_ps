"""Shared test fixtures for VQMS test suite.

Provides reusable fixtures for mocking AWS services (moto),
database connectors, external API connectors, and sample data.
All Phase 2 and later tests import fixtures from here.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import boto3
import pytest
from moto import mock_aws

from config.settings import Settings
from models.vendor import VendorMatch

# ===========================
# Settings Fixture
# ===========================


@pytest.fixture
def mock_settings() -> Settings:
    """Settings with test values — no real credentials needed."""
    return Settings(
        app_env="test",
        app_name="vqms-test",
        aws_region="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_session_token="testing",
        # S3 bucket (single bucket, prefix-organized)
        s3_bucket_data_store="test-data-store",
        # SQS queues
        sqs_email_intake_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/test-email-intake",
        sqs_query_intake_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/test-query-intake",
        sqs_visibility_timeout=30,
        # EventBridge
        eventbridge_bus_name="test-event-bus",
        eventbridge_source="com.vqms.test",
        # Graph API
        graph_api_tenant_id="test-tenant-id",
        graph_api_client_id="test-client-id",
        graph_api_client_secret="test-client-secret",
        graph_api_mailbox="test@company.com",
        graph_api_poll_interval_seconds=10,
        # Salesforce
        salesforce_instance_url="https://test.salesforce.com",
        salesforce_username="test@test.com",
        salesforce_password="testpass",
        salesforce_security_token="testtoken",
        # PostgreSQL — not connecting in tests, just need valid values
        postgres_host="localhost",
        postgres_port=5432,
        postgres_db="vqms_test",
        postgres_user="test",
        postgres_password="test",
    )


# ===========================
# AWS Credential Fixtures
# ===========================


@pytest.fixture
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set fake AWS credentials so moto doesn't look for real ones."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


# ===========================
# AWS S3 Mock Fixture
# ===========================


@pytest.fixture
def mock_s3(aws_credentials: None) -> Any:
    """Create moto S3 mock with single test bucket.

    Uses the single-bucket architecture: one bucket with
    prefix-based organization (inbound-emails/, attachments/,
    processed/, templates/, archive/).

    Yields the boto3 S3 client so tests can verify state directly.
    """
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-data-store")
        yield client


# ===========================
# AWS SQS Mock Fixture
# ===========================


@pytest.fixture
def mock_sqs(aws_credentials: None) -> Any:
    """Create moto SQS mock with test queues.

    Yields a tuple of (client, queue_urls dict) so tests can
    send/receive messages and verify queue state.
    """
    with mock_aws():
        client = boto3.client("sqs", region_name="us-east-1")

        # Create test queues
        email_queue = client.create_queue(QueueName="test-email-intake")
        query_queue = client.create_queue(QueueName="test-query-intake")

        queue_urls = {
            "email_intake": email_queue["QueueUrl"],
            "query_intake": query_queue["QueueUrl"],
        }
        yield client, queue_urls


# ===========================
# AWS EventBridge Mock Fixture
# ===========================


@pytest.fixture
def mock_eventbridge(aws_credentials: None) -> Any:
    """Create moto EventBridge mock with test event bus.

    Yields the boto3 EventBridge client.
    """
    with mock_aws():
        client = boto3.client("events", region_name="us-east-1")
        client.create_event_bus(Name="test-event-bus")
        yield client


# ===========================
# Mock Connector Fixtures
# ===========================


@pytest.fixture
def mock_postgres() -> AsyncMock:
    """AsyncMock of PostgresConnector for service-level tests.

    Pre-configured: check_idempotency returns True (new key),
    execute/fetch/fetchrow return sensible defaults.
    """
    mock = AsyncMock()
    mock.check_idempotency.return_value = True
    mock.execute.return_value = "INSERT 0 1"
    mock.fetch.return_value = []
    mock.fetchrow.return_value = None
    mock.health_check.return_value = True
    return mock


@pytest.fixture
def mock_graph_api() -> AsyncMock:
    """AsyncMock of GraphAPIConnector for service-level tests.

    Pre-configured: fetch_email returns a realistic Graph API response.
    """
    mock = AsyncMock()
    mock.fetch_email.return_value = _sample_graph_email_response()
    mock.list_unread_messages.return_value = []
    mock.send_email.return_value = None
    mock.close.return_value = None
    return mock


@pytest.fixture
def mock_salesforce() -> AsyncMock:
    """AsyncMock of SalesforceConnector for service-level tests.

    Pre-configured: identify_vendor returns a VendorMatch.
    """
    mock = AsyncMock()
    mock.identify_vendor.return_value = VendorMatch(
        vendor_id="V-001",
        vendor_name="TechNova Solutions",
        match_method="exact_email",
        confidence=1.0,
    )
    mock.find_vendor_by_email.return_value = VendorMatch(
        vendor_id="V-001",
        vendor_name="TechNova Solutions",
        match_method="exact_email",
        confidence=1.0,
    )
    return mock


# ===========================
# Sample Data Fixtures
# ===========================


@pytest.fixture
def sample_email_response() -> dict:
    """Realistic Microsoft Graph API /messages/{id} response.

    Includes from, subject, body, conversationId, and attachments.
    """
    return _sample_graph_email_response()


@pytest.fixture
def sample_query_submission() -> dict:
    """Valid QuerySubmission data dict for portal intake tests."""
    return {
        "subject": "Invoice discrepancy for PO-2026-1234",
        "description": (
            "We noticed a discrepancy between the invoice amount "
            "and the purchase order total. Invoice #INV-5678 shows "
            "$15,000 but PO-2026-1234 was approved for $12,500. "
            "Please review and advise."
        ),
        "query_type": "billing",
        "priority": "high",
        "reference_number": "PO-2026-1234",
    }


# ===========================
# Private Helpers
# ===========================


def _sample_graph_email_response() -> dict:
    """Build a realistic Graph API email response dict."""
    return {
        "id": "AAMkAGI2TG93AAA=",
        "subject": "Invoice discrepancy for PO-2026-1234",
        "from": {
            "emailAddress": {
                "name": "Rajesh Kumar",
                "address": "rajesh.kumar@technova.com",
            }
        },
        "toRecipients": [
            {
                "emailAddress": {
                    "name": "Vendor Support",
                    "address": "vendorsupport@company.com",
                }
            }
        ],
        "body": {
            "contentType": "html",
            "content": (
                "<html><body>"
                "<p>Dear Support Team,</p>"
                "<p>We noticed a discrepancy between invoice #INV-5678 "
                "and PO-2026-1234. The invoice shows $15,000 but the PO "
                "was approved for $12,500.</p>"
                "<p>Please review and advise.</p>"
                "<p>Best regards,<br>Rajesh Kumar<br>TechNova Solutions</p>"
                "</body></html>"
            ),
        },
        "bodyPreview": "Dear Support Team, We noticed a discrepancy...",
        "conversationId": "AAQkAGI2TG93conv=",
        "internetMessageHeaders": [
            {"name": "In-Reply-To", "value": ""},
            {"name": "References", "value": ""},
        ],
        "receivedDateTime": "2026-04-12T10:30:00Z",
        "isRead": False,
        "hasAttachments": True,
        "attachments": [
            {
                "id": "ATT-001",
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "invoice_5678.pdf",
                "contentType": "application/pdf",
                "size": 245760,
                "contentBytes": "JVBERi0xLjQK",  # Base64 stub
            }
        ],
    }
