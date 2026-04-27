"""Module: services/portal_intake/attachment_processor.py

Validates, stores, and extracts text from portal-uploaded files.

Mirrors the email-path attachment_processor but takes FastAPI
UploadFile objects instead of MIME parts. Each file is uploaded
to S3 first (so Textract can read it from there) before text
extraction is attempted.

A row is written to intake.portal_query_attachments for every file
processed, regardless of extraction outcome — the admin UI shows
the user exactly which files were stored, which were extracted, and
how (textract / pdfplumber / openpyxl / python_docx / decode).
"""

from __future__ import annotations

from pathlib import PurePosixPath

import structlog
from fastapi import UploadFile

from config.s3_paths import S3_PREFIX_ATTACHMENTS, build_s3_key
from config.settings import Settings
from models.query import QueryAttachment
from services.attachment_manifest import AttachmentManifestBuilder
from services.portal_intake.text_extractor import TextExtractor
from storage.s3_client import S3Connector

logger = structlog.get_logger(__name__)


# Same guardrails as the email path — keep the values consistent so a
# vendor sees identical limits whether they email a file or upload it.
BLOCKED_EXTENSIONS: frozenset[str] = frozenset({".exe", ".bat", ".cmd", ".ps1", ".sh", ".js"})
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB per file
MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB total
MAX_ATTACHMENT_COUNT = 10


class PortalAttachmentProcessor:
    """Validates portal-uploaded files, stores them in S3, and extracts text."""

    def __init__(
        self,
        s3: S3Connector,
        text_extractor: TextExtractor,
        postgres: object,  # PostgresConnector
        settings: Settings,
    ) -> None:
        """Initialize with the connectors needed end-to-end.

        Args:
            s3: S3 connector for uploading the binary.
            text_extractor: Extractor that picks Textract or library fallbacks.
            postgres: PostgreSQL connector for the per-attachment row.
            settings: Application settings (bucket name).
        """
        self._s3 = s3
        self._text_extractor = text_extractor
        self._postgres = postgres
        self._settings = settings

    async def process(
        self,
        files: list[UploadFile],
        query_id: str,
        correlation_id: str,
    ) -> list[QueryAttachment]:
        """Process all uploaded files for a query.

        Returns the list of QueryAttachment models in submission order.
        Files that fail validation are returned with extraction_status
        set to 'skipped' or 'failed' rather than being dropped silently
        — the vendor UI shows them so the user can re-upload.
        """
        if not files:
            return []

        bucket = self._settings.s3_bucket_data_store.strip()
        results: list[QueryAttachment] = []
        total_size = 0

        for i, upload in enumerate(files[:MAX_ATTACHMENT_COUNT]):
            filename = upload.filename or f"attachment_{i}"
            content_type = upload.content_type or "application/octet-stream"
            att_id = f"ATT-{i + 1:03d}"

            # Read the bytes once. Starlette UploadFile is async-friendly,
            # but we need the bytes both for size check and for fallback
            # parsers, so we materialize the whole thing here. The 10 MB
            # cap below keeps memory bounded.
            try:
                content_bytes = await upload.read()
            except Exception:
                logger.warning(
                    "Could not read uploaded file",
                    file_name=filename,
                    correlation_id=correlation_id,
                )
                results.append(
                    QueryAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=0,
                        extraction_status="failed",
                        extraction_method="none",
                    )
                )
                continue

            size_bytes = len(content_bytes)
            ext = PurePosixPath(filename).suffix.lower()

            if ext in BLOCKED_EXTENSIONS:
                logger.warning(
                    "Blocked extension on portal upload",
                    file_name=filename,
                    ext=ext,
                    correlation_id=correlation_id,
                )
                results.append(
                    QueryAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        extraction_status="skipped",
                        extraction_method="none",
                    )
                )
                continue

            if size_bytes > MAX_ATTACHMENT_SIZE:
                logger.warning(
                    "Oversized portal upload skipped",
                    file_name=filename,
                    size_bytes=size_bytes,
                    correlation_id=correlation_id,
                )
                results.append(
                    QueryAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        extraction_status="skipped",
                        extraction_method="none",
                    )
                )
                continue

            total_size += size_bytes
            if total_size > MAX_TOTAL_SIZE:
                logger.warning(
                    "Total upload size exceeded — skipping remaining files",
                    total_size=total_size,
                    correlation_id=correlation_id,
                )
                break

            s3_key = build_s3_key(
                S3_PREFIX_ATTACHMENTS, query_id, f"{att_id}_{filename}"
            )

            try:
                await self._s3.upload_file(
                    bucket=bucket,
                    key=s3_key,
                    body=content_bytes,
                    content_type=content_type,
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "S3 upload failed for portal attachment",
                    file_name=filename,
                    correlation_id=correlation_id,
                )
                results.append(
                    QueryAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        extraction_status="failed",
                        extraction_method="none",
                    )
                )
                continue

            extracted_text, method = await self._text_extractor.extract(
                content=content_bytes,
                content_type=content_type,
                filename=filename,
                bucket=bucket,
                s3_key=s3_key,
                correlation_id=correlation_id,
            )

            attachment = QueryAttachment(
                attachment_id=att_id,
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                s3_key=s3_key,
                extracted_text=extracted_text,
                extraction_status="success" if extracted_text else "failed",
                extraction_method=method,
            )
            results.append(attachment)

            await self._record_attachment(query_id, attachment, correlation_id)

        # Manifest is non-critical; the helper handles its own failures.
        await AttachmentManifestBuilder.store_manifest(
            s3=self._s3,
            settings=self._settings,
            query_id=query_id,
            attachments=[self._as_email_attachment(a) for a in results],
            correlation_id=correlation_id,
        )

        return results

    async def _record_attachment(
        self,
        query_id: str,
        attachment: QueryAttachment,
        correlation_id: str,
    ) -> None:
        """Insert one row into intake.portal_query_attachments. Best-effort."""
        try:
            await self._postgres.execute(
                """
                INSERT INTO intake.portal_query_attachments
                    (query_id, attachment_id, filename, content_type,
                     size_bytes, s3_key, extracted_text, extraction_status,
                     extraction_method)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (query_id, attachment_id) DO NOTHING
                """,
                query_id,
                attachment.attachment_id,
                attachment.filename,
                attachment.content_type,
                attachment.size_bytes,
                attachment.s3_key,
                attachment.extracted_text,
                attachment.extraction_status,
                attachment.extraction_method,
            )
        except Exception:
            logger.warning(
                "Failed to persist portal attachment row — continuing",
                query_id=query_id,
                attachment_id=attachment.attachment_id,
                correlation_id=correlation_id,
            )

    @staticmethod
    def _as_email_attachment(att: QueryAttachment):
        """Build the EmailAttachment-shape object the manifest builder expects.

        AttachmentManifestBuilder is shared with the email path. Rather
        than duplicate it, we adapt our QueryAttachment to the fields it
        reads. Done locally to avoid an import cycle.
        """
        from models.email import EmailAttachment

        return EmailAttachment(
            attachment_id=att.attachment_id,
            filename=att.filename,
            content_type=att.content_type,
            size_bytes=att.size_bytes,
            s3_key=att.s3_key,
            extracted_text=att.extracted_text,
            extraction_status=att.extraction_status,
        )
