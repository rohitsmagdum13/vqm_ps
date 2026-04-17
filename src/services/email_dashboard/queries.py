"""Module: services/email_dashboard/queries.py

Database query helpers for the email dashboard.

Handles dynamic WHERE clause construction, batch attachment
fetching, and SQL query building for the dashboard service.
"""

from __future__ import annotations

import structlog

from db.connection import PostgresConnector
from models.email_dashboard import AttachmentSummary
from services.email_dashboard.mappings import DashboardMapper, STATUS_FILTER_MAP

logger = structlog.get_logger(__name__)


class DashboardQueryBuilder:
    """Builds and executes dashboard-specific database queries.

    Encapsulates SQL query construction, dynamic WHERE clauses,
    and batch data fetching to avoid N+1 query patterns.
    """

    def __init__(self, postgres: PostgresConnector) -> None:
        """Initialize with PostgreSQL connector.

        Args:
            postgres: PostgreSQL connector for database queries.
        """
        self._postgres = postgres

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
        self, message_ids: list[str]
    ) -> dict[str, list[AttachmentSummary]]:
        """Fetch all attachments for a list of message_ids in ONE query.

        Returns a dict keyed by message_id, each value is a list of
        AttachmentSummary models. This avoids N+1 queries.
        """
        if not message_ids:
            return {}

        placeholders = ", ".join(f"${i + 1}" for i in range(len(message_ids)))
        sql = (
            "SELECT message_id, attachment_id, filename, content_type, size_bytes "
            "FROM intake.email_attachments "
            f"WHERE message_id IN ({placeholders})"
        )
        rows = await self._postgres.fetch(sql, *message_ids)

        result: dict[str, list[AttachmentSummary]] = {}
        for row in rows:
            summary = AttachmentSummary(
                attachment_id=row["attachment_id"],
                filename=row["filename"],
                content_type=row["content_type"],
                size_bytes=row["size_bytes"],
                file_format=DashboardMapper.file_format(row["filename"]),
            )
            result.setdefault(row["message_id"], []).append(summary)

        return result

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
