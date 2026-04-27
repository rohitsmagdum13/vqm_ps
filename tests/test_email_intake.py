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
        """Email metadata, attachment metadata, case execution + outbox
        row are written in a single transaction."""
        await email_service.process_email("AAMkAGI2TG93AAA=")

        # Claim-check is the first DB hit.
        assert mock_postgres.check_idempotency.call_count == 1

        # Writes are now inside postgres.transaction() — inspect the
        # connection mock attached to the fixture. Three go through
        # tx.execute directly, one goes through postgres.enqueue_outbox
        # (which in real code also uses the tx conn, but as a method
        # call on the connector).
        tx_conn = mock_postgres.transaction.tx_conn
        assert tx_conn.execute.call_count == 3  # email_messages, attachments, case_execution
        mock_postgres.enqueue_outbox.assert_called_once()  # outbox row in same txn

        # Happy path must finalize the claim.
        mock_postgres.mark_idempotency_complete.assert_called_once()

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


class TestClaimCheckIdempotency:
    """Verify the claim-check pattern actually protects against email loss."""

    async def test_happy_path_marks_idempotency_complete(
        self, email_service, mock_postgres
    ) -> None:
        """Successful ingestion must flip the claim to COMPLETED."""
        await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_postgres.mark_idempotency_complete.assert_called_once()
        # Release must NOT be called on the happy path.
        mock_postgres.release_idempotency_claim.assert_not_called()

    async def test_fetch_failure_releases_claim(
        self, email_service, mock_postgres, mock_graph_api
    ) -> None:
        """If fetch_email crashes, the claim is released so retry works."""
        mock_graph_api.fetch_email.side_effect = Exception("Graph 500")

        with pytest.raises(Exception, match="Graph 500"):
            await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_postgres.release_idempotency_claim.assert_called_once()
        mock_postgres.mark_idempotency_complete.assert_not_called()

    async def test_db_failure_releases_claim(
        self, email_service, mock_postgres
    ) -> None:
        """If the atomic DB write raises, the claim is released."""
        # Make the transaction's execute blow up on commit attempts.
        tx_conn = mock_postgres.transaction.tx_conn
        tx_conn.execute.side_effect = Exception("DB down")

        with pytest.raises(Exception, match="DB down"):
            await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_postgres.release_idempotency_claim.assert_called_once()

    async def test_duplicate_does_not_release_claim(
        self, email_service, mock_postgres
    ) -> None:
        """A refused claim (duplicate/in-flight) must not touch release."""
        mock_postgres.check_idempotency.return_value = False

        await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_postgres.release_idempotency_claim.assert_not_called()
        mock_postgres.mark_idempotency_complete.assert_not_called()


class TestOutboxPublish:
    """SQS publish failures must not lose the message — outbox holds it."""

    async def test_sqs_failure_is_recoverable(
        self, email_service, mock_postgres, mock_sqs_connector
    ) -> None:
        """SQS failure after DB commit → claim still COMPLETED, drainer retries.

        The outbox row is durably in the DB (we already committed the
        transaction), so the message is not lost. We mark the claim
        COMPLETED so retries don't re-create the case_execution, and
        we record the failure on the outbox row for the drainer.
        """
        mock_sqs_connector.send_message.side_effect = Exception("SQS throttled")

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        # Pipeline completes successfully — the data is in the DB.
        assert result is not None
        # Claim finalized despite SQS failure (outbox is the source of truth).
        mock_postgres.mark_idempotency_complete.assert_called_once()
        # Failure recorded on the outbox row for diagnostics.
        mock_postgres.record_outbox_failure.assert_called_once()
        # And NOT marked sent, so the drainer will pick it up.
        mock_postgres.mark_outbox_sent.assert_not_called()

    async def test_sqs_success_marks_outbox_sent(
        self, email_service, mock_postgres
    ) -> None:
        """Happy path flips outbox row's sent_at."""
        await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_postgres.mark_outbox_sent.assert_called_once()
        mock_postgres.record_outbox_failure.assert_not_called()


class TestMarkAsReadAfterProcessing:
    """Verify emails are marked read on all three exit paths.

    Without mark_as_read the reconciliation poller's 'isRead eq false'
    filter would re-surface already-processed mail on every cycle.
    """

    async def test_happy_path_marks_email_as_read(
        self, email_service, mock_graph_api
    ) -> None:
        """Successful SQS enqueue is followed by mark_as_read(message_id)."""
        await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_graph_api.mark_as_read.assert_called_once()
        call_args = mock_graph_api.mark_as_read.call_args
        assert call_args.args[0] == "AAMkAGI2TG93AAA="

    async def test_duplicate_still_marks_as_read(
        self, email_service, mock_postgres, mock_graph_api
    ) -> None:
        """Duplicate emails are still marked read (defensive)."""
        mock_postgres.check_idempotency.return_value = False

        await email_service.process_email("AAMkAGI2TG93AAA=")

        mock_graph_api.mark_as_read.assert_called_once()

    async def test_mark_as_read_failure_does_not_break_pipeline(
        self, email_service, mock_graph_api
    ) -> None:
        """A failing mark_as_read does not roll back a successful ingestion."""
        mock_graph_api.mark_as_read.side_effect = Exception("Graph 500")

        result = await email_service.process_email("AAMkAGI2TG93AAA=")

        # Pipeline result is still the parsed payload, not None/error.
        assert result is not None


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


# ---------------------------------------------------------------------------
# Follow-up info handling — EXISTING_OPEN reply that is NOT a confirmation
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_closure_service() -> AsyncMock:
    """Mock ClosureService for follow-up wiring tests."""
    svc = AsyncMock()
    svc.detect_confirmation.return_value = False
    svc.handle_reopen.return_value = "SKIPPED"
    svc.handle_followup_info.return_value = "MERGED_MID_PIPELINE"
    return svc


@pytest.fixture
def email_service_with_closure(
    mock_graph_api,
    mock_postgres,
    mock_s3_connector,
    mock_sqs_connector,
    mock_eventbridge_connector,
    mock_salesforce,
    mock_settings,
    mock_closure_service,
) -> EmailIntakeService:
    """EmailIntakeService wired with a ClosureService mock so the
    follow-up branch of _run_closure_detection actually runs."""
    return EmailIntakeService(
        graph_api=mock_graph_api,
        postgres=mock_postgres,
        s3=mock_s3_connector,
        sqs=mock_sqs_connector,
        eventbridge=mock_eventbridge_connector,
        salesforce=mock_salesforce,
        settings=mock_settings,
        closure_service=mock_closure_service,
    )


class TestFollowupReplyHandling:
    """The vendor replies in the same thread with a missing PDF / extra info.

    Verifies the email_intake → closure_service hand-off:
      - EXISTING_OPEN that is not a confirmation → handle_followup_info
        is invoked with the new query_id, body, and attachment summary.
      - A confirmation reply still short-circuits before the follow-up
        handler runs (regression).
      - REPLY_TO_CLOSED still goes through handle_reopen, not the
        follow-up handler.
    """

    async def test_existing_open_non_confirmation_calls_handle_followup_info(
        self,
        email_service_with_closure,
        mock_postgres,
        mock_closure_service,
    ) -> None:
        """An open thread + non-confirmation body triggers the merge call."""
        # Thread correlator fetches the open case row.
        mock_postgres.fetchrow.return_value = {
            "query_id": "VQ-PRIOR",
            "status": "ANALYZING",
        }
        mock_closure_service.detect_confirmation.return_value = False

        result = await email_service_with_closure.process_email(
            "AAMkAGI2TG93AAA="
        )

        assert result is not None
        assert result.thread_status == "EXISTING_OPEN"
        mock_closure_service.handle_followup_info.assert_awaited_once()
        kwargs = mock_closure_service.handle_followup_info.await_args.kwargs
        assert kwargs["new_query_id"] == result.query_id
        assert kwargs["conversation_id"] == "AAQkAGI2TG93conv="
        # Attachments are summarised (not raw EmailAttachment objects).
        assert isinstance(kwargs["attachments_summary"], list)
        assert all(
            isinstance(a, dict) and "filename" in a
            for a in kwargs["attachments_summary"]
        )
        # Reopen path must NOT fire on EXISTING_OPEN.
        mock_closure_service.handle_reopen.assert_not_awaited()

    async def test_confirmation_reply_skips_followup_handler(
        self,
        email_service_with_closure,
        mock_postgres,
        mock_closure_service,
    ) -> None:
        """If detect_confirmation returns True, the merge path is skipped."""
        mock_postgres.fetchrow.return_value = {
            "query_id": "VQ-PRIOR",
            "status": "AWAITING_RESOLUTION",
        }
        mock_closure_service.detect_confirmation.return_value = True

        await email_service_with_closure.process_email("AAMkAGI2TG93AAA=")

        mock_closure_service.detect_confirmation.assert_awaited_once()
        mock_closure_service.handle_followup_info.assert_not_awaited()
        mock_closure_service.handle_reopen.assert_not_awaited()

    async def test_reply_to_closed_skips_followup_handler(
        self,
        email_service_with_closure,
        mock_postgres,
        mock_closure_service,
    ) -> None:
        """REPLY_TO_CLOSED still uses handle_reopen, never handle_followup_info."""
        mock_postgres.fetchrow.return_value = {
            "query_id": "VQ-PRIOR",
            "status": "CLOSED",
        }
        mock_closure_service.detect_confirmation.return_value = False

        await email_service_with_closure.process_email("AAMkAGI2TG93AAA=")

        mock_closure_service.handle_reopen.assert_awaited_once()
        mock_closure_service.handle_followup_info.assert_not_awaited()

    async def test_followup_handler_failure_does_not_break_pipeline(
        self,
        email_service_with_closure,
        mock_postgres,
        mock_closure_service,
    ) -> None:
        """A crash inside handle_followup_info is swallowed (non-critical)."""
        mock_postgres.fetchrow.return_value = {
            "query_id": "VQ-PRIOR",
            "status": "ANALYZING",
        }
        mock_closure_service.detect_confirmation.return_value = False
        mock_closure_service.handle_followup_info.side_effect = RuntimeError(
            "merge boom"
        )

        # Pipeline must still return a parsed payload — the email is
        # already durably persisted, the follow-up merge is best-effort.
        result = await email_service_with_closure.process_email(
            "AAMkAGI2TG93AAA="
        )
        assert result is not None
        assert result.thread_status == "EXISTING_OPEN"
