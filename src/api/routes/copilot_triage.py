"""Module: api/routes/copilot_triage.py

FastAPI route that streams the Path C reviewer copilot.

POST /copilot/triage/{query_id}/ask
  Body: {"question": "..."}
  Auth: REVIEWER or ADMIN role required (vendor JWTs explicitly rejected).
  Response: text/event-stream (SSE).

The route delegates the agent loop to
src/agents/reviewer_copilot/agent.py, which opens an MCP session
against the reviewer MCP server (separate process), runs a LangGraph
ReAct agent, and yields SSE-formatted strings.

The agent module is imported lazily inside the request handler so the
app boots cleanly even when copilot-only dependencies (langchain-mcp-
adapters, langchain-openai, mcp) are not installed in the current
environment. A missing dependency or unset MCP URL surfaces as a
graceful SSE 'error' event instead of a 500 / 404.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/copilot/triage", tags=["copilot"])

# Same role gate as /triage routes — only ADMIN/REVIEWER may use the
# copilot, since the tools surface vendor + ticket data the reviewer
# is already authorised to see.
ALLOWED_ROLES: frozenset[str] = frozenset({"REVIEWER", "ADMIN"})


class AskRequest(BaseModel):
    """Body of POST /copilot/triage/{query_id}/ask."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(
        min_length=1,
        max_length=2000,
        description="The reviewer's question about this triage case.",
    )


def _require_reviewer(request: Request) -> str:
    """Return the username if the caller is REVIEWER or ADMIN.

    Raises:
        HTTPException 403: when the role is absent or not allowed.
    """
    role = getattr(request.state, "role", None)
    username = getattr(request.state, "username", None)
    if role not in ALLOWED_ROLES or username is None:
        raise HTTPException(
            status_code=403,
            detail="Reviewer or Admin access required for the copilot.",
        )
    return username


def _sse(event: str, data: dict) -> str:
    """Tiny SSE serializer used only for the graceful-failure paths.

    The full agent has its own helper in
    :mod:`agents.reviewer_copilot.sse`; we duplicate a couple of lines
    here so the route can respond without importing the agent.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _unavailable_stream(message: str) -> AsyncIterator[str]:
    """Emit a single 'error' SSE event followed by 'done'.

    Used when the copilot stack can't run (missing dependency or
    missing MCP config) so the UI shows a clean message instead of a
    raw HTTP error.
    """
    yield _sse("error", {"message": message})
    yield _sse("done", {})


@router.post("/{query_id}/ask")
async def ask_copilot(
    query_id: str,
    body: AskRequest,
    request: Request,
) -> StreamingResponse:
    """Stream the reviewer copilot's response for one question.

    Args:
        query_id: VQMS query ID being investigated (e.g. 'VQ-2026-0123').
        body: The reviewer's question.
        request: FastAPI request — used for JWT-derived state and headers.

    Returns:
        StreamingResponse with media_type='text/event-stream'. Each
        event is one of:
            tool_call, tool_result, warning, final, error, done.
    """
    username = _require_reviewer(request)

    # Either propagate the X-Correlation-ID header set by the caller or
    # mint a fresh one. Either way the agent logs it on every tool call.
    correlation_id = (
        request.headers.get("X-Correlation-ID") or IdGenerator.generate_correlation_id()
    )

    sse_headers = {
        # Disable proxy-level buffering so events reach the browser
        # as they're emitted, not in 4KB batches.
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
        "X-Correlation-ID": correlation_id,
    }

    # Lazy-import so the app boots even if copilot-only deps are absent.
    try:
        from agents.reviewer_copilot.agent import stream_copilot
    except ImportError as exc:
        logger.warning(
            "Copilot dependencies unavailable",
            tool="reviewer_copilot",
            query_id=query_id,
            error=str(exc),
            correlation_id=correlation_id,
        )
        return StreamingResponse(
            _unavailable_stream(
                "Reviewer copilot is not available in this environment "
                f"(missing dependency: {exc})."
            ),
            media_type="text/event-stream",
            headers=sse_headers,
        )

    # Reject early if the MCP reviewer URL isn't configured. Without it
    # `stream_copilot` would raise AttributeError mid-stream, which the
    # browser would see as an aborted connection.
    from config.settings import get_settings

    settings = get_settings()
    if not getattr(settings, "mcp_reviewer_url", None):
        logger.warning(
            "MCP reviewer URL not configured",
            tool="reviewer_copilot",
            query_id=query_id,
            correlation_id=correlation_id,
        )
        return StreamingResponse(
            _unavailable_stream(
                "Reviewer copilot is not configured "
                "(MCP_REVIEWER_URL is missing in settings)."
            ),
            media_type="text/event-stream",
            headers=sse_headers,
        )

    logger.info(
        "Copilot stream starting",
        tool="reviewer_copilot",
        query_id=query_id,
        username=username,
        correlation_id=correlation_id,
        question_len=len(body.question),
    )

    return StreamingResponse(
        stream_copilot(query_id, body.question, correlation_id),
        media_type="text/event-stream",
        headers=sse_headers,
    )
