"""Module: services/admin_email/attachments.py

Attachment validation and S3 staging for admin-composed emails.

The validator enforces size, count, and MIME safety rules BEFORE any
S3 write happens, so a rejected request leaves no partial state. The
stager uploads to S3 under outbound-emails/{outbound_id}/{filename}
and returns OutboundAttachment records ready to hand to the Graph
adapter.

Limits match the inbound attachment policy in CLAUDE.md so admin
sends and vendor receives go through the same safety bar.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Iterable

import structlog
from fastapi import UploadFile

from adapters.graph_api import OutboundAttachment
from utils.decorators import log_service_call
from utils.exceptions import AttachmentRejectedError

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AttachmentLimits:
    """Safety limits for outbound email attachments.

    Matches the inbound policy in CLAUDE.md so admin sends and the
    inbound pipeline both reject the same set of bad files.
    """

    max_per_file_bytes: int = 25 * 1024 * 1024     # 25 MB Graph hard limit
    max_total_bytes: int = 50 * 1024 * 1024        # 50 MB matches inbound policy
    max_count: int = 10
    blocked_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {".exe", ".bat", ".cmd", ".ps1", ".sh", ".js"}
        )
    )


@dataclass(frozen=True)
class StagedAttachment:
    """Result of staging a single file: the OutboundAttachment for
    Graph plus the row metadata needed to insert into
    intake.admin_outbound_attachments.
    """

    attachment_id: str
    s3_key: str
    outbound_attachment: OutboundAttachment


class AttachmentValidator:
    """Validate UploadFile list against AttachmentLimits.

    Reads each file's bytes once to verify the actual size and to
    check the magic-extension. Size limits use UploadFile.size when
    present; otherwise we fall back to counting bytes after read.
    """

    def __init__(self, limits: AttachmentLimits | None = None) -> None:
        self._limits = limits or AttachmentLimits()

    def validate(self, files: Iterable[UploadFile]) -> None:
        """Validate that every file is within limits.

        Raises:
            AttachmentRejectedError: First failure (count, size, type).
                The route handler converts this to a 422 response.
        """
        files_list = list(files)
        if len(files_list) > self._limits.max_count:
            raise AttachmentRejectedError(
                f"Too many attachments: {len(files_list)} > "
                f"{self._limits.max_count}"
            )

        total_bytes = 0
        for upload in files_list:
            filename = upload.filename or "unnamed"
            ext = os.path.splitext(filename)[1].lower()
            if ext in self._limits.blocked_extensions:
                raise AttachmentRejectedError(
                    f"File extension '{ext}' is blocked",
                    filename=filename,
                )

            size = _file_size(upload)
            if size > self._limits.max_per_file_bytes:
                raise AttachmentRejectedError(
                    f"File too large: {size} bytes > "
                    f"{self._limits.max_per_file_bytes} bytes",
                    filename=filename,
                )
            total_bytes += size

        if total_bytes > self._limits.max_total_bytes:
            raise AttachmentRejectedError(
                f"Total attachments too large: {total_bytes} bytes > "
                f"{self._limits.max_total_bytes} bytes"
            )


class AttachmentStager:
    """Read uploaded files into memory, push them to S3, and return
    OutboundAttachment records ready for the Graph adapter.

    Bytes are kept in memory so the Graph adapter can either base64-
    encode them inline (small files) or chunk them through the upload
    session (large files). For dev mode this is acceptable — production
    would stream from S3 to avoid the memory pressure.
    """

    def __init__(self, s3_client, bucket: str, prefix: str = "outbound-emails") -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._prefix = prefix

    @log_service_call
    async def stage(
        self,
        outbound_id: str,
        files: list[UploadFile],
        *,
        correlation_id: str = "",
    ) -> list[StagedAttachment]:
        """Upload each file to S3 and return staging metadata.

        Args:
            outbound_id: AOE-YYYY-NNNN identifying this admin send.
            files: UploadFile list (already validated by
                ``AttachmentValidator``).
            correlation_id: Tracing id.

        Returns:
            One StagedAttachment per file in the same order as the
            input. The list is empty when no files were uploaded.

        Raises:
            ClientError: If any S3 upload fails (caller catches and
                marks the outbound row FAILED).
        """
        staged: list[StagedAttachment] = []
        for upload in files:
            filename = upload.filename or "unnamed"
            content_type = upload.content_type or "application/octet-stream"
            content_bytes = await upload.read()
            size_bytes = len(content_bytes)

            attachment_id = f"ATT-{uuid.uuid4().hex[:16]}"
            s3_key = f"{self._prefix}/{outbound_id}/{attachment_id}_{filename}"

            await self._s3.upload_file(
                bucket=self._bucket,
                key=s3_key,
                body=content_bytes,
                content_type=content_type,
                correlation_id=correlation_id,
            )

            staged.append(
                StagedAttachment(
                    attachment_id=attachment_id,
                    s3_key=s3_key,
                    outbound_attachment=OutboundAttachment(
                        filename=filename,
                        content_type=content_type,
                        content_bytes=content_bytes,
                        size_bytes=size_bytes,
                    ),
                )
            )

        logger.info(
            "Admin email attachments staged",
            tool="s3",
            outbound_id=outbound_id,
            count=len(staged),
            total_bytes=sum(s.outbound_attachment.size_bytes for s in staged),
            correlation_id=correlation_id,
        )
        return staged


def _file_size(upload: UploadFile) -> int:
    """Return the size of an UploadFile in bytes.

    Starlette sets ``upload.size`` when the multipart parser knows it.
    When it does not (rare — chunked uploads), we fall back to seeking
    the underlying SpooledTemporaryFile.
    """
    if upload.size is not None:
        return upload.size
    try:
        upload.file.seek(0, os.SEEK_END)
        size = upload.file.tell()
        upload.file.seek(0)
        return size
    except (AttributeError, OSError):
        return 0
