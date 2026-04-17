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

        Args:
            to: Recipient email address.
            subject: Email subject.
            body_html: HTML body content.
            reply_to_message_id: Optional message ID to reply to.
            correlation_id: Tracing ID.

        Raises:
            GraphAPIError: On API errors.
        """
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
