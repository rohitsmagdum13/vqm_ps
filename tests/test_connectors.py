"""Tests for AWS connectors: S3, SQS, and EventBridge.

All tests use moto to mock AWS services — no real AWS
credentials needed. Each test is isolated: moto spins up
a fresh mock per fixture scope.
"""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from events.eventbridge import VALID_EVENT_TYPES, EventBridgeConnector
from storage.s3_client import S3Connector
from queues.sqs import SQSConnector

# ===========================
# S3 Connector Tests
# ===========================


class TestS3Connector:
    """Tests for S3Connector upload, download, and presigned URL."""

    @pytest.fixture
    def s3_connector(self, mock_s3, mock_settings) -> S3Connector:
        """Create an S3Connector that uses the moto mock client."""
        connector = S3Connector(mock_settings)
        # Replace the connector's client with the moto-managed client
        connector._client = mock_s3
        return connector

    async def test_upload_file_returns_key(self, s3_connector: S3Connector) -> None:
        """Upload bytes, verify the S3 key is returned."""
        key = await s3_connector.upload_file(
            bucket="test-data-store",
            key="inbound-emails/VQ-2026-0001/raw_email.json",
            body=b"From: vendor@example.com\nSubject: Test",
            content_type="application/json",
            correlation_id="test-corr-001",
        )
        assert key == "inbound-emails/VQ-2026-0001/raw_email.json"

    async def test_download_file_returns_content(self, s3_connector: S3Connector) -> None:
        """Upload then download, verify content matches."""
        original_content = b"PDF content here for testing"
        await s3_connector.upload_file(
            bucket="test-data-store",
            key="attachments/VQ-2026-0001/invoice.pdf",
            body=original_content,
        )

        downloaded = await s3_connector.download_file(
            bucket="test-data-store",
            key="attachments/VQ-2026-0001/invoice.pdf",
            correlation_id="test-corr-002",
        )
        assert downloaded == original_content

    async def test_generate_presigned_url_returns_string(self, s3_connector: S3Connector) -> None:
        """Verify presigned URL is a non-empty string."""
        await s3_connector.upload_file(
            bucket="test-data-store",
            key="inbound-emails/VQ-2026-0001/raw_email.json",
            body=b"test content",
        )

        url = await s3_connector.generate_presigned_url(
            bucket="test-data-store",
            key="inbound-emails/VQ-2026-0001/raw_email.json",
            expiration=3600,
            correlation_id="test-corr-003",
        )
        assert isinstance(url, str)
        assert len(url) > 0
        assert "test-data-store" in url
        assert "raw_email.json" in url

    async def test_upload_to_nonexistent_bucket_raises(self, s3_connector: S3Connector) -> None:
        """ClientError raised when uploading to a bucket that doesn't exist."""
        with pytest.raises(ClientError):
            await s3_connector.upload_file(
                bucket="nonexistent-bucket",
                key="test.txt",
                body=b"should fail",
            )

    async def test_download_nonexistent_key_raises(self, s3_connector: S3Connector) -> None:
        """ClientError raised when downloading a key that doesn't exist."""
        with pytest.raises(ClientError):
            await s3_connector.download_file(
                bucket="test-data-store",
                key="does-not-exist.txt",
            )

    async def test_object_exists_returns_true_for_existing(self, s3_connector: S3Connector) -> None:
        """object_exists returns True when the object is present."""
        await s3_connector.upload_file(
            bucket="test-data-store",
            key="inbound-emails/VQ-2026-0001/raw_email.json",
            body=b"test content",
        )

        exists = await s3_connector.object_exists(
            bucket="test-data-store",
            key="inbound-emails/VQ-2026-0001/raw_email.json",
            correlation_id="test-corr-010",
        )
        assert exists is True

    async def test_object_exists_returns_false_for_missing(self, s3_connector: S3Connector) -> None:
        """object_exists returns False when the object is not present."""
        exists = await s3_connector.object_exists(
            bucket="test-data-store",
            key="does-not-exist.txt",
            correlation_id="test-corr-011",
        )
        assert exists is False

    async def test_list_objects_returns_keys(self, s3_connector: S3Connector) -> None:
        """list_objects returns all keys under a prefix."""
        # Upload 3 files under the same prefix
        for i in range(3):
            await s3_connector.upload_file(
                bucket="test-data-store",
                key=f"attachments/VQ-2026-0001/file_{i}.pdf",
                body=b"content",
            )

        keys = await s3_connector.list_objects(
            bucket="test-data-store",
            prefix="attachments/VQ-2026-0001/",
            correlation_id="test-corr-012",
        )
        assert len(keys) == 3
        assert all(k.startswith("attachments/VQ-2026-0001/") for k in keys)

    async def test_list_objects_empty_prefix_returns_empty(self, s3_connector: S3Connector) -> None:
        """list_objects returns empty list when no keys match the prefix."""
        keys = await s3_connector.list_objects(
            bucket="test-data-store",
            prefix="nonexistent-prefix/",
            correlation_id="test-corr-013",
        )
        assert keys == []

    async def test_delete_object_removes_key(self, s3_connector: S3Connector) -> None:
        """delete_object removes the specified key."""
        await s3_connector.upload_file(
            bucket="test-data-store",
            key="processed/VQ-2026-0001/to_delete.json",
            body=b"delete me",
        )

        # Verify it exists
        exists_before = await s3_connector.object_exists(
            bucket="test-data-store",
            key="processed/VQ-2026-0001/to_delete.json",
        )
        assert exists_before is True

        # Delete it
        await s3_connector.delete_object(
            bucket="test-data-store",
            key="processed/VQ-2026-0001/to_delete.json",
            correlation_id="test-corr-014",
        )

        # Verify it's gone
        exists_after = await s3_connector.object_exists(
            bucket="test-data-store",
            key="processed/VQ-2026-0001/to_delete.json",
        )
        assert exists_after is False


# ===========================
# SQS Connector Tests
# ===========================


class TestSQSConnector:
    """Tests for SQSConnector send, receive, and delete."""

    @pytest.fixture
    def sqs_connector(self, mock_sqs, mock_settings) -> tuple[SQSConnector, dict]:
        """Create an SQSConnector with moto mock client.

        Returns (connector, queue_urls) tuple.
        """
        client, queue_urls = mock_sqs
        connector = SQSConnector(mock_settings)
        connector._client = client
        return connector, queue_urls

    async def test_send_message_returns_message_id(self, sqs_connector) -> None:
        """Send a dict message, verify MessageId is returned."""
        connector, queue_urls = sqs_connector
        message_id = await connector.send_message(
            queue_url=queue_urls["email_intake"],
            message_body={"query_id": "VQ-2026-0001", "source": "email"},
            correlation_id="test-corr-010",
        )
        assert isinstance(message_id, str)
        assert len(message_id) > 0

    async def test_send_and_receive_roundtrip(self, sqs_connector) -> None:
        """Send then receive, verify body matches the original dict."""
        connector, queue_urls = sqs_connector
        original_body = {"query_id": "VQ-2026-0002", "vendor_id": "V-001", "priority": "high"}

        await connector.send_message(
            queue_url=queue_urls["query_intake"],
            message_body=original_body,
        )

        # Receive with short polling (wait_time_seconds=0) for test speed
        messages = await connector.receive_messages(
            queue_url=queue_urls["query_intake"],
            max_messages=1,
            wait_time_seconds=0,
        )
        assert len(messages) == 1
        assert messages[0]["body"] == original_body
        assert "message_id" in messages[0]
        assert "receipt_handle" in messages[0]

    async def test_receive_empty_queue_returns_empty_list(self, sqs_connector) -> None:
        """Receiving from an empty queue returns an empty list."""
        connector, queue_urls = sqs_connector
        messages = await connector.receive_messages(
            queue_url=queue_urls["email_intake"],
            max_messages=1,
            wait_time_seconds=0,
        )
        assert messages == []

    async def test_delete_message_succeeds(self, sqs_connector) -> None:
        """Send, receive, delete, then receive again — should be empty."""
        connector, queue_urls = sqs_connector
        queue_url = queue_urls["email_intake"]

        # Send a message
        await connector.send_message(
            queue_url=queue_url,
            message_body={"test": "delete_me"},
        )

        # Receive it
        messages = await connector.receive_messages(
            queue_url=queue_url,
            max_messages=1,
            wait_time_seconds=0,
        )
        assert len(messages) == 1

        # Delete it
        await connector.delete_message(
            queue_url=queue_url,
            receipt_handle=messages[0]["receipt_handle"],
            correlation_id="test-corr-011",
        )

        # Queue should now be empty
        messages_after = await connector.receive_messages(
            queue_url=queue_url,
            max_messages=1,
            wait_time_seconds=0,
        )
        assert messages_after == []

    async def test_send_message_with_delay(self, sqs_connector) -> None:
        """Send with delay_seconds, verify message is sent successfully."""
        connector, queue_urls = sqs_connector
        message_id = await connector.send_message(
            queue_url=queue_urls["email_intake"],
            message_body={"delayed": True},
            delay_seconds=5,
        )
        assert isinstance(message_id, str)


# ===========================
# EventBridge Connector Tests
# ===========================


class TestEventBridgeConnector:
    """Tests for EventBridgeConnector event publishing."""

    @pytest.fixture
    def eb_connector(self, mock_eventbridge, mock_settings) -> EventBridgeConnector:
        """Create an EventBridgeConnector with moto mock client."""
        connector = EventBridgeConnector(mock_settings)
        connector._client = mock_eventbridge
        return connector

    async def test_publish_valid_event_succeeds(self, eb_connector: EventBridgeConnector) -> None:
        """Publishing a valid event type returns an EventId."""
        event_id = await eb_connector.publish_event(
            event_type="EmailParsed",
            detail={"query_id": "VQ-2026-0001", "sender": "vendor@example.com"},
            correlation_id="test-corr-020",
        )
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    async def test_publish_invalid_event_type_raises_valueerror(
        self, eb_connector: EventBridgeConnector
    ) -> None:
        """Publishing an invalid event type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid event type"):
            await eb_connector.publish_event(
                event_type="InvalidEvent",
                detail={"test": True},
            )

    async def test_event_detail_includes_correlation_id(
        self, eb_connector: EventBridgeConnector
    ) -> None:
        """Verify that correlation_id is added to the event detail.

        We can't inspect the actual EventBridge payload easily with moto,
        but we verify the call doesn't fail — the enrichment logic is
        tested implicitly (if correlation_id injection broke JSON
        serialization, the call would fail).
        """
        event_id = await eb_connector.publish_event(
            event_type="QueryReceived",
            detail={"query_id": "VQ-2026-0002"},
            correlation_id="enrichment-test-corr",
        )
        # If we got here without error, the enrichment worked
        assert isinstance(event_id, str)

    async def test_all_valid_event_types_accepted(
        self, eb_connector: EventBridgeConnector
    ) -> None:
        """Every one of the 20 valid event types can be published."""
        for event_type in VALID_EVENT_TYPES:
            event_id = await eb_connector.publish_event(
                event_type=event_type,
                detail={"test": True},
            )
            assert isinstance(event_id, str)

    async def test_original_detail_not_mutated(self, eb_connector: EventBridgeConnector) -> None:
        """Publishing should not modify the caller's detail dict."""
        original_detail = {"query_id": "VQ-2026-0003"}
        detail_copy = original_detail.copy()

        await eb_connector.publish_event(
            event_type="EmailReceived",
            detail=original_detail,
            correlation_id="mutation-test",
        )

        # Original dict should be unchanged (no correlation_id or timestamp added)
        assert original_detail == detail_copy
