"""Module: utils/context.py

Cross-call context for pipeline observability.

The ``@log_llm_call`` decorator and the trail wrapper need to know the
``query_id`` of the request currently in flight, but adding ``query_id``
to every function signature would touch every adapter. We use a
``ContextVar`` instead: ``sqs_consumer.process_message`` binds it before
invoking the graph and resets it in a ``finally``, so all downstream
calls (including LLM calls deep inside Bedrock/OpenAI adapters) can
read it without a code change.

Also exposes a single ExecutionTrailService instance — set once on
startup by :mod:`app.lifespan` so the LLM decorator can record sub-step
rows without an explicit dependency injection through the call stack.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.execution_trail import ExecutionTrailService


# Empty string when no query is in flight (e.g. health checks, admin lists).
_query_id_var: ContextVar[str] = ContextVar("vqms_query_id", default="")

# The active trail service — set on startup, read by the LLM decorator.
# None means observability is off (e.g. tests, scripts) and audit writes
# should be skipped silently.
_trail_service: "ExecutionTrailService | None" = None


def get_query_id() -> str:
    """Return the query_id bound for the current async task, or ''."""
    return _query_id_var.get()


def bind_query_id(query_id: str) -> object:
    """Bind ``query_id`` for downstream calls in this task.

    Returns a token. Pass it to :func:`reset_query_id` in a ``finally``
    block to restore the previous value.
    """
    return _query_id_var.set(query_id or "")


def reset_query_id(token: object) -> None:
    """Restore the value of ``query_id`` from before the matching ``bind``."""
    _query_id_var.reset(token)  # type: ignore[arg-type]


def set_trail_service(service: "ExecutionTrailService | None") -> None:
    """Install the global trail service (called once on startup)."""
    global _trail_service
    _trail_service = service


def get_trail_service() -> "ExecutionTrailService | None":
    """Return the active trail service, or None if not configured."""
    return _trail_service
