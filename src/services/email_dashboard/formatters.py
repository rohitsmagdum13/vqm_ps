"""Module: services/email_dashboard/formatters.py

Row-to-model conversion and chain grouping for the email dashboard.

Converts raw database rows into Pydantic response models and
groups emails into conversation chains.
"""

from __future__ import annotations

from models.email_dashboard import (
    AttachmentSummary,
    MailChainResponse,
    MailItemResponse,
    UserResponse,
)
from services.email_dashboard.mappings import DashboardMapper


class DashboardFormatter:
    """Converts database rows into dashboard response models.

    Handles row-to-model mapping and conversation chain grouping.
    Stateless — all methods are static.
    """

    @staticmethod
    def row_to_mail_item(
        row: dict, attachments: list[AttachmentSummary]
    ) -> MailItemResponse:
        """Convert a database row to a MailItemResponse.

        Expects the row to include every non-PII column from
        intake.email_messages. See service.py SELECT lists.
        """
        return MailItemResponse(
            query_id=row["query_id"],
            message_id=row["message_id"],
            correlation_id=row["correlation_id"],
            sender=UserResponse(
                name=row["sender_name"] or row["sender_email"],
                email=row["sender_email"],
            ),
            subject=row["subject"],
            body=row["body_text"] or "",
            body_html=row.get("body_html"),
            timestamp=DashboardMapper.format_timestamp(row["received_at"]),
            parsed_at=DashboardMapper.format_timestamp(row.get("parsed_at")),
            created_at=DashboardMapper.format_timestamp(row.get("created_at")),
            in_reply_to=row.get("in_reply_to"),
            conversation_id=row.get("conversation_id"),
            thread_status=row["thread_status"] or "NEW",
            vendor_id=row.get("vendor_id"),
            vendor_match_method=row.get("vendor_match_method"),
            s3_raw_email_key=row.get("s3_raw_email_key"),
            source=row.get("source") or "email",
            attachments=attachments,
        )

    @staticmethod
    def group_into_chains(
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
            first_row = rows[0]
            mail_items = [
                DashboardFormatter.row_to_mail_item(
                    row, attachments_by_message.get(row["message_id"], [])
                )
                for row in rows
            ]

            chains.append(
                MailChainResponse(
                    conversation_id=first_row["conversation_id"],
                    mail_items=mail_items,
                    status=DashboardMapper.map_status(first_row.get("case_status")),
                    priority=DashboardMapper.map_priority(first_row.get("routing_priority")),
                )
            )

        return chains
