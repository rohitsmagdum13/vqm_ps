"""Module: agents/reviewer_copilot/sse.py

Server-Sent Events serialization helpers.

The Reviewer Copilot agent streams events to the Angular client over
text/event-stream. Each event has a name (event:) and a JSON payload
(data:), terminated by a blank line per the SSE spec.
"""

from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event.

    Args:
        event: Event name. The frontend dispatches on this string.
        data: Payload that will be JSON-encoded.

    Returns:
        A complete SSE event string ending with the required blank line.
    """
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
