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

        Pulls sender, all recipient lists (to/cc/bcc/replyTo), subject,
        body, importance, attachment flag, web link, and thread headers
        from the Graph API response format.
        """
        from_field = raw_email.get("from", {}).get("emailAddress", {})
        sender_email = from_field.get("address", "unknown@unknown.com")
        sender_name = from_field.get("name")

        # Extract all recipient lists as structured {name, email} objects.
        # Legacy `recipients` (list[str]) is kept for backward compatibility
        # with ParsedEmailPayload — it mirrors to_recipients as addresses only.
        to_recipients = EmailParser._extract_recipients(raw_email.get("toRecipients", []))
        cc_recipients = EmailParser._extract_recipients(raw_email.get("ccRecipients", []))
        bcc_recipients = EmailParser._extract_recipients(raw_email.get("bccRecipients", []))
        reply_to = EmailParser._extract_recipients(raw_email.get("replyTo", []))
        recipients_flat = [r["email"] for r in to_recipients if r.get("email")]

        # Extract body
        body_obj = raw_email.get("body", {})
        body_html = body_obj.get("content", "")
        body_text = EmailParser.html_to_text(body_html)
        body_preview = raw_email.get("bodyPreview", "")

        # Extract headers for thread correlation + RFC Message-ID
        in_reply_to = ""
        references_list: list[str] = []
        internet_message_id: str | None = None
        for header in raw_email.get("internetMessageHeaders", []):
            name = header.get("name", "")
            value = header.get("value", "")
            if name == "In-Reply-To":
                in_reply_to = value
            elif name == "References":
                references_list = [ref.strip() for ref in value.split() if ref.strip()]
            elif name == "Message-ID":
                internet_message_id = value

        return {
            "sender_email": sender_email,
            "sender_name": sender_name,
            "recipients": recipients_flat,
            "to_recipients": to_recipients,
            "cc_recipients": cc_recipients,
            "bcc_recipients": bcc_recipients,
            "reply_to": reply_to,
            "subject": raw_email.get("subject", ""),
            "body_html": body_html,
            "body_text": body_text or body_preview,
            "body_preview": body_preview,
            "conversation_id": raw_email.get("conversationId"),
            "in_reply_to": in_reply_to or None,
            "references": references_list,
            "importance": raw_email.get("importance"),
            "has_attachments": bool(raw_email.get("hasAttachments", False)),
            "web_link": raw_email.get("webLink"),
            "internet_message_id": internet_message_id,
        }

    @staticmethod
    def _extract_recipients(raw: list[dict]) -> list[dict]:
        """Normalize a Graph API recipients array to [{name, email}, ...].

        Graph gives us items like {"emailAddress": {"name": "...", "address": "..."}}.
        Drop anything without an address — display names are optional but
        addresses are the only thing downstream systems can rely on.
        """
        out: list[dict] = []
        for r in raw or []:
            ea = r.get("emailAddress", {}) or {}
            addr = ea.get("address")
            if not addr:
                continue
            out.append({"name": ea.get("name"), "email": addr})
        return out

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
