"""Module: services/email_dashboard/queries.py

Database query helpers for the email dashboard.

Handles dynamic WHERE clause construction, batch attachment
fetching, and SQL query building for the dashboard service.
"""

from __future__ import annotations

import asyncio

import structlog

from db.connection import PostgresConnector
from models.email_dashboard import AttachmentSummary
from services.email_dashboard.mappings import DashboardMapper, STATUS_FILTER_MAP
from storage.s3_client import S3Connector

logger = structlog.get_logger(__name__)

# Admin portal leaves email list views open for extended sessions,
# so we sign URLs for a full hour. If a URL 403s after expiry, the
# frontend just refetches the list.
ATTACHMENT_URL_TTL_SECONDS = 3600


class DashboardQueryBuilder:
    """Builds and executes dashboard-specific database queries.

    Encapsulates SQL query construction, dynamic WHERE clauses,
    and batch data fetching to avoid N+1 query patterns.
    """

    def __init__(
        self,
        postgres: PostgresConnector,
        s3: S3Connector,
        s3_bucket: str,
    ) -> None:
        """Initialize with PostgreSQL and S3 connectors.

        Args:
            postgres: PostgreSQL connector for database queries.
            s3: S3 connector used to mint presigned download URLs.
            s3_bucket: Name of the VQMS data-store bucket.
        """
        self._postgres = postgres
        self._s3 = s3
        self._s3_bucket = s3_bucket

    def build_where_clause(
        self,
        *,
        status: str | None,
        priority: str | None,
        search: str | None,
    ) -> tuple[str, list, int]:
        """Build a dynamic WHERE clause with asyncpg $N placeholders.

        Returns:
            Tuple of (where_clause_str, params_list, next_param_index).
        """
        conditions: list[str] = []
        params: list = []
        idx = 1

        if status:
            db_statuses = STATUS_FILTER_MAP.get(status, [])
            if db_statuses:
                placeholders = ", ".join(f"${idx + i}" for i in range(len(db_statuses)))
                conditions.append(f"ce.status IN ({placeholders})")
                params.extend(db_statuses)
                idx += len(db_statuses)

        if priority:
            # Map display priority back to DB values
            db_priority = priority.lower()
            conditions.append(f"rd.priority = ${idx}")
            params.append(db_priority)
            idx += 1

        if search:
            conditions.append(f"(em.subject ILIKE ${idx} OR em.sender_email ILIKE ${idx})")
            params.append(f"%{search}%")
            idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        return where_clause, params, idx

    async def batch_fetch_attachments(
        self,
        message_ids: list[str],
        *,
        correlation_id: str = "",
    ) -> dict[str, list[AttachmentSummary]]:
        """Fetch all attachments for a list of message_ids in ONE query.

        Also mints a presigned S3 download URL per row so the admin
        portal can render a direct download link without a second API
        call. Rows without an s3_key get download_url=None.

        Returns a dict keyed by message_id, each value is a list of
        AttachmentSummary models. This avoids N+1 queries.
        """
        if not message_ids:
            return {}

        placeholders = ", ".join(f"${i + 1}" for i in range(len(message_ids)))
        sql = (
            "SELECT message_id, attachment_id, filename, content_type, "
            "size_bytes, s3_key "
            "FROM intake.email_attachments "
            f"WHERE message_id IN ({placeholders})"
        )
        rows = await self._postgres.fetch(sql, *message_ids)

        # Sign all URLs concurrently — generate_presigned_url is a local
        # crypto op, but asyncio.to_thread dispatch still adds overhead
        # per call, so gather amortizes that across the batch.
        signed_urls = await asyncio.gather(
            *(
                self._sign_or_none(row["s3_key"], correlation_id=correlation_id)
                for row in rows
            )
        )

        result: dict[str, list[AttachmentSummary]] = {}
        for row, url in zip(rows, signed_urls):
            summary = AttachmentSummary(
                attachment_id=row["attachment_id"],
                filename=row["filename"],
                content_type=row["content_type"],
                size_bytes=row["size_bytes"],
                file_format=DashboardMapper.file_format(row["filename"]),
                download_url=url,
                expires_in_seconds=ATTACHMENT_URL_TTL_SECONDS,
            )
            result.setdefault(row["message_id"], []).append(summary)

        return result

    async def _sign_or_none(
        self,
        s3_key: str | None,
        *,
        correlation_id: str,
    ) -> str | None:
        """Return a presigned URL for the key, or None if the key is missing."""
        if not s3_key:
            return None
        return await self._s3.generate_presigned_url(
            self._s3_bucket,
            s3_key,
            ATTACHMENT_URL_TTL_SECONDS,
            correlation_id=correlation_id,
        )

    @staticmethod
    def sort_expression(sort_by: str) -> str:
        """Map sort_by parameter to SQL aggregate expression.

        Since we GROUP BY thread_key, sort fields must be aggregated.
        """
        sort_map = {
            "timestamp": "MAX(em.received_at)",
            "status": "MIN(ce.status)",
            "priority": "MIN(rd.priority)",
        }
        return sort_map.get(sort_by, "MAX(em.received_at)")
