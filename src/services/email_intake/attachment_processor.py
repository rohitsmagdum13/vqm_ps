"""Module: services/email_intake/attachment_processor.py

Attachment validation, S3 storage, and text extraction.

Processes email attachments: validates against safety guardrails,
stores binary content to S3, extracts text from PDF/Excel/Word/CSV
files, and stores a manifest summarizing all attachments.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import PurePosixPath

import structlog

from config.s3_paths import S3_PREFIX_ATTACHMENTS, build_s3_key
from config.settings import Settings
from models.email import EmailAttachment
from services.attachment_manifest import AttachmentManifestBuilder
from storage.s3_client import S3Connector

logger = structlog.get_logger(__name__)


class AttachmentProcessor:
    """Validates, stores, and extracts text from email attachments.

    Uses the single-bucket S3 architecture with prefix-based
    organization. Enforces safety guardrails (blocked extensions,
    size limits, count limits).
    """

    # Safety guardrails for attachments
    BLOCKED_EXTENSIONS: frozenset[str] = frozenset({".exe", ".bat", ".cmd", ".ps1", ".sh", ".js"})
    MAX_ATTACHMENT_SIZE: int = 10 * 1024 * 1024  # 10 MB per file
    MAX_TOTAL_SIZE: int = 50 * 1024 * 1024  # 50 MB per email
    MAX_ATTACHMENT_COUNT: int = 10
    MAX_EXTRACTED_TEXT_LENGTH: int = 5000

    def __init__(self, s3: S3Connector, settings: Settings) -> None:
        """Initialize with S3 connector and settings.

        Args:
            s3: S3 connector for attachment storage.
            settings: Application settings (bucket name).
        """
        self._s3 = s3
        self._settings = settings

    async def process_attachments(
        self, raw_email: dict, query_id: str, correlation_id: str
    ) -> list[EmailAttachment]:
        """Process all attachments: validate, store to S3, extract text.

        Key pattern: attachments/VQ-YYYY-NNNN/{att_id}_{filename}

        After processing, stores a _manifest.json summarizing all
        attachments for this query.

        Non-critical — returns empty list on total failure, or
        partial results if some attachments fail.
        """
        raw_attachments = raw_email.get("attachments", [])
        if not raw_attachments:
            return []

        results: list[EmailAttachment] = []
        total_size = 0

        for i, att in enumerate(raw_attachments[: self.MAX_ATTACHMENT_COUNT]):
            filename = att.get("name", f"attachment_{i}")
            size_bytes = att.get("size", 0)
            content_type = att.get("contentType", "application/octet-stream")
            att_id = att.get("id", f"ATT-{i:03d}")

            # Check blocked extensions
            ext = PurePosixPath(filename).suffix.lower()
            if ext in self.BLOCKED_EXTENSIONS:
                logger.warning(
                    "Blocked attachment extension",
                    file_name=filename,
                    ext=ext,
                    correlation_id=correlation_id,
                )
                results.append(
                    EmailAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        extraction_status="skipped",
                    )
                )
                continue

            # Check individual file size
            if size_bytes > self.MAX_ATTACHMENT_SIZE:
                logger.warning(
                    "Oversized attachment skipped",
                    file_name=filename,
                    size_bytes=size_bytes,
                    correlation_id=correlation_id,
                )
                results.append(
                    EmailAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        extraction_status="skipped",
                    )
                )
                continue

            # Check total size
            total_size += size_bytes
            if total_size > self.MAX_TOTAL_SIZE:
                logger.warning(
                    "Total attachment size exceeded — skipping remaining",
                    total_size=total_size,
                    correlation_id=correlation_id,
                )
                break

            # Try to decode and store the attachment
            try:
                content_bytes_b64 = att.get("contentBytes", "")
                content_bytes = base64.b64decode(content_bytes_b64) if content_bytes_b64 else b""

                # Store to S3 using single-bucket architecture
                s3_key = build_s3_key(
                    S3_PREFIX_ATTACHMENTS, query_id, f"{att_id}_{filename}"
                )
                await self._s3.upload_file(
                    bucket=self._settings.s3_bucket_data_store,
                    key=s3_key,
                    body=content_bytes,
                    content_type=content_type,
                    correlation_id=correlation_id,
                )

                # Extract text based on content type
                extracted_text = await self._extract_text(content_bytes, content_type, filename)

                results.append(
                    EmailAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        s3_key=s3_key,
                        extracted_text=extracted_text,
                        extraction_status="success" if extracted_text else "failed",
                    )
                )
            except Exception:
                logger.warning(
                    "Attachment processing failed",
                    file_name=filename,
                    correlation_id=correlation_id,
                )
                results.append(
                    EmailAttachment(
                        attachment_id=att_id,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        extraction_status="failed",
                    )
                )

        # Store attachment manifest (non-critical)
        await AttachmentManifestBuilder.store_manifest(
            s3=self._s3,
            settings=self._settings,
            query_id=query_id,
            attachments=results,
            correlation_id=correlation_id,
        )

        return results

    async def _extract_text(
        self, content: bytes, content_type: str, filename: str
    ) -> str | None:
        """Extract text from an attachment based on its type.

        Supports PDF (pdfplumber), Excel (openpyxl), Word (python-docx),
        and CSV/TXT (direct decode). Runs in a thread to avoid blocking.

        Returns text truncated to MAX_EXTRACTED_TEXT_LENGTH chars, or None.
        """
        try:
            ext = PurePosixPath(filename).suffix.lower()

            if ext == ".pdf" or content_type == "application/pdf":
                text = await asyncio.to_thread(self._extract_pdf_text, content)
            elif ext in (".xlsx", ".xls") or "spreadsheet" in content_type:
                text = await asyncio.to_thread(self._extract_excel_text, content)
            elif ext == ".docx" or "wordprocessingml" in content_type:
                text = await asyncio.to_thread(self._extract_docx_text, content)
            elif ext in (".csv", ".txt") or content_type.startswith("text/"):
                text = content.decode("utf-8", errors="replace")
            else:
                # Unsupported type — skip extraction
                return None

            if text:
                return text[: self.MAX_EXTRACTED_TEXT_LENGTH]
            return None
        except Exception:
            logger.warning("Text extraction failed", file_name=filename)
            return None

    @staticmethod
    def _extract_pdf_text(content: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber."""
        import io

        import pdfplumber

        text_parts = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)

    @staticmethod
    def _extract_excel_text(content: bytes) -> str:
        """Extract text from Excel bytes using openpyxl."""
        import io

        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        text_parts = []
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            for row in ws.iter_rows(values_only=True):
                row_text = " ".join(str(cell) for cell in row if cell is not None)
                if row_text.strip():
                    text_parts.append(row_text)
        wb.close()
        return "\n".join(text_parts)

    @staticmethod
    def _extract_docx_text(content: bytes) -> str:
        """Extract text from Word document bytes using python-docx."""
        import io

        from docx import Document

        doc = Document(io.BytesIO(content))
        text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n".join(text_parts)
