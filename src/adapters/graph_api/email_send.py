"""Module: adapters/graph_api/email_send.py

Email sending operations via Microsoft Graph API.

Handles sending outbound emails to vendors via the
/sendMail endpoint. Used by the Delivery node (Step 12)
for both Path A resolution emails and Path B acknowledgments.
"""

from __future__ import annotations

import structlog

from adapters.graph_api.client import GRAPH_BASE_URL
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class EmailSendMixin:
    """Email send methods for the Graph API connector.

    Mixed into GraphAPIConnector. Expects self._request()
    and self._mailbox from GraphAPIClient.
    """

    @log_service_call
    async def send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        *,
        reply_to_message_id: str | None = None,
        correlation_id: str = "",
    ) -> None:
        """Send an email via Graph API.

        When ``reply_to_message_id`` is provided, the message is sent via
        ``/messages/{id}/reply`` so Graph keeps the same conversationId
        and sets the In-Reply-To / References headers — Gmail and Outlook
        will then group the response on the original thread instead of
        starting a new conversation. The ``subject`` argument is ignored
        on the reply path (Graph reuses the original subject prefixed
        with "RE:") which is exactly what threaded clients expect.

        When ``reply_to_message_id`` is None (e.g. portal submissions
        with no inbound email), a standalone /sendMail is used.

        Args:
            to: Recipient email address.
            subject: Email subject (used only for fresh sends, not replies).
            body_html: HTML body content.
            reply_to_message_id: Graph internal message ID of the email
                being replied to. When set, the response is threaded.
            correlation_id: Tracing ID.

        Raises:
            GraphAPIError: On API errors.
        """
        if reply_to_message_id:
            url = (
                f"{GRAPH_BASE_URL}/users/{self._mailbox}"
                f"/messages/{reply_to_message_id}/reply"
            )
            await self._request(
                "POST",
                url,
                json_body={
                    "message": {
                        "body": {"contentType": "HTML", "content": body_html},
                        "toRecipients": [{"emailAddress": {"address": to}}],
                    },
                    "comment": "",
                },
                correlation_id=correlation_id,
            )
            logger.info(
                "Email sent via Graph API (threaded reply)",
                tool="graph_api",
                to=to,
                reply_to_message_id=reply_to_message_id,
                correlation_id=correlation_id,
            )
            return

        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body_html,
            },
            "toRecipients": [
                {"emailAddress": {"address": to}}
            ],
        }

        url = f"{GRAPH_BASE_URL}/users/{self._mailbox}/sendMail"
        await self._request(
            "POST",
            url,
            json_body={"message": message, "saveToSentItems": True},
            correlation_id=correlation_id,
        )

        logger.info(
            "Email sent via Graph API",
            tool="graph_api",
            to=to,
            subject=subject,
            correlation_id=correlation_id,
        )
