"""Module: services/email_intake/parser.py

Email field parsing and HTML-to-text conversion.

Extracts structured fields (sender, recipients, subject, body,
thread headers) from a Microsoft Graph API message response.
"""

from __future__ import annotations

import re


class EmailParser:
    """Parses raw Graph API email responses into structured fields.

    Stateless — all methods are static. Grouped as a class for
    namespacing and to follow the project's class-based convention.
    """

    @staticmethod
    def parse_email_fields(raw_email: dict) -> dict:
        """Extract structured fields from a Graph API message response.

        Pulls sender, recipients, subject, body, conversation ID,
        and reply-to headers from the Graph API response format.
        """
        from_field = raw_email.get("from", {}).get("emailAddress", {})
        sender_email = from_field.get("address", "unknown@unknown.com")
        sender_name = from_field.get("name")

        # Extract recipients
        recipients = []
        for r in raw_email.get("toRecipients", []):
            addr = r.get("emailAddress", {}).get("address", "")
            if addr:
                recipients.append(addr)

        # Extract body
        body_obj = raw_email.get("body", {})
        body_html = body_obj.get("content", "")
        body_text = EmailParser.html_to_text(body_html)
        body_preview = raw_email.get("bodyPreview", "")

        # Extract headers for thread correlation
        in_reply_to = ""
        references_list: list[str] = []
        for header in raw_email.get("internetMessageHeaders", []):
            name = header.get("name", "")
            value = header.get("value", "")
            if name == "In-Reply-To":
                in_reply_to = value
            elif name == "References":
                references_list = [ref.strip() for ref in value.split() if ref.strip()]

        return {
            "sender_email": sender_email,
            "sender_name": sender_name,
            "recipients": recipients,
            "subject": raw_email.get("subject", ""),
            "body_html": body_html,
            "body_text": body_text or body_preview,
            "body_preview": body_preview,
            "conversation_id": raw_email.get("conversationId"),
            "in_reply_to": in_reply_to or None,
            "references": references_list,
        }

    @staticmethod
    def html_to_text(html: str) -> str:
        """Convert HTML to plain text by stripping tags.

        Simple regex-based approach for development. In production,
        consider using beautifulsoup4 for more robust parsing.
        """
        if not html:
            return ""
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        # Collapse multiple whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text
