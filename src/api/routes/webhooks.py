"""Module: api/routes/webhooks.py

FastAPI routes for webhook handling in VQMS.

Handles Microsoft Graph API webhook notifications
(POST /webhooks/ms-graph) for real-time email detection.

Usage:
    from api.routes.webhooks import router
    app.include_router(router)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from utils.exceptions import DuplicateQueryError

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/ms-graph", response_model=None)
async def ms_graph_webhook(request: Request) -> PlainTextResponse | dict:
    """Handle Microsoft Graph API webhook notifications.

    Two scenarios:
    1. Validation handshake: Graph API sends a GET-like POST with
       validationToken query param. We echo it back as text/plain.
    2. Notification: Graph API sends a POST with notification data.
       We extract the message ID and process the email.

    Returns:
        200 with validationToken on handshake
        202 Accepted on notification
    """
    # Handle validation handshake
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info("Graph webhook validation handshake")
        return PlainTextResponse(content=validation_token, status_code=200)

    # Handle notification
    try:
        body = await request.json()
    except Exception:
        logger.warning("Invalid webhook request body")
        return {"status": "invalid_body"}

    notifications = body.get("value", [])
    email_intake = request.app.state.email_intake

    for notification in notifications:
        resource = notification.get("resource", "")
        # Extract message ID from resource path
        # Format: Users/{mailbox}/Messages/{message_id}
        parts = resource.split("/")
        if len(parts) >= 4 and parts[-2].lower() == "messages":
            message_id = parts[-1]
        else:
            logger.warning("Could not extract message_id from resource", resource=resource)
            continue

        try:
            await email_intake.process_email(message_id)
        except DuplicateQueryError:
            # Expected: webhook + polling might both detect the same email
            logger.info("Webhook duplicate skipped", message_id=message_id)
        except Exception:
            logger.exception("Webhook email processing failed", message_id=message_id)

    return {"status": "accepted"}
