"""Module: mcp_servers/reviewer/tools.py

Six tools exposed by the Path C Reviewer Copilot MCP server.

Each tool wraps an existing VQMS adapter or runs a SQL query against
the workflow / memory / intake schemas. No mock data — every call
returns real production state.

Tools are registered onto a FastMCP instance via register_tools().
Connectors are captured in closures so each tool keeps a reference to
the shared instances initialised by server.py.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from mcp.server.fastmcp import FastMCP

from adapters.llm_gateway import LLMGateway
from adapters.salesforce import SalesforceConnector
from adapters.servicenow import ServiceNowConnector
from db.connection import PostgresConnector

logger = structlog.get_logger(__name__)

# Cap text sent to the embedding model so the embed call stays cheap.
_MAX_QUERY_TEXT_LENGTH = 2000

# Cap KB result size so the agent's context window stays manageable.
_KB_SNIPPET_CHARS = 220


def _safe_json(value: Any) -> str:
    """Serialise tool output to JSON safely.

    The MCP contract is "tools return strings". We always JSON-encode
    so the agent gets structured data it can reason about.
    """
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return json.dumps({"error": "Could not serialise tool output."})


def register_tools(
    mcp: FastMCP,
    *,
    postgres: PostgresConnector,
    salesforce: SalesforceConnector,
    servicenow: ServiceNowConnector,
    llm_gateway: LLMGateway,
) -> None:
    """Register the 6 reviewer copilot tools onto the FastMCP instance.

    Connectors are captured by closure so the tool functions can stay
    plain top-level callables (which FastMCP prefers) without resorting
    to module-level globals.
    """

    # ------------------------------------------------------------------
    # Tool 1 — confidence_breakdown_explainer
    # ------------------------------------------------------------------
    @mcp.tool()
    async def confidence_breakdown_explainer(query_id: str) -> str:
        """Explain why the AI assigned low confidence to a Path C query.

        Always call this FIRST when investigating a triage case. Reads
        the TriagePackage stored in workflow.triage_packages — that's
        the canonical Path C record built by the triage node when the
        analysis confidence fell below the agent threshold.

        Args:
            query_id: VQMS query ID (e.g. 'VQ-2026-0123').

        Returns:
            JSON string with the package's analysis_result, the
            confidence_breakdown dict (overall + per-dimension scores +
            threshold), suggested_routing, suggested_draft, and the
            original query payload (subject + body inside).
            Returns {"error": ...} if no triage package exists for the
            query — that means the query never entered Path C.
        """
        # workflow.triage_packages.package_data is a JSONB column holding
        # the full TriagePackage Pydantic dump. Reading it directly is
        # cheaper than going through the TriageService and gives us the
        # raw shape the agent can reason about.
        row = await postgres.fetchrow(
            """
            SELECT
                tp.query_id,
                tp.correlation_id,
                tp.status AS triage_status,
                tp.original_confidence,
                tp.suggested_category,
                tp.created_at AS triage_created_at,
                tp.reviewed_at,
                tp.reviewed_by,
                tp.package_data,
                ce.vendor_id,
                ce.status AS case_status,
                ce.processing_path
            FROM workflow.triage_packages tp
            LEFT JOIN workflow.case_execution ce ON ce.query_id = tp.query_id
            WHERE tp.query_id = $1
            """,
            query_id,
        )
        if row is None:
            logger.info(
                "confidence_breakdown_explainer: triage package not found",
                tool="reviewer_mcp",
                query_id=query_id,
            )
            return _safe_json(
                {
                    "error": (
                        f"No triage package found for {query_id}. "
                        "This query may not be in Path C, or it predates "
                        "the triage table migration."
                    )
                }
            )

        # package_data may come back as dict (asyncpg + pgvector) or as a
        # JSON string depending on the codec — handle both shapes.
        package_raw = row.get("package_data")
        if isinstance(package_raw, (str, bytes)):
            try:
                package = json.loads(package_raw)
            except json.JSONDecodeError:
                package = {}
        else:
            package = package_raw or {}

        analysis = package.get("analysis_result") or {}
        original_query = package.get("original_query") or {}

        return _safe_json(
            {
                "query_id": row["query_id"],
                "vendor_id": row.get("vendor_id"),
                "case_status": row.get("case_status"),
                "processing_path": row.get("processing_path"),
                "triage_status": row.get("triage_status"),
                "original_confidence": float(row["original_confidence"])
                if row.get("original_confidence") is not None
                else None,
                "suggested_category": row.get("suggested_category"),
                "subject": original_query.get("subject"),
                "body_excerpt": (original_query.get("body") or "")[:300],
                # Pull the per-dimension scores built by the triage node.
                # Keys: overall, intent_classification, entity_extraction,
                # single_issue_detection, threshold.
                "confidence_breakdown": package.get("confidence_breakdown", {}),
                # Surface the AI's analysis so the agent can reason about
                # what was extracted vs missed.
                "intent": analysis.get("intent_classification"),
                "extracted_entities": analysis.get("extracted_entities", {}),
                "urgency_level": analysis.get("urgency_level"),
                "sentiment": analysis.get("sentiment"),
                "multi_issue_detected": analysis.get("multi_issue_detected"),
                "suggested_routing": package.get("suggested_routing"),
                "suggested_draft": package.get("suggested_draft"),
            }
        )

    # ------------------------------------------------------------------
    # Tool 2 — vendor_lookup
    # ------------------------------------------------------------------
    @mcp.tool()
    async def vendor_lookup(vendor_id: str) -> str:
        """Get the full vendor profile from Salesforce.

        Resolves either a Salesforce record ID or the human-readable
        Vendor_ID__c (e.g. 'V-001'). Salesforce calls are cached for
        1 hour via cache.vendor_cache.

        Args:
            vendor_id: Salesforce record ID or Vendor_ID__c.

        Returns:
            JSON string with company name, tier, website, city, etc.
            or {"error": ...} if not found.
        """
        record = await salesforce.find_vendor_by_id(vendor_id=vendor_id)
        if record is None:
            return _safe_json({"error": f"Vendor {vendor_id} not found"})

        return _safe_json(
            {
                "salesforce_id": record.get("Id"),
                "vendor_id": record.get("Vendor_ID__c"),
                "company_name": record.get("Name"),
                "tier": record.get("Vendor_Tier__c"),
                "website": record.get("Website__c"),
                "city": record.get("City__c"),
            }
        )

    # ------------------------------------------------------------------
    # Tool 3 — episodic_memory_for_vendor
    # ------------------------------------------------------------------
    @mcp.tool()
    async def episodic_memory_for_vendor(vendor_id: str, limit: int = 5) -> str:
        """Get this vendor's recent past interactions.

        Use this when you need to spot patterns: do they always ask
        about invoices? Did past queries go Path A or Path B?

        Args:
            vendor_id: The vendor's ID.
            limit: Max past interactions to return (default 5, max 20).

        Returns:
            JSON list newest-first with query_id, intent, path, outcome,
            resolved_at, summary.
        """
        capped_limit = max(1, min(int(limit), 20))
        rows = await postgres.fetch(
            """
            SELECT query_id, intent, resolution_path, outcome, resolved_at, summary
            FROM memory.episodic_memory
            WHERE vendor_id = $1
            ORDER BY resolved_at DESC
            LIMIT $2
            """,
            vendor_id,
            capped_limit,
        )
        return _safe_json(
            {
                "vendor_id": vendor_id,
                "count": len(rows),
                "history": [
                    {
                        "query_id": r["query_id"],
                        "intent": r["intent"],
                        "path": r["resolution_path"],
                        "outcome": r["outcome"],
                        "resolved_at": str(r["resolved_at"]) if r["resolved_at"] else None,
                        "summary": r["summary"],
                    }
                    for r in rows
                ],
            }
        )

    # ------------------------------------------------------------------
    # Tool 4 — get_similar_past_queries
    # ------------------------------------------------------------------
    @mcp.tool()
    async def get_similar_past_queries(query_text: str, top_k: int = 3) -> str:
        """Find resolved past queries similar to the given text.

        Embeds the input via the LLM gateway (Bedrock Titan v2 primary,
        OpenAI fallback) and runs cosine similarity against the
        embedding column on memory.episodic_memory (added in migration
        016). Useful when the new query is ambiguous and you want to
        see how similar past ones were classified — different from
        kb_search, which retrieves KB articles.

        Rows whose embedding hasn't been backfilled yet are skipped via
        WHERE embedding IS NOT NULL, so the tool degrades gracefully
        until every historic row has been embedded.

        Args:
            query_text: The new query's text (subject + body works best).
            top_k: How many similar items to return (default 3, max 10).

        Returns:
            JSON ranked list with query_id, intent, path, outcome,
            summary, resolved_at, similarity.
        """
        capped_top_k = max(1, min(int(top_k), 10))
        text = (query_text or "").strip()
        if not text:
            return _safe_json({"results": [], "reason": "empty query_text"})
        if len(text) > _MAX_QUERY_TEXT_LENGTH:
            text = text[:_MAX_QUERY_TEXT_LENGTH]

        embedding = await llm_gateway.llm_embed(text=text)
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        rows = await postgres.fetch(
            """
            SELECT query_id, vendor_id, intent, resolution_path, outcome,
                   resolved_at, summary,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM memory.episodic_memory
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            embedding_str,
            capped_top_k,
        )
        return _safe_json(
            {
                "results": [
                    {
                        "query_id": r["query_id"],
                        "vendor_id": r.get("vendor_id"),
                        "intent": r["intent"],
                        "path": r["resolution_path"],
                        "outcome": r["outcome"],
                        "resolved_at": str(r["resolved_at"]) if r.get("resolved_at") else None,
                        "summary": r["summary"],
                        "similarity": float(r["similarity"]),
                    }
                    for r in rows
                ]
            }
        )

    # ------------------------------------------------------------------
    # Tool 5 — view_servicenow_history
    # ------------------------------------------------------------------
    @mcp.tool()
    async def view_servicenow_history(vendor_id: str) -> str:
        """List past ServiceNow tickets for a vendor.

        Calls the ServiceNow Table API for incidents tagged with the
        given vendor_id. Useful for spotting open tickets the new
        query might be a follow-up to, and for seeing which team has
        handled this vendor before.

        Args:
            vendor_id: The vendor's ID (matches u_vendor_id in ServiceNow).

        Returns:
            JSON list newest-first with ticket_id, status, priority,
            team, opened_at, short_description.
        """
        # ServiceNowConnector exposes _get_client and _base_url; we call
        # them directly here so we don't need a new mixin method just
        # for this read-only tool.
        try:
            client = servicenow._get_client()  # noqa: SLF001 — inline reuse
            url = f"{servicenow._base_url}/api/now/table/incident"  # noqa: SLF001
            params = {
                "sysparm_query": f"u_vendor_id={vendor_id}^ORDERBYDESCopened_at",
                "sysparm_limit": "10",
                "sysparm_fields": (
                    "number,state,priority,assignment_group,opened_at,"
                    "closed_at,short_description,close_notes"
                ),
            }
            response = await client.get(url, params=params)
            response.raise_for_status()
            results = response.json().get("result", [])
        except Exception as exc:
            logger.warning(
                "view_servicenow_history failed",
                tool="reviewer_mcp",
                vendor_id=vendor_id,
                error=str(exc),
            )
            return _safe_json({"error": f"ServiceNow query failed: {exc}"})

        return _safe_json(
            {
                "vendor_id": vendor_id,
                "count": len(results),
                "tickets": [
                    {
                        "ticket_id": r.get("number"),
                        "state": r.get("state"),
                        "priority": r.get("priority"),
                        "assignment_group": r.get("assignment_group"),
                        "opened_at": r.get("opened_at"),
                        "closed_at": r.get("closed_at"),
                        "short_description": r.get("short_description"),
                        "close_notes": (r.get("close_notes") or "")[:300],
                    }
                    for r in results
                ],
            }
        )

    # ------------------------------------------------------------------
    # Tool 6 — kb_search
    # ------------------------------------------------------------------
    @mcp.tool()
    async def kb_search(query: str, category: str = "", top_k: int = 3) -> str:
        """Search the knowledge base by semantic similarity.

        Embeds the query via the LLM gateway and runs pgvector cosine
        search against memory.embedding_index. Optionally filtered by
        category. Use when you suspect the AI's automatic KB lookup
        missed something or the suggested_category was wrong.

        Args:
            query: Free-text query (subject + topic words work well).
            category: Optional filter ('invoicing', 'procurement',
                'logistics', 'compliance', 'payments', 'contract',
                'general'). Empty string = all categories.
            top_k: Number of top results to return (default 3, max 10).

        Returns:
            JSON ranked list of articles with article_id, title,
            content_snippet, category, similarity.
        """
        capped_top_k = max(1, min(int(top_k), 10))
        text = (query or "").strip()
        if not text:
            return _safe_json({"results": [], "reason": "empty query"})
        if len(text) > _MAX_QUERY_TEXT_LENGTH:
            text = text[:_MAX_QUERY_TEXT_LENGTH]

        embedding = await llm_gateway.llm_embed(text=text)
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        # Filter by category only when one was supplied. Building the
        # SQL by branching keeps the parameter binding straightforward.
        if category:
            rows = await postgres.fetch(
                """
                SELECT article_id, title, content_text, category, source_url,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM memory.embedding_index
                WHERE category = $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                embedding_str,
                category,
                capped_top_k,
            )
        else:
            rows = await postgres.fetch(
                """
                SELECT article_id, title, content_text, category, source_url,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM memory.embedding_index
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                embedding_str,
                capped_top_k,
            )

        return _safe_json(
            {
                "category_filter": category or None,
                "results": [
                    {
                        "article_id": r["article_id"],
                        "title": r["title"],
                        "category": r["category"],
                        "source_url": r.get("source_url"),
                        "content_snippet": (r["content_text"] or "")[:_KB_SNIPPET_CHARS],
                        "similarity": float(r["similarity"]),
                    }
                    for r in rows
                ],
            }
        )

    logger.info(
        "Reviewer MCP tools registered",
        tool="reviewer_mcp",
        tools=[
            "confidence_breakdown_explainer",
            "vendor_lookup",
            "episodic_memory_for_vendor",
            "get_similar_past_queries",
            "view_servicenow_history",
            "kb_search",
        ],
    )
