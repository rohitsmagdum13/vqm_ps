"""Module: services/attachment_manifest.py

Attachment Manifest Builder for VQMS single-bucket S3 architecture.

After all attachments for an email are processed and stored in S3,
this module builds and uploads a _manifest.json file that indexes
every attachment for that query. This makes cross-file lookups
trivial — any downstream service can read one manifest to find
all attachment keys, sizes, and extraction statuses.

Manifest location: attachments/VQ-YYYY-NNNN/_manifest.json

Usage:
    from services.attachment_manifest import AttachmentManifestBuilder

    manifest_key = await AttachmentManifestBuilder.store_manifest(
        s3=s3_connector,
        settings=settings,
        query_id="VQ-2026-0001",
        attachments=attachment_list,
        correlation_id="abc-123",
    )
"""

from __future__ import annotations

import orjson
import structlog

from config.s3_paths import (
    FILENAME_ATTACHMENT_MANIFEST,
    S3_PREFIX_ATTACHMENTS,
    build_s3_key,
)
from config.settings import Settings
from storage.s3_client import S3Connector
from models.email import EmailAttachment
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


class AttachmentManifestBuilder:
    """Builds and stores attachment manifests in S3.

    The manifest is a JSON file listing every attachment for a
    given query, including S3 keys, sizes, content types, and
    extraction status. Stored at:
        attachments/{query_id}/_manifest.json
    """

    @staticmethod
    def build_manifest(
        query_id: str,
        attachments: list[EmailAttachment],
    ) -> dict:
        """Build the manifest dict from a list of processed attachments.

        Args:
            query_id: Vendor Query ID (e.g., "VQ-2026-0001").
            attachments: List of processed EmailAttachment objects.

        Returns:
            Manifest dict ready for JSON serialization.
        """
        total_size = sum(att.size_bytes for att in attachments)
        now = TimeHelper.ist_now()

        attachment_entries = []
        for att in attachments:
            attachment_entries.append({
                "attachment_id": att.attachment_id,
                "filename": att.filename,
                "content_type": att.content_type,
                "size_bytes": att.size_bytes,
                "s3_key": att.s3_key,
                "extraction_status": att.extraction_status,
                "has_extracted_text": att.extracted_text is not None and len(att.extracted_text) > 0,
            })

        return {
            "query_id": query_id,
            "total_attachments": len(attachments),
            "total_size_bytes": total_size,
            "created_at": now.isoformat(),
            "attachments": attachment_entries,
        }

    @staticmethod
    async def store_manifest(
        s3: S3Connector,
        settings: Settings,
        query_id: str,
        attachments: list[EmailAttachment],
        *,
        correlation_id: str = "",
    ) -> str | None:
        """Build and upload the attachment manifest to S3.

        Non-critical — returns None on failure instead of raising.

        Args:
            s3: S3 connector for uploading.
            settings: Application settings (for bucket name).
            query_id: Vendor Query ID.
            attachments: List of processed EmailAttachment objects.
            correlation_id: Tracing ID for structured logging.

        Returns:
            The S3 key of the uploaded manifest, or None if upload failed.
        """
        if not attachments:
            # No attachments — no manifest needed
            return None

        try:
            manifest = AttachmentManifestBuilder.build_manifest(query_id, attachments)
            manifest_bytes = orjson.dumps(manifest, option=orjson.OPT_INDENT_2)

            manifest_key = build_s3_key(
                S3_PREFIX_ATTACHMENTS, query_id, FILENAME_ATTACHMENT_MANIFEST
            )

            await s3.upload_file(
                bucket=settings.s3_bucket_data_store,
                key=manifest_key,
                body=manifest_bytes,
                content_type="application/json",
                correlation_id=correlation_id,
            )

            logger.info(
                "Attachment manifest stored",
                query_id=query_id,
                manifest_key=manifest_key,
                attachment_count=len(attachments),
                correlation_id=correlation_id,
            )
            return manifest_key
        except Exception:
            logger.warning(
                "Failed to store attachment manifest — continuing",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return None
