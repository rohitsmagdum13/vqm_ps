"""Package: agents.reviewer_copilot

Path C Reviewer Copilot agent.

Runs in-process inside the FastAPI app. Opens an MCP session against
the reviewer MCP server (separate process), builds a LangGraph ReAct
agent backed by the LLM gateway (Bedrock primary, OpenAI fallback),
and streams events back as Server-Sent Events.

Public surface:
- stream_copilot(query_id, question, correlation_id): async generator
  yielding SSE-formatted strings.
"""

from agents.reviewer_copilot.agent import stream_copilot

__all__ = ["stream_copilot"]
