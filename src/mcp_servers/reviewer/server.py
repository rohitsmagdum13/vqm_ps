"""Module: mcp_servers/reviewer/server.py

Path C Reviewer Copilot MCP server entry point.

Runs as a separate process via:
    uv run python -m mcp_servers.reviewer.server

On startup it:
1. Loads VQMS settings.
2. Initialises the connectors the tools need (Postgres via SSH tunnel,
   Salesforce, ServiceNow, LLM gateway for embeddings).
3. Builds a FastMCP instance and registers the 6 tools (closures over
   the connectors live inside register_tools).
4. Runs the MCP server with the streamable-http transport so any MCP
   client (LangGraph agent in FastAPI, Claude Desktop) can connect.
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from mcp.server.fastmcp import FastMCP

from adapters.llm_gateway import LLMGateway
from adapters.salesforce import SalesforceConnector
from adapters.servicenow import ServiceNowConnector
from config.settings import get_settings
from db.connection import PostgresConnector
from mcp_servers.reviewer.tools import register_tools
from utils.logger import LoggingSetup

logger = structlog.get_logger(__name__)


async def _bootstrap() -> tuple[FastMCP, PostgresConnector, ServiceNowConnector]:
    """Initialise connectors and build the FastMCP instance.

    Returns the FastMCP instance plus the connectors that need explicit
    teardown (Postgres pool, ServiceNow httpx client). Other connectors
    (Salesforce client, LLM gateway) are stateless enough to skip.
    """
    settings = get_settings()
    LoggingSetup.configure()

    # Postgres needs to connect explicitly (opens SSH tunnel + pool).
    postgres = PostgresConnector(settings)
    await postgres.connect()
    logger.info("MCP server: Postgres connected", tool="reviewer_mcp")

    salesforce = SalesforceConnector(settings)
    servicenow = ServiceNowConnector(settings)
    llm_gateway = LLMGateway(settings)

    mcp = FastMCP(
        "VQMS Reviewer Copilot",
        host=settings.mcp_reviewer_host,
        port=settings.mcp_reviewer_port,
    )

    register_tools(
        mcp,
        postgres=postgres,
        salesforce=salesforce,
        servicenow=servicenow,
        llm_gateway=llm_gateway,
    )

    logger.info(
        "MCP server: ready",
        tool="reviewer_mcp",
        host=settings.mcp_reviewer_host,
        port=settings.mcp_reviewer_port,
        url=f"http://{settings.mcp_reviewer_host}:{settings.mcp_reviewer_port}/mcp",
    )
    return mcp, postgres, servicenow


async def _shutdown(postgres: PostgresConnector, servicenow: ServiceNowConnector) -> None:
    """Close connectors that need explicit cleanup."""
    try:
        await servicenow.close()
        logger.info("MCP server: ServiceNow client closed", tool="reviewer_mcp")
    except Exception as exc:  # noqa: BLE001 — log and continue shutdown
        logger.warning("ServiceNow close failed", tool="reviewer_mcp", error=str(exc))

    try:
        await postgres.disconnect()
        logger.info("MCP server: Postgres disconnected", tool="reviewer_mcp")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Postgres disconnect failed", tool="reviewer_mcp", error=str(exc))


def main() -> int:
    """Synchronous entry point for the launcher script.

    Everything runs inside one asyncio.run(...) call so the asyncpg pool
    created in _bootstrap() lives on the same event loop that uvicorn
    uses to serve MCP requests. asyncpg pools are loop-bound; using a
    pool across two loops (bootstrap loop vs FastMCP's internal one)
    triggers asyncpg's "another operation is in progress" error on
    every SQL call. mcp.run_streamable_http_async() lets us host the
    transport on the existing loop instead of letting FastMCP spin up
    its own.
    """

    async def _serve() -> None:
        mcp, postgres, servicenow = await _bootstrap()
        try:
            # Blocks until SIGINT / SIGTERM. Same event loop as the pool.
            await mcp.run_streamable_http_async()
        finally:
            await _shutdown(postgres, servicenow)

    asyncio.run(_serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
