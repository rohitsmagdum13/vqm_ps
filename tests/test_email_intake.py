"""Tests for EmailIntakeService.

All connectors are mocked via AsyncMock fixtures from conftest.
Tests verify the 10-step pipeline, critical/non-critical step
behavior, and attachment processing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.email_intake import EmailIntakeService
from models.email import ParsedEmailPayload


@pytest.fixture
def mock_s3_connector() -> AsyncMock:
    """Mock S3 connector that tracks upload calls.

    Returns keys matching the single-bucket architecture:
    inbound-emails/VQ-YYYY-NNNN/raw_email.json
    """
    mock = AsyncMock()
    mock.upload_file.return_value = "inbound-emails/VQ-2026-0001/raw_email.json"
    return mock


@pytest.fixture
def mock_sqs_connector() -> AsyncMock:
    """Mock SQS connector that tracks send_message calls."""
    mock = AsyncMock()
    mock.send_message.return_value = "mock-message-id"
    return mock


@pytest.fixture
def mock_eventbridge_connector() -> AsyncMock:
    """Mock EventBridge connector."""
    mock = AsyncMock()
    mock.publish_event.return_value = "mock-event-id"
    return mock


@pytest.fixture
def email_service(
    mock_graph_api,
    mock_postgres,
    mock_s3_connector,
    mock_sqs_connector,
    mock_eventbridge_connector,
    mock_salesforce,
    mock_settings,
) -> EmailIntakeService:
    """Create an EmailIntakeService with all connectors mocked."""
    return EmailIntakeService(
        graph_api=mock_graph_api,
        postgres=mock_postgres,
        s3=mock_s3_connector,
        sqs=mock_sqs_connector,
        eventbridge=mock_eventbridge_connector,
        salesforce=mock_salesforce,
        settings=mock_settings,
    )


class TestProcessEmailHappyPath:
    """Tests for the full 10-step email processing pipeline."""

    async def test_process_email_returns_parsed_payload(
        self, email_service, mock_postgres
    ) -> None:
        """Full pipeline returns a ParsedEmailPayload with correct fields."""
        result = await email_service.process_email(
            "AAMkAGI2TG93AAA=", correlation_id="test-corr-100"
        )

        assert result is not None
        assert isinstance(result, ParsedEmailPayload)
        assert result.message_id == "AAMkAGI2TG93AAA="
        assert result.correlation_id == "test-corr-100"
        assert result.sender_email == "rajesh.kumar@technova.com"
        assert result.subject == "Invoice discrepancy for PO-2026-1234"
        assert result.source == "email"
        assert result.vendor_id == "V-001"
        assert result.vendor_match_method == "exact_email"

    async def test_sqs_message_sent(
        self, email_service, mock_sqs_connector
    ) -> None:
        """SQS send_message is called with the unified payload."""
        await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_sqs_connector.send_message.assert_called_once()
        call_args = mock_sqs_connector.send_message.call_args
        body = call_args.args[1]  # Second positional arg is message_body dict
        assert body["source"] == "email"
        assert "query_id" in body
        assert body["subject"] == "Invoice discrepancy for PO-2026-1234"

    async def test_db_writes_called(
        self, email_service, mock_postgres
    ) -> None:
        """Email metadata, attachment metadata, and case execution are written to DB."""
        await email_service.process_email("AAMkAGI2TG93AAA=")

        # check_idempotency + 3 execute calls:
        #   1. email_messages INSERT
        #   2. email_attachments INSERT (1 attachment in sample data)
        #   3. case_execution INSERT
        assert mock_postgres.check_idempotency.call_count == 1
        assert mock_postgres.execute.call_count == 3

    async def test_eventbridge_event_published(
        self, email_service, mock_eventbridge_connector
    ) -> None:
        """EventBridge EmailParsed event is published."""
        await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_eventbridge_connector.publish_event.assert_called_once()
        call_args = mock_eventbridge_connector.publish_event.call_args
        assert call_args.args[0] == "EmailParsed"


class TestProcessEmailDuplicate:
    """Tests for idempotency (duplicate detection)."""

    async def test_duplicate_returns_none(
        self, email_service, mock_postgres
    ) -> None:
        """Duplicate email (check_idempotency returns False) returns None."""
        mock_postgres.check_idempotency.return_value = False

        result = await email_service.process_email("AAMkAGI2TG93AAA=")
        assert result is None

    async def test_duplicate_does_not_call_graph_api(
        self, email_service, mock_postgres, mock_graph_api
    ) -> None:
        """Duplicate email skips all processing — Graph API is not called."""
        mock_postgres.check_idempotency.return_value = False

        await email_service.process_email("AAMkAGI2TG93AAA=")
        mock_graph_api.fetch_email.assert_not_called()


class TestNonCriticalStepFailures:
    """Tests that non-critical step failures don't block the pipeline."""

    async def test_s3_failure_does_not_block(
        self, email_service, mock_s3_connector
    ) -> None:
        """S3 upload failure doesn't prevent email processing."""
        mock_s3_connector.upload_file.side_effect = Exception("S3 timeout")

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        # Pipeline should still complete
        assert result is not None
        assert result.s3_raw_email_key is None  # S3 failed, but we continued

    async def test_vendor_not_found_but_domain_allowlisted_continues(
        self,
        mock_graph_api,
        mock_postgres,
        mock_s3_connector,
        mock_sqs_connector,
        mock_eventbridge_connector,
        mock_salesforce,
        mock_settings,
    ) -> None:
        """Unresolved vendor from an allowlisted domain still proceeds.

        Confirms that when Salesforce can't match the sender but the domain
        is explicitly allowlisted, the pipeline doesn't abort — it continues
        downstream with vendor_id=None and vendor_match_method='unresolved'.
        """
        mock_salesforce.identify_vendor.return_value = None
        mock_settings.email_filter_allowed_sender_domains = ["technova.com"]

        service = EmailIntakeService(
            graph_api=mock_graph_api,
            postgres=mock_postgres,
            s3=mock_s3_connector,
            sqs=mock_sqs_connector,
            eventbridge=mock_eventbridge_connector,
            salesforce=mock_salesforce,
            settings=mock_settings,
        )
        result = await service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        assert result.vendor_id is None
        assert result.vendor_match_method == "unresolved"

    async def test_eventbridge_failure_does_not_block(
        self, email_service, mock_eventbridge_connector, mock_sqs_connector
    ) -> None:
        """EventBridge failure doesn't prevent SQS enqueue."""
        mock_eventbridge_connector.publish_event.side_effect = Exception("EB down")

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        # SQS should still be called
        mock_sqs_connector.send_message.assert_called_once()


class TestAttachmentProcessing:
    """Tests for attachment safety guardrails."""

    async def test_blocked_extension_skipped(
        self, email_service, mock_graph_api
    ) -> None:
        """Attachment with .exe extension is skipped."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["attachments"] = [
            {
                "id": "ATT-EXE",
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "malware.exe",
                "contentType": "application/octet-stream",
                "size": 1024,
                "contentBytes": "",
            }
        ]
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        assert len(result.attachments) == 1
        assert result.attachments[0].extraction_status == "skipped"

    async def test_oversized_attachment_skipped(
        self, email_service, mock_graph_api
    ) -> None:
        """Attachment larger than 10MB is skipped."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["attachments"] = [
            {
                "id": "ATT-BIG",
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "huge_file.pdf",
                "contentType": "application/pdf",
                "size": 15 * 1024 * 1024,  # 15 MB
                "contentBytes": "",
            }
        ]
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        assert len(result.attachments) == 1
        assert result.attachments[0].extraction_status == "skipped"

    async def test_no_attachments_returns_empty_list(
        self, email_service, mock_graph_api
    ) -> None:
        """Email with no attachments results in empty attachment list."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["attachments"] = []
        email_response["hasAttachments"] = False
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        assert result.attachments == []


class TestAttachmentManifest:
    """Tests for attachment manifest creation after processing."""

    async def test_manifest_stored_when_attachments_exist(
        self, email_service, mock_s3_connector
    ) -> None:
        """Manifest _manifest.json is uploaded after processing attachments."""
        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        # The sample email has 1 attachment — manifest should be stored
        # upload_file is called for: raw email, attachment binary, manifest
        assert mock_s3_connector.upload_file.call_count >= 2

        # Find the manifest upload call
        manifest_calls = [
            call for call in mock_s3_connector.upload_file.call_args_list
            if "_manifest.json" in str(call)
        ]
        assert len(manifest_calls) == 1

    async def test_no_manifest_when_no_attachments(
        self, email_service, mock_graph_api, mock_s3_connector
    ) -> None:
        """No manifest is created when the email has no attachments."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["attachments"] = []
        email_response["hasAttachments"] = False
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        # Only 1 upload call: raw email (no attachment, no manifest)
        assert mock_s3_connector.upload_file.call_count == 1


class TestRelevanceFilter:
    """Tests for the pre-pipeline relevance filter.

    Verifies that "hello"-only emails, auto-replies, unknown senders,
    and other noise are rejected before reaching SQS / Bedrock.
    """

    async def test_hello_only_email_rejected(
        self, email_service, mock_graph_api, mock_sqs_connector
    ) -> None:
        """A known vendor sending just 'hello' is rejected (too short)."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["subject"] = "hi"
        email_response["body"] = {"contentType": "text", "content": "hello"}
        email_response["bodyPreview"] = "hello"
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is None
        mock_sqs_connector.send_message.assert_not_called()

    async def test_unknown_sender_rejected_with_auto_reply(
        self, email_service, mock_salesforce, mock_graph_api, mock_sqs_connector
    ) -> None:
        """Unresolved vendor + non-allowlisted domain rejects and auto-replies."""
        mock_salesforce.identify_vendor.return_value = None

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is None
        mock_sqs_connector.send_message.assert_not_called()
        # Auto-reply asking for details is sent to the sender
        mock_graph_api.send_email.assert_called_once()

    async def test_allowlisted_domain_bypasses_sender_check(
        self, mock_graph_api, mock_postgres, mock_s3_connector,
        mock_sqs_connector, mock_eventbridge_connector, mock_salesforce,
        mock_settings,
    ) -> None:
        """Unresolved vendor from an allowlisted domain still goes through."""
        mock_settings.email_filter_allowed_sender_domains = ["technova.com"]
        mock_salesforce.identify_vendor.return_value = None
        service = EmailIntakeService(
            graph_api=mock_graph_api,
            postgres=mock_postgres,
            s3=mock_s3_connector,
            sqs=mock_sqs_connector,
            eventbridge=mock_eventbridge_connector,
            salesforce=mock_salesforce,
            settings=mock_settings,
        )

        result = await service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        mock_sqs_connector.send_message.assert_called_once()

    async def test_auto_submitted_header_rejected(
        self, email_service, mock_graph_api, mock_sqs_connector
    ) -> None:
        """Email with Auto-Submitted header is dropped silently."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["internetMessageHeaders"] = [
            {"name": "Auto-Submitted", "value": "auto-replied"},
        ]
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is None
        mock_sqs_connector.send_message.assert_not_called()
        mock_graph_api.send_email.assert_not_called()  # silent drop

    async def test_out_of_office_subject_rejected(
        self, email_service, mock_graph_api, mock_sqs_connector
    ) -> None:
        """'Out of office' subject prefix is rejected even without headers."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["subject"] = "Out of office: back Monday"
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is None
        mock_sqs_connector.send_message.assert_not_called()

    async def test_newsletter_with_list_unsubscribe_rejected(
        self, email_service, mock_graph_api, mock_sqs_connector
    ) -> None:
        """List-Unsubscribe header marks the message as bulk mail — dropped."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["internetMessageHeaders"] = [
            {"name": "List-Unsubscribe", "value": "<mailto:unsub@example.com>"},
        ]
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is None
        mock_sqs_connector.send_message.assert_not_called()

    async def test_valid_query_passes_filter(
        self, email_service, mock_sqs_connector
    ) -> None:
        """A real invoice query (default conftest email) passes through."""
        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        mock_sqs_connector.send_message.assert_called_once()


class TestThreadCorrelation:
    """Tests for thread status determination."""

    async def test_new_thread_when_no_conversation_id(
        self, email_service, mock_graph_api
    ) -> None:
        """No conversationId in email results in NEW thread status."""
        email_response = mock_graph_api.fetch_email.return_value.copy()
        email_response["conversationId"] = None
        mock_graph_api.fetch_email.return_value = email_response

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        assert result.thread_status == "NEW"

    async def test_existing_open_when_conversation_found(
        self, email_service, mock_postgres
    ) -> None:
        """ConversationId found with open status returns EXISTING_OPEN."""
        mock_postgres.fetchrow.return_value = {
            "query_id": "VQ-2026-0001",
            "status": "ANALYZING",
        }

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        assert result.thread_status == "EXISTING_OPEN"

    async def test_reply_to_closed_when_conversation_closed(
        self, email_service, mock_postgres
    ) -> None:
        """ConversationId found with CLOSED status returns REPLY_TO_CLOSED."""
        mock_postgres.fetchrow.return_value = {
            "query_id": "VQ-2026-0001",
            "status": "CLOSED",
        }

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        assert result is not None
        assert result.thread_status == "REPLY_TO_CLOSED"
