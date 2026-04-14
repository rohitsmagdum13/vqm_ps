"""Module: services/email_dashboard.py

Email Dashboard Service for VQMS.

Provides read-only query methods for the email dashboard API.
All data comes from existing PostgreSQL tables — no writes,
no mutations, no side effects.

Uses the PostgresConnector (asyncpg) for database queries and
S3Connector for presigned attachment download URLs.

Query strategy: fixed 4-query pattern per page load to avoid N+1:
  1. Count distinct thread keys (for pagination total)
  2. Get paginated thread keys ordered by latest received_at
  3. Fetch all emails belonging to those thread keys
  4. Batch-fetch all attachments for those emails

Usage:
    service = EmailDashboardService(postgres, s3, settings)
    chains = await service.list_email_chains(page=1, page_size=20)
    stats = await service.get_stats(correlation_id="abc-123")
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from config.settings import Settings
from db.connection import PostgresConnector
from storage.s3_client import S3Connector
from models.email_dashboard import (
    AttachmentDownloadResponse,
    AttachmentSummary,
    EmailStatsResponse,
    MailChainListResponse,
    MailChainResponse,
    MailItemResponse,
    UserResponse,
)
from utils.decorators import log_service_call
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# --- Status Mapping ---
# DB stores UPPERCASE workflow statuses. Dashboard shows 3 categories.

_STATUS_MAP: dict[str, str] = {
    "RECEIVED": "New",
    "ANALYZING": "New",
    "ROUTING": "New",
    "DRAFTING": "New",
    "VALIDATING": "New",
    "SENDING": "New",
    "AWAITING_HUMAN_REVIEW": "New",
    "AWAITING_TEAM_RESOLUTION": "New",
    "FAILED": "New",
    "DRAFT_REJECTED": "New",
    "REOPENED": "Reopened",
    "RESOLVED": "Resolved",
    "CLOSED": "Resolved",
}

# Reverse map: dashboard status → list of DB statuses for SQL IN clauses
_STATUS_FILTER_MAP: dict[str, list[str]] = {
    "New": [
        "RECEIVED", "ANALYZING", "ROUTING", "DRAFTING", "VALIDATING",
        "SENDING", "AWAITING_HUMAN_REVIEW", "AWAITING_TEAM_RESOLUTION",
        "FAILED", "DRAFT_REJECTED",
    ],
    "Reopened": ["REOPENED"],
    "Resolved": ["RESOLVED", "CLOSED"],
}

# All "New" statuses as a SQL-safe tuple string for the stats query
_NEW_STATUSES_SQL = (
    "'RECEIVED','ANALYZING','ROUTING','DRAFTING','VALIDATING',"
    "'SENDING','AWAITING_HUMAN_REVIEW','AWAITING_TEAM_RESOLUTION',"
    "'FAILED','DRAFT_REJECTED'"
)

# --- Priority Mapping ---
# routing_decision.priority → dashboard display string

_PRIORITY_MAP: dict[str, str] = {
    "critical": "High",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


class EmailDashboardService:
    """Read-only service for the email dashboard API.

    Queries intake.email_messages, intake.email_attachments,
    workflow.case_execution, and workflow.routing_decision tables
    to serve dashboard data. Never writes to the database.
    """

    def __init__(
        self,
        postgres: PostgresConnector,
        s3: S3Connector,
        settings: Settings,
    ) -> None:
        """Initialize with required connectors.

        Args:
            postgres: PostgreSQL connector for database queries.
            s3: S3 connector for presigned download URLs.
            settings: Application settings (S3 bucket name, etc.).
        """
        self._postgres = postgres
        self._s3 = s3
        self._settings = settings

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    @log_service_call
    async def list_email_chains(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
        correlation_id: str = "",
    ) -> MailChainListResponse:
        """List email chains with pagination, filtering, and sorting.

        Groups emails by conversation_id (thread). If conversation_id
        is NULL, each email is its own chain (grouped by query_id).

        Args:
            page: Page number (1-based).
            page_size: Items per page (1-100).
            status: Filter by dashboard status (New, Reopened, Resolved).
            priority: Filter by dashboard priority (High, Medium, Low).
            search: Search in subject and sender_email (ILIKE).
            sort_by: Sort field (timestamp, status, priority).
            sort_order: Sort direction (asc, desc).
            correlation_id: Tracing ID.

        Returns:
            Paginated list of mail chains.
        """
        try:
            # Build dynamic WHERE clause
            where_clause, params, idx = self._build_where_clause(
                status=status, priority=priority, search=search
            )

            # Step 1: Count distinct thread keys
            count_sql = (
                "SELECT COUNT(DISTINCT COALESCE(em.conversation_id, em.query_id)) AS total "
                "FROM intake.email_messages em "
                "JOIN workflow.case_execution ce ON em.query_id = ce.query_id "
                "LEFT JOIN workflow.routing_decision rd ON em.query_id = rd.query_id "
                f"WHERE {where_clause}"
            )
            count_row = await self._postgres.fetchrow(count_sql, *params)
            total = count_row["total"] if count_row else 0

            if total == 0:
                return MailChainListResponse(
                    total=0, page=page, page_size=page_size, mail_chains=[]
                )

            # Step 2: Get paginated thread keys
            sort_expr = self._sort_expression(sort_by)
            direction = "DESC" if sort_order == "desc" else "ASC"
            offset = (page - 1) * page_size

            # Add LIMIT and OFFSET params
            limit_param = f"${idx}"
            offset_param = f"${idx + 1}"
            params_with_pagination = [*params, page_size, offset]

            thread_keys_sql = (
                "SELECT COALESCE(em.conversation_id, em.query_id) AS thread_key "
                "FROM intake.email_messages em "
                "JOIN workflow.case_execution ce ON em.query_id = ce.query_id "
                "LEFT JOIN workflow.routing_decision rd ON em.query_id = rd.query_id "
                f"WHERE {where_clause} "
                "GROUP BY COALESCE(em.conversation_id, em.query_id) "
                f"ORDER BY {sort_expr} {direction} "
                f"LIMIT {limit_param} OFFSET {offset_param}"
            )
            thread_key_rows = await self._postgres.fetch(
                thread_keys_sql, *params_with_pagination
            )
            thread_keys = [row["thread_key"] for row in thread_key_rows]

            if not thread_keys:
                return MailChainListResponse(
                    total=total, page=page, page_size=page_size, mail_chains=[]
                )

            # Step 3: Fetch all emails for these thread keys
            tk_placeholders = ", ".join(f"${i + 1}" for i in range(len(thread_keys)))
            emails_sql = (
                "SELECT em.query_id, em.sender_email, em.sender_name, "
                "em.subject, em.body_text, em.received_at, em.conversation_id, "
                "em.thread_status, em.message_id, "
                "ce.status AS case_status, "
                "rd.priority AS routing_priority "
                "FROM intake.email_messages em "
                "JOIN workflow.case_execution ce ON em.query_id = ce.query_id "
                "LEFT JOIN workflow.routing_decision rd ON em.query_id = rd.query_id "
                f"WHERE COALESCE(em.conversation_id, em.query_id) IN ({tk_placeholders}) "
                "ORDER BY em.received_at DESC"
            )
            email_rows = await self._postgres.fetch(emails_sql, *thread_keys)

            # Step 4: Batch-fetch all attachments for these emails
            message_ids = [row["message_id"] for row in email_rows]
            attachments_by_message = await self._batch_fetch_attachments(message_ids)

            # Group emails into chains preserving page order
            mail_chains = self._group_into_chains(
                email_rows, attachments_by_message, thread_keys
            )

            return MailChainListResponse(
                total=total,
                page=page,
                page_size=page_size,
                mail_chains=mail_chains,
            )

        except Exception:
            logger.exception(
                "Failed to list email chains",
                correlation_id=correlation_id,
            )
            return MailChainListResponse(
                total=0, page=page, page_size=page_size, mail_chains=[]
            )

    @log_service_call
    async def get_stats(
        self,
        *,
        correlation_id: str = "",
    ) -> EmailStatsResponse:
        """Get aggregate dashboard statistics for email-sourced queries.

        Counts emails by status category, priority, and time period.

        Args:
            correlation_id: Tracing ID.

        Returns:
            Dashboard statistics.
        """
        try:
            now = TimeHelper.ist_now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=7)

            # Main stats query — single pass over case_execution
            stats_sql = (
                "SELECT "
                "COUNT(*) AS total, "
                f"COUNT(*) FILTER (WHERE ce.status IN ({_NEW_STATUSES_SQL})) AS new_count, "
                "COUNT(*) FILTER (WHERE ce.status = 'REOPENED') AS reopened_count, "
                "COUNT(*) FILTER (WHERE ce.status IN ('RESOLVED', 'CLOSED')) AS resolved_count, "
                "COUNT(*) FILTER (WHERE ce.created_at >= $1) AS today_count, "
                "COUNT(*) FILTER (WHERE ce.created_at >= $2) AS week_count "
                "FROM workflow.case_execution ce "
                "WHERE ce.source = 'email'"
            )
            stats_row = await self._postgres.fetchrow(stats_sql, today_start, week_start)

            # Priority breakdown — from routing_decision table
            priority_sql = (
                "SELECT rd.priority, COUNT(*) AS cnt "
                "FROM workflow.routing_decision rd "
                "JOIN workflow.case_execution ce ON rd.query_id = ce.query_id "
                "WHERE ce.source = 'email' "
                "GROUP BY rd.priority"
            )
            priority_rows = await self._postgres.fetch(priority_sql)

            # Map DB priority values to display values and aggregate
            priority_breakdown: dict[str, int] = {"High": 0, "Medium": 0, "Low": 0}
            for row in priority_rows:
                display_priority = _map_priority(row["priority"])
                priority_breakdown[display_priority] += row["cnt"]

            if stats_row:
                return EmailStatsResponse(
                    total_emails=stats_row["total"],
                    new_count=stats_row["new_count"],
                    reopened_count=stats_row["reopened_count"],
                    resolved_count=stats_row["resolved_count"],
                    priority_breakdown=priority_breakdown,
                    today_count=stats_row["today_count"],
                    this_week_count=stats_row["week_count"],
                )

            return EmailStatsResponse(
                total_emails=0,
                new_count=0,
                reopened_count=0,
                resolved_count=0,
                priority_breakdown=priority_breakdown,
                today_count=0,
                this_week_count=0,
            )

        except Exception:
            logger.exception(
                "Failed to get email stats",
                correlation_id=correlation_id,
            )
            return EmailStatsResponse(
                total_emails=0,
                new_count=0,
                reopened_count=0,
                resolved_count=0,
                priority_breakdown={"High": 0, "Medium": 0, "Low": 0},
                today_count=0,
                this_week_count=0,
            )

    @log_service_call
    async def get_email_chain(
        self,
        query_id: str,
        *,
        correlation_id: str = "",
    ) -> MailChainResponse | None:
        """Get a single email chain by query_id.

        If the email has a conversation_id, returns the full thread
        (all emails sharing that conversation_id). Otherwise returns
        just the single email.

        Args:
            query_id: VQMS query ID (e.g., VQ-2026-0001).
            correlation_id: Tracing ID.

        Returns:
            MailChainResponse with all emails in the thread,
            or None if query_id not found.
        """
        try:
            # Find the email and its conversation_id
            lookup_sql = (
                "SELECT em.conversation_id, ce.status, rd.priority "
                "FROM intake.email_messages em "
                "JOIN workflow.case_execution ce ON em.query_id = ce.query_id "
                "LEFT JOIN workflow.routing_decision rd ON em.query_id = rd.query_id "
                "WHERE em.query_id = $1"
            )
            lookup_row = await self._postgres.fetchrow(lookup_sql, query_id)

            if lookup_row is None:
                return None

            conversation_id = lookup_row["conversation_id"]
            case_status = lookup_row["status"]
            routing_priority = lookup_row["priority"]

            # Fetch all emails in the thread
            if conversation_id:
                # Full thread: all emails sharing this conversation_id
                emails_sql = (
                    "SELECT em.query_id, em.sender_email, em.sender_name, "
                    "em.subject, em.body_text, em.received_at, em.conversation_id, "
                    "em.thread_status, em.message_id "
                    "FROM intake.email_messages em "
                    "WHERE em.conversation_id = $1 "
                    "ORDER BY em.received_at DESC"
                )
                email_rows = await self._postgres.fetch(emails_sql, conversation_id)
            else:
                # Standalone email: just this query_id
                emails_sql = (
                    "SELECT em.query_id, em.sender_email, em.sender_name, "
                    "em.subject, em.body_text, em.received_at, em.conversation_id, "
                    "em.thread_status, em.message_id "
                    "FROM intake.email_messages em "
                    "WHERE em.query_id = $1 "
                    "ORDER BY em.received_at DESC"
                )
                email_rows = await self._postgres.fetch(emails_sql, query_id)

            # Batch-fetch attachments
            message_ids = [row["message_id"] for row in email_rows]
            attachments_by_message = await self._batch_fetch_attachments(message_ids)

            # Build mail items
            mail_items = [
                self._row_to_mail_item(row, attachments_by_message.get(row["message_id"], []))
                for row in email_rows
            ]

            return MailChainResponse(
                conversation_id=conversation_id,
                mail_items=mail_items,
                status=_map_status(case_status),
                priority=_map_priority(routing_priority),
            )

        except Exception:
            logger.exception(
                "Failed to get email chain",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return None

    @log_service_call
    async def get_attachment_download(
        self,
        attachment_id: str,
        *,
        correlation_id: str = "",
    ) -> AttachmentDownloadResponse | None:
        """Generate a presigned S3 download URL for an attachment.

        Args:
            attachment_id: Unique attachment identifier.
            correlation_id: Tracing ID.

        Returns:
            AttachmentDownloadResponse with presigned URL,
            or None if attachment not found or has no S3 key.
        """
        try:
            row = await self._postgres.fetchrow(
                "SELECT attachment_id, filename, content_type, s3_key "
                "FROM intake.email_attachments "
                "WHERE attachment_id = $1",
                attachment_id,
            )

            if row is None:
                return None

            s3_key = row["s3_key"]
            if not s3_key:
                logger.warning(
                    "Attachment has no S3 key",
                    attachment_id=attachment_id,
                    correlation_id=correlation_id,
                )
                return None

            expiration = 3600  # 1 hour
            url = await self._s3.generate_presigned_url(
                self._settings.s3_bucket_data_store,
                s3_key,
                expiration,
                correlation_id=correlation_id,
            )

            return AttachmentDownloadResponse(
                attachment_id=row["attachment_id"],
                filename=row["filename"],
                download_url=url,
                expires_in_seconds=expiration,
            )

        except Exception:
            logger.exception(
                "Failed to generate attachment download URL",
                attachment_id=attachment_id,
                correlation_id=correlation_id,
            )
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_where_clause(
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
            db_statuses = _STATUS_FILTER_MAP.get(status, [])
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

    async def _batch_fetch_attachments(
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
                file_format=_file_format(row["filename"]),
            )
            result.setdefault(row["message_id"], []).append(summary)

        return result

    def _group_into_chains(
        self,
        email_rows: list[dict],
        attachments_by_message: dict[str, list[AttachmentSummary]],
        ordered_thread_keys: list[str],
    ) -> list[MailChainResponse]:
        """Group email rows into MailChainResponse objects.

        Preserves the ordering of thread_keys (from the paginated query)
        so the API response matches the requested sort order.
        """
        # Group emails by thread key
        chains_map: dict[str, list[dict]] = {}
        for row in email_rows:
            thread_key = row["conversation_id"] or row["query_id"]
            chains_map.setdefault(thread_key, []).append(row)

        # Build chains in the same order as the paginated thread keys
        chains: list[MailChainResponse] = []
        for tk in ordered_thread_keys:
            rows = chains_map.get(tk, [])
            if not rows:
                continue

            # Use the first email's case_status and priority for the chain
            # (all emails in a conversation share the same workflow context)
            first_row = rows[0]
            mail_items = [
                self._row_to_mail_item(
                    row, attachments_by_message.get(row["message_id"], [])
                )
                for row in rows
            ]

            chains.append(
                MailChainResponse(
                    conversation_id=first_row["conversation_id"],
                    mail_items=mail_items,
                    status=_map_status(first_row.get("case_status")),
                    priority=_map_priority(first_row.get("routing_priority")),
                )
            )

        return chains

    @staticmethod
    def _row_to_mail_item(
        row: dict, attachments: list[AttachmentSummary]
    ) -> MailItemResponse:
        """Convert a database row to a MailItemResponse."""
        return MailItemResponse(
            query_id=row["query_id"],
            sender=UserResponse(
                name=row["sender_name"] or row["sender_email"],
                email=row["sender_email"],
            ),
            subject=row["subject"],
            body=row["body_text"] or "",
            timestamp=_format_timestamp(row["received_at"]),
            attachments=attachments,
            thread_status=row["thread_status"] or "NEW",
        )

    @staticmethod
    def _sort_expression(sort_by: str) -> str:
        """Map sort_by parameter to SQL aggregate expression.

        Since we GROUP BY thread_key, sort fields must be aggregated.
        """
        sort_map = {
            "timestamp": "MAX(em.received_at)",
            "status": "MIN(ce.status)",
            "priority": "MIN(rd.priority)",
        }
        return sort_map.get(sort_by, "MAX(em.received_at)")


# ------------------------------------------------------------------
# Module-level helper functions (pure, no side effects)
# ------------------------------------------------------------------


def _map_status(db_status: str | None) -> str:
    """Map a DB workflow status to a dashboard display status.

    Unmapped or NULL → 'New' (safe default for unknown states).
    """
    if not db_status:
        return "New"
    return _STATUS_MAP.get(db_status, "New")


def _map_priority(db_priority: str | None) -> str:
    """Map a DB routing priority to a dashboard display priority.

    Unmapped or NULL → 'Medium' (safe default when routing hasn't run).
    """
    if not db_priority:
        return "Medium"
    return _PRIORITY_MAP.get(db_priority.lower(), "Medium")


def _file_format(filename: str) -> str:
    """Extract the uppercase file extension from a filename.

    'invoice.pdf' → 'PDF', 'report.xlsx' → 'XLSX'.
    No extension → 'UNKNOWN'.
    """
    if "." not in filename:
        return "UNKNOWN"
    ext = filename.rsplit(".", 1)[-1]
    return ext.upper() if ext else "UNKNOWN"


def _format_timestamp(dt: datetime | None) -> str:
    """Format a datetime as ISO 8601 string.

    DB stores naive datetimes in IST (per CLAUDE.md convention).
    Returns empty string for None values.
    """
    if dt is None:
        return ""
    return dt.isoformat()
