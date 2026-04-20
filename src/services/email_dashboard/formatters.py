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
        """Convert a database row to a MailItemResponse."""
        return MailItemResponse(
            query_id=row["query_id"],
            sender=UserResponse(
                name=row["sender_name"] or row["sender_email"],
                email=row["sender_email"],
            ),
            subject=row["subject"],
            body=row["body_text"] or "",
            body_html=row.get("body_html"),
            timestamp=DashboardMapper.format_timestamp(row["received_at"]),
            attachments=attachments,
            thread_status=row["thread_status"] or "NEW",
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
