"""Module: services/email_dashboard/formatters.py

Row-to-model conversion and chain grouping for the email dashboard.

Converts raw database rows into Pydantic response models and
groups emails into conversation chains.
"""

from __future__ import annotations

import orjson

from models.email_dashboard import (
    AttachmentSummary,
    MailChainResponse,
    MailItemResponse,
    UserResponse,
)
from services.email_dashboard.mappings import DashboardMapper


def _decode_recipients(value: object) -> list[UserResponse]:
    """Decode a JSONB recipients column into a list of UserResponse.

    asyncpg may return a JSONB value as list/dict (if a codec is
    registered), as bytes, or as a str. Handle all shapes and tolerate
    missing name/email fields so the API never 500s on bad data.
    """
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray)):
        value = orjson.loads(value)
    elif isinstance(value, str):
        value = orjson.loads(value) if value else []

    if not isinstance(value, list):
        return []

    out: list[UserResponse] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        email = item.get("email") or ""
        if not email:
            continue
        name = item.get("name") or email
        out.append(UserResponse(name=name, email=email))
    return out


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
            internet_message_id=row.get("internet_message_id"),
            sender=UserResponse(
                name=row["sender_name"] or row["sender_email"],
                email=row["sender_email"],
            ),
            to_recipients=_decode_recipients(row.get("to_recipients")),
            cc_recipients=_decode_recipients(row.get("cc_recipients")),
            bcc_recipients=_decode_recipients(row.get("bcc_recipients")),
            reply_to=_decode_recipients(row.get("reply_to")),
            subject=row["subject"],
            body=row["body_text"] or "",
            body_html=row.get("body_html"),
            importance=row.get("importance"),
            has_attachments=bool(row.get("has_attachments", False)),
            web_link=row.get("web_link"),
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
