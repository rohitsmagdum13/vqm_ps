"""Module: agents/reviewer_copilot/agent.py

Path C Reviewer Copilot agent loop.

Opens an MCP session against the reviewer MCP server, builds a
LangGraph ReAct agent, and streams events back as SSE strings.

LLM strategy: Bedrock primary, OpenAI fallback at the *request* level.
If the Bedrock-backed agent raises during the loop, we restart the
loop with an OpenAI-backed agent and emit a warning event so the user
sees what happened. This is simpler than per-call fallback (which the
LLM gateway already does for direct adapter calls) and matches the
"interactive request" semantics — if the primary is down, switch and
retry the whole question.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from langchain_aws import ChatBedrock
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agents.reviewer_copilot.sse import sse_event
from config.settings import Settings, get_settings
from mcp_servers.reviewer.prompt import SYSTEM_PROMPT

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def _open_mcp_session(mcp_url: str):
    """Open an MCP client session and discover the tool surface.

    The streamable-http transport requires both `streamablehttp_client`
    (which manages the HTTP connection) and `ClientSession` (which
    handles the MCP handshake on top).
    """
    async with streamablehttp_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _build_bedrock_llm(settings: Settings) -> BaseChatModel:
    """Build a Bedrock-backed chat model.

    Uses the same model ID and region the rest of VQMS uses for direct
    LLM calls so the agent's tool-selection style matches the analysis
    and resolution agents.
    """
    return ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.bedrock_region,
        model_kwargs={
            "temperature": 0,
            "max_tokens": settings.bedrock_max_tokens,
        },
    )


def _build_openai_llm(settings: Settings) -> BaseChatModel:
    """Build an OpenAI-backed chat model used as the fallback.

    Honors the same `OPENAI_API_BASE_URL` setting the rest of the
    project uses, which lets us point at the Great Learning proxy in
    the dev environment without code changes.
    """
    if not settings.openai_api_key:
        raise RuntimeError(
            "OpenAI fallback requested but OPENAI_API_KEY is not set in .env."
        )
    return ChatOpenAI(
        model=settings.copilot_openai_model,
        temperature=0,
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base_url or None,
    )


def _serialize_messages(messages: list) -> list[str]:
    """Convert a node's emitted messages into SSE event strings.

    The ReAct prebuilt agent emits two flavours of update:
    - "agent" node → AIMessage that may carry tool_calls (model
      decided to call tools) OR text content (model is producing the
      final answer).
    - "tools" node → one ToolMessage per tool that just ran.

    We surface tool_calls and tool_results as discrete events so the
    UI can render each step as soon as it lands. The final AI content
    is emitted as a single 'final' event.
    """
    events: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                events.append(
                    sse_event(
                        "tool_call",
                        {"name": tc.get("name"), "args": tc.get("args", {})},
                    )
                )
            if not tool_calls and msg.content:
                events.append(sse_event("final", {"content": str(msg.content)}))
        elif isinstance(msg, ToolMessage):
            events.append(
                sse_event(
                    "tool_result",
                    {"name": getattr(msg, "name", ""), "content": str(msg.content)},
                )
            )
    return events


async def _run_with_llm(
    llm: BaseChatModel,
    tools: list,
    query_id: str,
    question: str,
    recursion_limit: int,
    correlation_id: str,
) -> AsyncIterator[str]:
    """Run a single ReAct loop and yield SSE event strings.

    Uses ``stream_mode="updates"`` so each yield from astream is the
    set of *new* messages a node added — no dedup needed on our side.
    """
    agent = create_react_agent(llm, tools=tools, prompt=SYSTEM_PROMPT)
    user_msg = HumanMessage(
        content=f"Query ID: {query_id}\n\nReviewer asks: {question}"
    )
    config = {"recursion_limit": recursion_limit}

    logger.info(
        "Reviewer copilot agent starting",
        tool="reviewer_copilot",
        correlation_id=correlation_id,
        query_id=query_id,
        recursion_limit=recursion_limit,
    )

    async for update in agent.astream(
        {"messages": [user_msg]},
        config=config,
        stream_mode="updates",
    ):
        # update shape: {node_name: {"messages": [...]}}.
        for _, node_state in update.items():
            if not isinstance(node_state, dict):
                continue
            for sse in _serialize_messages(node_state.get("messages") or []):
                yield sse

    logger.info(
        "Reviewer copilot agent finished",
        tool="reviewer_copilot",
        correlation_id=correlation_id,
        query_id=query_id,
    )


async def stream_copilot(
    query_id: str,
    question: str,
    correlation_id: str,
) -> AsyncIterator[str]:
    """Top-level SSE streaming generator for one reviewer question.

    Strategy:
    1. Open MCP session and discover tools.
    2. Run agent with Bedrock first.
    3. On exception, emit a 'warning' event and retry with OpenAI.
    4. On second exception, emit 'error'.
    5. Always emit 'done' at the end so the client can close cleanly.
    """
    settings = get_settings()

    try:
        async with _open_mcp_session(settings.mcp_reviewer_url) as session:
            tools = await load_mcp_tools(session)

            # Try Bedrock-backed agent.
            try:
                async for sse in _run_with_llm(
                    _build_bedrock_llm(settings),
                    tools,
                    query_id,
                    question,
                    settings.copilot_recursion_limit,
                    correlation_id,
                ):
                    yield sse
            except Exception as primary_err:  # noqa: BLE001 — fall back to OpenAI on any failure
                logger.warning(
                    "Bedrock agent failed — falling back to OpenAI",
                    tool="reviewer_copilot",
                    correlation_id=correlation_id,
                    error=str(primary_err),
                )
                yield sse_event(
                    "warning",
                    {"message": f"Bedrock failed, falling back to OpenAI: {primary_err}"},
                )
                try:
                    async for sse in _run_with_llm(
                        _build_openai_llm(settings),
                        tools,
                        query_id,
                        question,
                        settings.copilot_recursion_limit,
                        correlation_id,
                    ):
                        yield sse
                except Exception as fallback_err:  # noqa: BLE001
                    logger.error(
                        "Both providers failed",
                        tool="reviewer_copilot",
                        correlation_id=correlation_id,
                        primary_error=str(primary_err),
                        fallback_error=str(fallback_err),
                    )
                    yield sse_event(
                        "error",
                        {"message": f"Both providers failed: {fallback_err}"},
                    )
    except Exception as setup_err:  # noqa: BLE001 — catch MCP connection / discovery errors
        logger.error(
            "Reviewer copilot setup failed",
            tool="reviewer_copilot",
            correlation_id=correlation_id,
            error=str(setup_err),
        )
        yield sse_event("error", {"message": f"Setup failed: {setup_err}"})

    yield sse_event("done", {})
