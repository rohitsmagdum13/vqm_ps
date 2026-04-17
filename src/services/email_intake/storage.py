"""Module: services/email_intake/storage.py

S3 raw email storage and PostgreSQL metadata writes.

Handles storing the raw email JSON in S3, writing email metadata
and attachment metadata to PostgreSQL, and creating the initial
case execution record.
"""

from __future__ import annotations

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

    async def store_email_metadata(
        self,
        *,
        message_id: str,
        query_id: str,
        correlation_id: str,
        parsed: dict,
        s3_raw_key: str | None,
        vendor_id: str | None,
        vendor_match_method: str | None,
        thread_status: str,
        now: object,
    ) -> None:
        """Write email metadata to intake.email_messages table."""
        await self._postgres.execute(
            """
            INSERT INTO intake.email_messages
            (message_id, query_id, correlation_id, sender_email, sender_name,
             subject, body_text, body_html, received_at, parsed_at,
             in_reply_to, conversation_id, thread_status, vendor_id,
             vendor_match_method, s3_raw_email_key, source, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18)
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
        )

    async def store_attachment_metadata(
        self,
        *,
        message_id: str,
        query_id: str,
        attachments: list[EmailAttachment],
        correlation_id: str,
    ) -> None:
        """Write each attachment's metadata to intake.email_attachments.

        Non-critical — if a single attachment INSERT fails, log and
        continue with the rest.
        """
        if not attachments:
            return

        for att in attachments:
            try:
                await self._postgres.execute(
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
            except Exception:
                logger.warning(
                    "Failed to store attachment metadata — continuing",
                    attachment_id=att.attachment_id,
                    filename=att.filename,
                    query_id=query_id,
                    correlation_id=correlation_id,
                )

        logger.info(
            "Attachment metadata stored",
            query_id=query_id,
            attachment_count=len(attachments),
            correlation_id=correlation_id,
        )

    async def create_case_execution(
        self,
        *,
        query_id: str,
        correlation_id: str,
        execution_id: str,
        vendor_id: str | None,
        now: object,
    ) -> None:
        """Create a new case execution record in workflow.case_execution."""
        await self._postgres.execute(
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
