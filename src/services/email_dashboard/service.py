"""Module: services/email_dashboard/service.py

Email Dashboard Service — main facade.

Provides read-only query methods for the email dashboard API.
All data comes from existing PostgreSQL tables — no writes,
no mutations, no side effects.

Delegates to DashboardQueryBuilder for SQL queries,
DashboardFormatter for row-to-model conversion,
and DashboardMapper for status/priority mapping.

Usage:
    service = EmailDashboardService(postgres, s3, settings)
    chains = await service.list_email_chains(page=1, page_size=20)
    stats = await service.get_stats(correlation_id="abc-123")
"""

from __future__ import annotations

from datetime import date, timedelta

import structlog

from config.settings import Settings
from db.connection import PostgresConnector
from storage.s3_client import S3Connector
from models.email_dashboard import (
    AttachmentDownloadResponse,
    EmailStatsResponse,
    MailChainListResponse,
    MailChainResponse,
)
from services.email_dashboard.formatters import DashboardFormatter
from services.email_dashboard.mappings import (
    NEW_STATUSES_SQL,
    DashboardMapper,
)
from services.email_dashboard.queries import DashboardQueryBuilder
from utils.decorators import log_service_call
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


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
        self._query_builder = DashboardQueryBuilder(
            postgres, s3, settings.s3_bucket_data_store
        )

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
            where_clause, params, idx = self._query_builder.build_where_clause(
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
            sort_expr = DashboardQueryBuilder.sort_expression(sort_by)
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

            # Step 3: Fetch all emails for these thread keys.
            # Select every non-PII column on intake.email_messages so
            # MailItemResponse can expose the full record.
            tk_placeholders = ", ".join(f"${i + 1}" for i in range(len(thread_keys)))
            emails_sql = (
                "SELECT em.query_id, em.message_id, em.correlation_id, "
                "em.internet_message_id, "
                "em.sender_email, em.sender_name, "
                "em.to_recipients, em.cc_recipients, em.bcc_recipients, em.reply_to, "
                "em.subject, em.body_text, em.body_html, "
                "em.importance, em.has_attachments, em.web_link, "
                "em.received_at, em.parsed_at, em.created_at, "
                "em.in_reply_to, em.conversation_id, em.thread_status, "
                "em.vendor_id, em.vendor_match_method, "
                "em.s3_raw_email_key, em.source, "
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
            attachments_by_message = await self._query_builder.batch_fetch_attachments(
                message_ids, correlation_id=correlation_id
            )

            # Group emails into chains preserving page order
            mail_chains = DashboardFormatter.group_into_chains(
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
        Includes a 10-day-by-day breakdown of new vs. resolved counts
        for sparkline rendering on the dashboard.
        """
        try:
            now = TimeHelper.ist_now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=7)
            # Window covers today + 9 prior days (10 buckets total). Resolved
            # uses `updated_at` because RESOLVED/CLOSED is a terminal status —
            # the row's last touch is when it was resolved.
            ten_days_start = today_start - timedelta(days=9)

            # Main stats query — single pass over case_execution
            stats_sql = (
                "SELECT "
                "COUNT(*) AS total, "
                f"COUNT(*) FILTER (WHERE ce.status IN ({NEW_STATUSES_SQL})) AS new_count, "
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
            priority_breakdown: dict[str, int] = self._empty_priority_breakdown()
            for row in priority_rows:
                display_priority = DashboardMapper.map_priority(row["priority"])
                priority_breakdown[display_priority] += row["cnt"]

            # 10-day daily breakdown for new + resolved.
            # Two separate queries because `new_count` is keyed off
            # `created_at` (when the email was ingested) while
            # `resolved_count` is keyed off `updated_at` (when it
            # transitioned to RESOLVED/CLOSED). Joining them in one
            # query would double-count or fail to align days.
            new_daily_sql = (
                "SELECT date_trunc('day', ce.created_at)::date AS day, "
                "COUNT(*) AS cnt "
                f"FROM workflow.case_execution ce "
                f"WHERE ce.source = 'email' "
                f"AND ce.status IN ({NEW_STATUSES_SQL}) "
                "AND ce.created_at >= $1 "
                "GROUP BY day"
            )
            resolved_daily_sql = (
                "SELECT date_trunc('day', ce.updated_at)::date AS day, "
                "COUNT(*) AS cnt "
                "FROM workflow.case_execution ce "
                "WHERE ce.source = 'email' "
                "AND ce.status IN ('RESOLVED', 'CLOSED') "
                "AND ce.updated_at >= $1 "
                "GROUP BY day"
            )
            new_daily_rows = await self._postgres.fetch(new_daily_sql, ten_days_start)
            resolved_daily_rows = await self._postgres.fetch(
                resolved_daily_sql, ten_days_start
            )
            past_10_days_new = self._fill_daily_buckets(
                new_daily_rows, today_start.date()
            )
            past_10_days_resolved = self._fill_daily_buckets(
                resolved_daily_rows, today_start.date()
            )

            if stats_row:
                return EmailStatsResponse(
                    total_emails=stats_row["total"],
                    new_count=stats_row["new_count"],
                    reopened_count=stats_row["reopened_count"],
                    resolved_count=stats_row["resolved_count"],
                    priority_breakdown=priority_breakdown,
                    today_count=stats_row["today_count"],
                    this_week_count=stats_row["week_count"],
                    past_10_days_new=past_10_days_new,
                    past_10_days_resolved=past_10_days_resolved,
                )

            return EmailStatsResponse(
                total_emails=0,
                new_count=0,
                reopened_count=0,
                resolved_count=0,
                priority_breakdown=priority_breakdown,
                today_count=0,
                this_week_count=0,
                past_10_days_new=past_10_days_new,
                past_10_days_resolved=past_10_days_resolved,
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
                priority_breakdown=self._empty_priority_breakdown(),
                today_count=0,
                this_week_count=0,
                past_10_days_new=[0] * 10,
                past_10_days_resolved=[0] * 10,
            )

    @staticmethod
    def _empty_priority_breakdown() -> dict[str, int]:
        """Seed dict with all four buckets so the response shape is stable
        even when no rows exist for a given priority."""
        return {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}

    @staticmethod
    def _fill_daily_buckets(
        rows: list[dict],
        end_date: date,
        window_days: int = 10,
    ) -> list[int]:
        """Project per-day count rows onto a fixed-length array, oldest →
        newest, ending with `end_date` (today). Days with no rows become 0
        so the frontend never has to handle gaps. Returned list length is
        always exactly `window_days`.
        """
        by_day: dict[date, int] = {row["day"]: row["cnt"] for row in rows}
        return [
            by_day.get(end_date - timedelta(days=offset), 0)
            for offset in range(window_days - 1, -1, -1)
        ]

    @log_service_call
    async def get_email_chain(
        self,
        query_id: str,
        *,
        correlation_id: str = "",
    ) -> MailChainResponse | None:
        """Get a single email chain by query_id.

        If the email has a conversation_id, returns the full thread.
        Otherwise returns just the single email.
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

            # Fetch all emails in the thread. Same full SELECT as
            # list_email_chains so MailItemResponse gets every column.
            mail_item_columns = (
                "em.query_id, em.message_id, em.correlation_id, "
                "em.internet_message_id, "
                "em.sender_email, em.sender_name, "
                "em.to_recipients, em.cc_recipients, em.bcc_recipients, em.reply_to, "
                "em.subject, em.body_text, em.body_html, "
                "em.importance, em.has_attachments, em.web_link, "
                "em.received_at, em.parsed_at, em.created_at, "
                "em.in_reply_to, em.conversation_id, em.thread_status, "
                "em.vendor_id, em.vendor_match_method, "
                "em.s3_raw_email_key, em.source"
            )
            if conversation_id:
                emails_sql = (
                    f"SELECT {mail_item_columns} "
                    "FROM intake.email_messages em "
                    "WHERE em.conversation_id = $1 "
                    "ORDER BY em.received_at DESC"
                )
                email_rows = await self._postgres.fetch(emails_sql, conversation_id)
            else:
                emails_sql = (
                    f"SELECT {mail_item_columns} "
                    "FROM intake.email_messages em "
                    "WHERE em.query_id = $1 "
                    "ORDER BY em.received_at DESC"
                )
                email_rows = await self._postgres.fetch(emails_sql, query_id)

            # Batch-fetch attachments
            message_ids = [row["message_id"] for row in email_rows]
            attachments_by_message = await self._query_builder.batch_fetch_attachments(
                message_ids, correlation_id=correlation_id
            )

            # Build mail items
            mail_items = [
                DashboardFormatter.row_to_mail_item(
                    row, attachments_by_message.get(row["message_id"], [])
                )
                for row in email_rows
            ]

            return MailChainResponse(
                conversation_id=conversation_id,
                mail_items=mail_items,
                status=DashboardMapper.map_status(case_status),
                priority=DashboardMapper.map_priority(routing_priority),
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
        """Generate a presigned S3 download URL for an attachment."""
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
