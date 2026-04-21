"""Module: api/routes/webhooks.py

FastAPI routes for webhook handling in VQMS.

Handles:
  - Microsoft Graph API webhook notifications (POST /webhooks/ms-graph)
    for real-time email detection.
  - ServiceNow status-change notifications (POST /webhooks/servicenow)
    for Phase 6 Step 15 — when the human team marks a ticket RESOLVED,
    we fetch the work notes and generate a resolution email.

Both webhook paths are in AuthMiddleware's SKIP_PATHS (see
src/api/middleware/auth_middleware.py) so no bearer token is required.
External webhook authenticity should be enforced upstream (HMAC or
IP allowlist at API Gateway); this is a dev-mode stub that trusts
the caller.

Usage:
    from api.routes.webhooks import router
    app.include_router(router)
"""

from __future__ import annotations

import orjson
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from utils.exceptions import DuplicateQueryError
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["webhooks"])


class ServiceNowWebhookPayload(BaseModel):
    """Body for POST /webhooks/servicenow.

    ServiceNow flow sends this when an incident transitions to a
    status we care about (specifically RESOLVED, which means the
    human team finished their investigation and wrote up the
    resolution in work_notes).
    """

    model_config = ConfigDict(frozen=True)

    ticket_id: str = Field(description="ServiceNow incident number, e.g. INC0012345")
    status: str = Field(description="New status — we only act on 'RESOLVED'")
    correlation_id: str | None = Field(
        default=None,
        description="Correlation ID from the original pipeline run. Optional.",
    )


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


@router.post("/webhooks/servicenow", response_model=None)
async def servicenow_webhook(
    payload: ServiceNowWebhookPayload,
    request: Request,
) -> dict:
    """Handle ServiceNow ticket status-change notifications (Phase 6 Step 15).

    When a Path B ticket transitions to RESOLVED, the human team has
    finished their investigation and written up the answer in the
    ServiceNow work_notes. We look up the original query_id from
    workflow.ticket_link, then re-enqueue the case into the pipeline
    with `resume_context.action = "prepare_resolution"` so the
    graph enters the resolution-from-notes branch (Step 15).

    Non-RESOLVED statuses are accepted and ignored — this keeps the
    webhook idempotent and tolerant of future status additions.

    Returns:
        {"status": "ignored"} when status != RESOLVED or no link row.
        {"status": "enqueued", "query_id": ...} on successful re-enqueue.
    """
    correlation_id = payload.correlation_id or IdGenerator.generate_correlation_id()
    ticket_id = payload.ticket_id
    status = payload.status.upper()

    logger.info(
        "ServiceNow webhook received",
        step="webhook",
        ticket_id=ticket_id,
        status=status,
        correlation_id=correlation_id,
    )

    if status != "RESOLVED":
        return {"status": "ignored", "reason": f"status={status} not actionable"}

    postgres = getattr(request.app.state, "postgres", None)
    sqs = getattr(request.app.state, "sqs", None)
    settings = getattr(request.app.state, "settings", None)

    if postgres is None or sqs is None or settings is None:
        logger.error(
            "ServiceNow webhook cannot resume — required services missing",
            step="webhook",
            ticket_id=ticket_id,
            has_postgres=postgres is not None,
            has_sqs=sqs is not None,
            has_settings=settings is not None,
            correlation_id=correlation_id,
        )
        return {"status": "error", "reason": "service not ready"}

    # Look up the query_id this ticket is linked to.
    link_row = await postgres.fetchrow(
        """
        SELECT query_id
        FROM workflow.ticket_link
        WHERE ticket_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        ticket_id,
    )
    if link_row is None:
        logger.warning(
            "ServiceNow webhook — no ticket_link row for ticket_id",
            step="webhook",
            ticket_id=ticket_id,
            correlation_id=correlation_id,
        )
        return {"status": "ignored", "reason": "no linked query"}

    query_id = link_row["query_id"]

    # Load the case_execution row so we can rebuild the unified_payload
    # the pipeline expects when re-entering the graph.
    case_row = await postgres.fetchrow(
        """
        SELECT query_id, correlation_id, execution_id, source,
               analysis_result, vendor_id
        FROM workflow.case_execution
        WHERE query_id = $1
        """,
        query_id,
    )
    if case_row is None:
        logger.warning(
            "ServiceNow webhook — case_execution missing for query_id",
            step="webhook",
            query_id=query_id,
            ticket_id=ticket_id,
            correlation_id=correlation_id,
        )
        return {"status": "ignored", "reason": "no case row"}

    # Use the case's original correlation_id when available so the
    # pipeline run traces back to the same Path B acknowledgment.
    resume_correlation_id = case_row["correlation_id"] or correlation_id

    resume_message = {
        "query_id": query_id,
        "correlation_id": resume_correlation_id,
        "execution_id": case_row["execution_id"],
        "source": case_row["source"],
        "unified_payload": {
            "query_id": query_id,
            "vendor_id": case_row["vendor_id"],
        },
        "resume_context": {
            "action": "prepare_resolution",
            "from_servicenow": True,
            "ticket_id": ticket_id,
            "correlation_id": resume_correlation_id,
            "analysis_result": _decode_jsonb(case_row["analysis_result"]),
        },
    }

    queue_url = settings.sqs_query_intake_queue_url
    if not queue_url:
        logger.error(
            "ServiceNow webhook — sqs_query_intake_queue_url not configured",
            step="webhook",
            query_id=query_id,
            correlation_id=resume_correlation_id,
        )
        return {"status": "error", "reason": "queue url not configured"}

    try:
        await sqs.send_message(
            queue_url,
            resume_message,
            correlation_id=resume_correlation_id,
        )
    except Exception:
        logger.exception(
            "ServiceNow webhook — SQS enqueue failed",
            step="webhook",
            query_id=query_id,
            ticket_id=ticket_id,
            correlation_id=resume_correlation_id,
        )
        return {"status": "error", "reason": "enqueue failed"}

    logger.info(
        "ServiceNow webhook — resolution-from-notes enqueued",
        step="webhook",
        query_id=query_id,
        ticket_id=ticket_id,
        correlation_id=resume_correlation_id,
    )
    return {"status": "enqueued", "query_id": query_id}


def _decode_jsonb(value: object) -> dict:
    """Decode a JSONB column safely into a dict.

    asyncpg normally returns JSONB as a Python dict, but mocks and
    unconfigured pools can return str/bytes. Handle all cases.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        return orjson.loads(value)
    if isinstance(value, str):
        return orjson.loads(value)
    return dict(value)
