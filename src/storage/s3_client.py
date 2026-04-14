"""Module: connectors/s3.py

AWS S3 connector for VQMS.

Handles upload, download, presigned URL generation, existence checks,
listing, and deletion for the single VQMS S3 bucket (vqms-data-store).
All files are organized by prefix + VQ-ID inside this one bucket.
All boto3 calls are wrapped in asyncio.to_thread because boto3
is synchronous — this keeps the interface async without adding
the aioboto3 dependency.

Usage:
    from connectors.s3 import S3Connector
    from config.settings import get_settings
    from config.s3_paths import build_s3_key, S3_PREFIX_INBOUND_EMAILS, FILENAME_RAW_EMAIL

    s3 = S3Connector(get_settings())
    key = build_s3_key(S3_PREFIX_INBOUND_EMAILS, "VQ-2026-0001", FILENAME_RAW_EMAIL)
    await s3.upload_file("vqms-data-store", key, raw_bytes)
"""

from __future__ import annotations

import asyncio

import boto3
import structlog
from botocore.exceptions import ClientError

from config.settings import Settings
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class S3Connector:
    """AWS S3 connector for file storage operations.

    All methods are async. Boto3 sync calls are executed in a
    thread pool via asyncio.to_thread to avoid blocking the
    event loop.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Creates the boto3 S3 client immediately — no lazy init
        needed since the client is lightweight and thread-safe.
        """
        self._client = boto3.client("s3", region_name=settings.aws_region)
        self._settings = settings

    @log_service_call
    async def upload_file(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str = "application/octet-stream",
        *,
        correlation_id: str = "",
    ) -> str:
        """Upload a file to S3.

        Args:
            bucket: S3 bucket name.
            key: Object key (path) within the bucket.
            body: File content as bytes.
            content_type: MIME type for the object.
            correlation_id: Tracing ID for structured logging.

        Returns:
            The S3 object key that was uploaded.

        Raises:
            ClientError: If the upload fails (e.g., AccessDenied, bucket not found).
        """
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
            logger.info(
                "S3 upload complete",
                tool="s3",
                bucket=bucket,
                key=key,
                size_bytes=len(body),
                correlation_id=correlation_id,
            )
            return key
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("AccessDeniedException", "AccessDenied"):
                logger.error(
                    "S3 access denied — check IAM permissions",
                    tool="s3",
                    bucket=bucket,
                    key=key,
                    correlation_id=correlation_id,
                )
            raise

    @log_service_call
    async def download_file(
        self,
        bucket: str,
        key: str,
        *,
        correlation_id: str = "",
    ) -> bytes:
        """Download a file from S3.

        Args:
            bucket: S3 bucket name.
            key: Object key (path) within the bucket.
            correlation_id: Tracing ID for structured logging.

        Returns:
            File content as bytes.

        Raises:
            ClientError: If the download fails (e.g., NoSuchKey, AccessDenied).
        """
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=bucket,
                Key=key,
            )
            # Read the streaming body — this is sync, so wrap it too
            body = await asyncio.to_thread(response["Body"].read)
            logger.info(
                "S3 download complete",
                tool="s3",
                bucket=bucket,
                key=key,
                size_bytes=len(body),
                correlation_id=correlation_id,
            )
            return body
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code == "NoSuchKey":
                logger.error(
                    "S3 object not found",
                    tool="s3",
                    bucket=bucket,
                    key=key,
                    correlation_id=correlation_id,
                )
            raise

    @log_service_call
    async def generate_presigned_url(
        self,
        bucket: str,
        key: str,
        expiration: int = 3600,
        *,
        correlation_id: str = "",
    ) -> str:
        """Generate a presigned URL for temporary read access.

        Args:
            bucket: S3 bucket name.
            key: Object key (path) within the bucket.
            expiration: URL validity in seconds (default 1 hour).
            correlation_id: Tracing ID for structured logging.

        Returns:
            Presigned URL string.
        """
        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiration,
        )
        return url

    @log_service_call
    async def object_exists(
        self,
        bucket: str,
        key: str,
        *,
        correlation_id: str = "",
    ) -> bool:
        """Check if an object exists in S3 using HEAD request.

        Args:
            bucket: S3 bucket name.
            key: Object key (path) within the bucket.
            correlation_id: Tracing ID for structured logging.

        Returns:
            True if the object exists, False otherwise.
        """
        try:
            await asyncio.to_thread(
                self._client.head_object,
                Bucket=bucket,
                Key=key,
            )
            return True
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            # head_object returns "404" or "NoSuchKey" when object is missing
            if error_code in ("404", "NoSuchKey"):
                return False
            raise

    @log_service_call
    async def list_objects(
        self,
        bucket: str,
        prefix: str,
        *,
        correlation_id: str = "",
    ) -> list[str]:
        """List all object keys under a given prefix.

        Args:
            bucket: S3 bucket name.
            prefix: Key prefix to filter by (e.g., "attachments/VQ-2026-0001/").
            correlation_id: Tracing ID for structured logging.

        Returns:
            List of S3 object keys matching the prefix.
        """
        keys: list[str] = []
        try:
            # Use paginator in case there are many objects
            paginator = self._client.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

            # Paginate synchronously in a thread to avoid blocking
            def _collect_keys() -> list[str]:
                collected: list[str] = []
                for page in page_iterator:
                    for obj in page.get("Contents", []):
                        collected.append(obj["Key"])
                return collected

            keys = await asyncio.to_thread(_collect_keys)
            logger.info(
                "S3 list objects complete",
                tool="s3",
                bucket=bucket,
                prefix=prefix,
                count=len(keys),
                correlation_id=correlation_id,
            )
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("AccessDeniedException", "AccessDenied"):
                logger.error(
                    "S3 access denied on list — check IAM permissions",
                    tool="s3",
                    bucket=bucket,
                    prefix=prefix,
                    correlation_id=correlation_id,
                )
            raise
        return keys

    @log_service_call
    async def delete_object(
        self,
        bucket: str,
        key: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """Delete a single object from S3.

        Args:
            bucket: S3 bucket name.
            key: Object key (path) within the bucket.
            correlation_id: Tracing ID for structured logging.

        Raises:
            ClientError: If the deletion fails (e.g., AccessDenied).
        """
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=bucket,
                Key=key,
            )
            logger.info(
                "S3 object deleted",
                tool="s3",
                bucket=bucket,
                key=key,
                correlation_id=correlation_id,
            )
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("AccessDeniedException", "AccessDenied"):
                logger.error(
                    "S3 access denied on delete — check IAM permissions",
                    tool="s3",
                    bucket=bucket,
                    key=key,
                    correlation_id=correlation_id,
                )
            raise
