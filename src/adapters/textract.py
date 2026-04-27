"""Module: adapters/textract.py

Amazon Textract connector for VQMS.

Used by the portal attachment pipeline to OCR PDFs and image
attachments before falling back to library-based parsers
(pdfplumber, etc.). Only the synchronous detect_document_text API
is exposed — multi-page async jobs are out of scope for now and
the caller (TextExtractor) falls through to pdfplumber when the
sync call rejects a multi-page PDF.

The connector reads from a file already uploaded to S3, so the
caller passes the bucket + key — no bytes round-trip.

Usage:
    from adapters.textract import TextractConnector
    text = await textract.detect_text_from_s3(bucket, key, correlation_id="abc")
"""

from __future__ import annotations

import asyncio

import boto3
import structlog
from botocore.exceptions import ClientError

from config.settings import Settings
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class TextractError(Exception):
    """Raised when Textract cannot extract text and the caller
    should fall back to a library-based extractor."""


class TextractConnector:
    """AWS Textract connector for synchronous document text detection.

    All boto3 calls are wrapped in asyncio.to_thread because the
    SDK is synchronous. detect_document_text supports PDF, PNG,
    JPEG, and TIFF — only the first page of multi-page PDFs is
    processed. The caller is expected to fall back to pdfplumber
    on UnsupportedDocumentException or InvalidParameterException.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the Textract client from AWS credentials in settings."""
        self._client = boto3.client(
            "textract",
            region_name=settings.aws_region,
            **settings.aws_credentials_kwargs(),
        )
        self._settings = settings

    @log_service_call
    async def detect_text_from_s3(
        self,
        bucket: str,
        key: str,
        *,
        correlation_id: str = "",
    ) -> str:
        """Detect text in a document already stored in S3.

        Args:
            bucket: S3 bucket holding the document.
            key: S3 object key.
            correlation_id: Tracing ID for structured logging.

        Returns:
            Extracted text joined by newlines (one entry per LINE block).

        Raises:
            TextractError: For any Textract failure (access denied,
                unsupported document, multi-page PDF, throttling, etc.)
                so the caller can decide whether to fall back to a
                library-based extractor.
        """
        try:
            response = await asyncio.to_thread(
                self._client.detect_document_text,
                Document={"S3Object": {"Bucket": bucket, "Name": key}},
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            logger.warning(
                "Textract detect_document_text failed",
                tool="textract",
                bucket=bucket,
                key=key,
                error_code=error_code,
                correlation_id=correlation_id,
            )
            raise TextractError(error_code or str(exc)) from exc

        # Textract returns Blocks; LINE blocks are the human-readable rows.
        # WORD blocks are subordinate to LINE blocks so we ignore them
        # to avoid duplicate text.
        lines: list[str] = []
        for block in response.get("Blocks", []):
            if block.get("BlockType") == "LINE":
                text = block.get("Text", "")
                if text:
                    lines.append(text)

        joined = "\n".join(lines)
        logger.info(
            "Textract extraction complete",
            tool="textract",
            bucket=bucket,
            key=key,
            line_count=len(lines),
            char_count=len(joined),
            correlation_id=correlation_id,
        )
        return joined
