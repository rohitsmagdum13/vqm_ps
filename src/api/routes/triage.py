"""Module: api/routes/triage.py

FastAPI routes for Path C human review (triage).

Three endpoints back the reviewer portal:

    GET  /triage/queue        — List pending packages for the queue.
    GET  /triage/{query_id}   — Fetch one package's full detail.
    POST /triage/{query_id}/review — Submit corrections and resume workflow.

All endpoints require REVIEWER or ADMIN role. Vendor role is explicitly
rejected — a vendor should never see another vendor's triage package.

Corresponds to Steps 8C.2 and 8C.3 in the VQMS Architecture Document.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from models.triage import ReviewerDecision
from services.triage import (
    TriageAlreadyReviewedError,
    TriagePackageNotFoundError,
)
from utils.decorators import log_api_call
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/triage", tags=["triage"])

# Roles permitted to access triage endpoints. ADMIN is allowed so
# operations staff can audit the queue without a REVIEWER role.
ALLOWED_ROLES: frozenset[str] = frozenset({"REVIEWER", "ADMIN"})


class ReviewerDecisionRequest(BaseModel):
    """Request body for POST /triage/{query_id}/review.

    Separate from the ReviewerDecision model so the reviewer_id and
    decided_at fields don't need to be submitted — they come from
    JWT claims and server clock respectively.
    """

    model_config = ConfigDict(frozen=True)

    corrected_intent: str | None = Field(
        default=None,
        description="Corrected intent classification",
    )
    corrected_vendor_id: str | None = Field(
        default=None,
        description="Corrected vendor ID",
    )
    corrected_routing: str | None = Field(
        default=None,
        description="Corrected routing team",
    )
    confidence_override: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Reviewer's confidence override (0.0-1.0)",
    )
    reviewer_notes: str = Field(
        min_length=1,
        description="Reviewer's notes explaining the corrections",
    )


def _require_reviewer(request: Request) -> str:
    """Check the caller is REVIEWER or ADMIN and return their user id.

    Raises:
        HTTPException 403: If the role is absent or not in ALLOWED_ROLES.
    """
    role = getattr(request.state, "role", None)
    username = getattr(request.state, "username", None)
    if role not in ALLOWED_ROLES or username is None:
        raise HTTPException(
            status_code=403,
            detail=(
                "Reviewer or Admin access required. Your role: "
                + (role or "unauthenticated")
            ),
        )
    return username


# ---------------------------------------------------------------
# GET /triage/queue — List pending triage packages
# ---------------------------------------------------------------


@router.get("/queue")
@log_api_call
async def list_triage_queue(request: Request, limit: int = 50) -> dict:
    """List pending triage packages ordered by oldest first.

    Oldest first so older cases don't get starved behind newer ones.
    The response is small (summary fields only); reviewers open one
    package to see full detail.

    Query params:
        limit: Maximum packages to return (1-200, default 50).

    Returns:
        { "packages": [ TriageQueueItem, ... ] }
    """
    _require_reviewer(request)

    correlation_id = IdGenerator.generate_correlation_id()

    triage_service = request.app.state.triage_service
    if triage_service is None:
        # Triage service can be None if PostgreSQL was unreachable at
        # startup. Don't 503 the whole page — return an empty queue so
        # the UI renders cleanly. The warning log gives ops a signal.
        logger.warning(
            "Triage service unavailable — returning empty queue",
            correlation_id=correlation_id,
        )
        return {"packages": []}

    try:
        items = await triage_service.list_pending(
            limit=limit,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        # Most common cause: the workflow.triage_packages table doesn't
        # exist yet (migration 011 not applied). Return an empty queue
        # with a warning instead of a 500 that breaks the page.
        logger.warning(
            "Triage queue query failed — returning empty queue",
            error=str(exc),
            correlation_id=correlation_id,
        )
        return {"packages": []}

    return {"packages": [item.model_dump(mode="json") for item in items]}


# ---------------------------------------------------------------
# GET /triage/{query_id} — Fetch full triage package detail
# ---------------------------------------------------------------


@router.get("/{query_id}")
@log_api_call
async def get_triage_package(request: Request, query_id: str) -> dict:
    """Fetch the full triage package for a query.

    Returns the stored TriagePackage JSON exactly as persisted
    when the pipeline paused. Reviewers use this to build their
    correction form.
    """
    _require_reviewer(request)

    correlation_id = IdGenerator.generate_correlation_id()

    triage_service = request.app.state.triage_service
    if triage_service is None:
        # No service = no package. 404 is more useful than 503 here
        # because the UI handles missing-case gracefully.
        logger.warning(
            "Triage service unavailable — treating package as not found",
            query_id=query_id,
            correlation_id=correlation_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Triage package not found: query_id={query_id}",
        )

    try:
        package = await triage_service.get_package(
            query_id,
            correlation_id=correlation_id,
        )
    except TriagePackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        # Likely the triage_packages table is missing or the JSONB
        # decode failed. Log and surface as 404 so the UI shows a
        # clear "case not found" instead of a generic 500.
        logger.warning(
            "Triage package fetch failed — treating as not found",
            query_id=query_id,
            error=str(exc),
            correlation_id=correlation_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Triage package not available: {exc}",
        ) from exc

    return package.model_dump(mode="json")


# ---------------------------------------------------------------
# POST /triage/{query_id}/review — Submit corrections and resume
# ---------------------------------------------------------------


@router.post("/{query_id}/review")
@log_api_call
async def submit_triage_review(
    request: Request,
    query_id: str,
    review_request: ReviewerDecisionRequest,
) -> dict:
    """Submit the reviewer's corrections and resume the paused workflow.

    The service merges corrections into the stored analysis, marks
    the package REVIEWED, and re-enqueues the unified payload to
    SQS so the pipeline resumes from context loading with corrected
    data. Confidence becomes 1.0 (or the reviewer's override), so
    the re-run skips Path C entirely.

    Returns:
        { "status": "REVIEWED", "query_id": ..., "resume_method": "sqs" | "db_only" }
    """
    reviewer_id = _require_reviewer(request)

    triage_service = request.app.state.triage_service
    if triage_service is None:
        raise HTTPException(
            status_code=503,
            detail="Triage service unavailable — check PostgreSQL connection",
        )

    correlation_id = IdGenerator.generate_correlation_id()
    decision = ReviewerDecision(
        query_id=query_id,
        reviewer_id=reviewer_id,
        corrected_intent=review_request.corrected_intent,
        corrected_vendor_id=review_request.corrected_vendor_id,
        corrected_routing=review_request.corrected_routing,
        confidence_override=review_request.confidence_override,
        reviewer_notes=review_request.reviewer_notes,
        decided_at=TimeHelper.ist_now(),
    )

    try:
        result = await triage_service.submit_decision(
            query_id,
            decision,
            correlation_id=correlation_id,
        )
    except TriagePackageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TriageAlreadyReviewedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return result
