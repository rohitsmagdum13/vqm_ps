"""Module: services/email_intake/storage.py

S3 raw email storage and PostgreSQL metadata writes.

Handles storing the raw email JSON in S3, writing email metadata
and attachment metadata to PostgreSQL, and creating the initial
case execution record.
"""

from __future__ import annotations

import orjson
import structlog

from config.s3_paths import (
    FILENAME_RAW_EMAIL,
    S3_PREFIX_INBOUND_EMAILS,
    build_s3_key,
)
from config.settings import Settings
from models.email import EmailAttachment
from storage.s3_client import S3Connector

logger = structlog.get_logger(__name__)


def _jsonb(value: object) -> str:
    """Serialize a value to a JSON string for asyncpg JSONB binding.

    asyncpg expects JSONB parameters to be a JSON text; None stays None.
    orjson is already a project dependency and handles defaults cleanly.
    """
    if value is None:
        return None  # type: ignore[return-value]
    return orjson.dumps(value).decode("utf-8")


class EmailStorage:
    """Handles S3 and PostgreSQL storage for ingested emails.

    Stores raw email JSON in S3 and writes metadata records
    to intake.email_messages, intake.email_attachments, and
    workflow.case_execution tables.
    """

    def __init__(
        self,
        postgres: object,
        s3: S3Connector,
        settings: Settings,
    ) -> None:
        """Initialize with storage connectors.

        Args:
            postgres: PostgresConnector for database writes.
            s3: S3 connector for raw email storage.
            settings: Application settings (bucket name).
        """
        self._postgres = postgres
        self._s3 = s3
        self._settings = settings

    async def store_raw_email(
        self, raw_email: dict, query_id: str, correlation_id: str
    ) -> str | None:
        """Store the raw email JSON in S3. Non-critical — returns None on failure.

        Uses the single-bucket architecture: all files go to
        s3_bucket_data_store with prefix-based organization.
        Key pattern: inbound-emails/VQ-YYYY-NNNN/raw_email.json
        """
        try:
            import orjson

            raw_bytes = orjson.dumps(raw_email)
            key = build_s3_key(S3_PREFIX_INBOUND_EMAILS, query_id, FILENAME_RAW_EMAIL)
            await self._s3.upload_file(
                bucket=self._settings.s3_bucket_data_store,
                key=key,
                body=raw_bytes,
                content_type="application/json",
                correlation_id=correlation_id,
            )
            return key
        except Exception:
            logger.warning(
                "Failed to store raw email in S3 — continuing",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return None

    async def persist_email_atomically(
        self,
        *,
        message_id: str,
        query_id: str,
        execution_id: str,
        correlation_id: str,
        parsed: dict,
        s3_raw_key: str | None,
        vendor_id: str | None,
        vendor_match_method: str | None,
        thread_status: str,
        attachments: list[EmailAttachment],
        now: object,
        outbox_queue_url: str,
        outbox_payload: dict,
    ) -> None:
        """Persist email metadata + attachments + case execution + outbox
        row in a single database transaction.

        If any step fails, the whole transaction rolls back, so the
        system never ends up with a case_execution row but no SQS
        message (or vice versa). The outbox row carries the SQS payload;
        the caller attempts publication immediately after this returns,
        and a drainer picks up anything left behind.

        Args:
            message_id: Exchange Online message ID.
            query_id: VQ-YYYY-NNNN.
            execution_id: case_execution.execution_id.
            correlation_id: Tracing ID.
            parsed: Parser output (sender, subject, body, headers, ...).
            s3_raw_key: S3 key where the raw email JSON is stored (or None).
            vendor_id: Resolved vendor or None.
            vendor_match_method: How vendor was resolved.
            thread_status: NEW | EXISTING_OPEN | REPLY_TO_CLOSED.
            attachments: Result of AttachmentProcessor.process_attachments.
            now: Timestamp used for received_at/parsed_at/created_at.
            outbox_queue_url: SQS queue URL the payload will be published to.
            outbox_payload: Dict payload to be sent to SQS.
        """
        async with self._postgres.transaction() as tx:
            # intake.email_messages
            await tx.execute(
                """
                INSERT INTO intake.email_messages
                (message_id, query_id, correlation_id, sender_email, sender_name,
                 subject, body_text, body_html, received_at, parsed_at,
                 in_reply_to, conversation_id, thread_status, vendor_id,
                 vendor_match_method, s3_raw_email_key, source, created_at,
                 to_recipients, cc_recipients, bcc_recipients, reply_to,
                 importance, has_attachments, web_link, internet_message_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18,
                        $19, $20, $21, $22, $23, $24, $25, $26)
                """,
                message_id,
                query_id,
                correlation_id,
                parsed["sender_email"],
                parsed.get("sender_name"),
                parsed["subject"],
                parsed.get("body_text", ""),
                parsed.get("body_html"),
                now,
                now,
                parsed.get("in_reply_to"),
                parsed.get("conversation_id"),
                thread_status,
                vendor_id,
                vendor_match_method,
                s3_raw_key,
                "email",
                now,
                _jsonb(parsed.get("to_recipients") or []),
                _jsonb(parsed.get("cc_recipients") or []),
                _jsonb(parsed.get("bcc_recipients") or []),
                _jsonb(parsed.get("reply_to") or []),
                parsed.get("importance"),
                bool(parsed.get("has_attachments", False)),
                parsed.get("web_link"),
                parsed.get("internet_message_id"),
            )

            # intake.email_attachments (per-row so one bad row doesn't
            # kill the whole transaction — but still within the same
            # txn so a failure after the INSERT above rolls both back).
            for att in attachments:
                await tx.execute(
                    """
                    INSERT INTO intake.email_attachments
                    (message_id, query_id, attachment_id, filename, content_type,
                     size_bytes, s3_key, extracted_text, extraction_status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (attachment_id) DO NOTHING
                    """,
                    message_id,
                    query_id,
                    att.attachment_id,
                    att.filename,
                    att.content_type,
                    att.size_bytes,
                    att.s3_key,
                    att.extracted_text[:5000] if att.extracted_text else None,
                    att.extraction_status,
                )

            # workflow.case_execution
            await tx.execute(
                """
                INSERT INTO workflow.case_execution
                (query_id, correlation_id, execution_id, vendor_id, source, status,
                 created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                query_id,
                correlation_id,
                execution_id,
                vendor_id,
                "email",
                "RECEIVED",
                now,
                now,
            )

            # cache.outbox_events — the SQS payload, staged for publish.
            # Queue_url + payload go to DB first; caller publishes right
            # after commit; drainer cleans up anything that didn't make it.
            await self._postgres.enqueue_outbox(
                tx,
                event_key=query_id,
                queue_url=outbox_queue_url,
                payload=outbox_payload,
            )

        logger.info(
            "Email persisted atomically",
            query_id=query_id,
            attachment_count=len(attachments),
            correlation_id=correlation_id,
        )
