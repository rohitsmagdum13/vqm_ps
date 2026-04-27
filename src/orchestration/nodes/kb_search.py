"""Module: orchestration/nodes/kb_search.py

KB Search Node — Step 9B in the VQMS pipeline.

Embeds the query text using Titan Embed v2 and runs a cosine
similarity search against KB article embeddings in PostgreSQL
(pgvector). Results determine Path A vs Path B.

Corresponds to Step 9B in the VQMS Architecture Document.
"""

from __future__ import annotations

import time

import structlog

from config.settings import Settings
from adapters.llm_gateway import LLMGateway
from db.connection import PostgresConnector
from models.memory import KBArticleMatch, KBSearchResult
from models.workflow import PipelineState
from utils.exceptions import BedrockTimeoutError
from utils.helpers import TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)

# Maximum query text length for embedding
MAX_SEARCH_TEXT_LENGTH = 2000


class KBSearchNode:
    """Searches the knowledge base using vector similarity.

    Embeds the query text, runs pgvector cosine similarity
    search, and returns ranked article matches.
    """

    def __init__(
        self,
        bedrock: LLMGateway,
        postgres: PostgresConnector,
        settings: Settings,
    ) -> None:
        """Initialize with connectors and search thresholds.

        Args:
            bedrock: LLM gateway for embedding calls (Bedrock primary, OpenAI fallback).
            postgres: PostgreSQL connector for pgvector search.
            settings: Application settings with KB thresholds.
        """
        self._bedrock = bedrock
        self._postgres = postgres
        self._match_threshold = settings.kb_match_threshold
        self._max_results = settings.kb_max_results
        self._embedding_model_id = settings.bedrock_embedding_model_id

    async def execute(self, state: PipelineState) -> PipelineState:
        """Embed query and search KB articles via pgvector.

        Args:
            state: Current pipeline state with unified_payload.

        Returns:
            Updated state with kb_search_result.
        """
        correlation_id = state.get("correlation_id", "")
        query_id = state.get("query_id", "")
        payload = state.get("unified_payload", {})
        start_time = time.perf_counter()

        logger.info(
            "KB search started",
            step="kb_search",
            correlation_id=correlation_id,
        )

        # Step 9B.1: Build search text from subject + body
        subject = payload.get("subject", "")
        body = payload.get("body", "")
        search_text = f"{subject} {body}".strip()
        if len(search_text) > MAX_SEARCH_TEXT_LENGTH:
            search_text = search_text[:MAX_SEARCH_TEXT_LENGTH]

        # Step 9B.2: Generate query embedding
        embed_start = time.perf_counter()
        try:
            embedding = await self._bedrock.llm_embed(
                text=search_text,
                correlation_id=correlation_id,
            )
        except BedrockTimeoutError:
            logger.error(
                "Embedding failed — returning empty KB result (forces Path B)",
                step="kb_search",
                correlation_id=correlation_id,
            )
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="kb_search",
                status="failed",
                details={"error_type": "embedding_failure", "total_matches": 0},
            )
            return self._empty_result_state(start_time)

        embed_time_ms = int((time.perf_counter() - embed_start) * 1000)

        # Step 9B.3: Vector similarity search via pgvector
        search_start = time.perf_counter()
        try:
            # Convert embedding list to pgvector-compatible string format
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

            rows = await self._postgres.fetch(
                "SELECT article_id, title, content_text AS content_snippet, "
                "category, source_url, "
                "1 - (embedding <=> $1::vector) AS similarity_score "
                "FROM memory.embedding_index "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2",
                embedding_str,
                self._max_results,
            )
        except Exception:
            logger.error(
                "pgvector search failed — returning empty KB result (forces Path B)",
                step="kb_search",
                correlation_id=correlation_id,
            )
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="kb_search",
                status="failed",
                details={"error_type": "pgvector_failure", "total_matches": 0},
            )
            return self._empty_result_state(start_time)

        search_time_ms = int((time.perf_counter() - search_start) * 1000)

        # Step 9B.4: Build KBSearchResult
        matches = []
        for row in rows:
            match = KBArticleMatch(
                article_id=row.get("article_id", ""),
                title=row.get("title", ""),
                content_snippet=row.get("content_snippet", ""),
                similarity_score=float(row.get("similarity_score", 0.0)),
                category=row.get("category", ""),
                source_url=row.get("source_url"),
            )
            matches.append(match)

        # Filter matches above threshold for the primary result
        above_threshold = [m for m in matches if m.similarity_score >= self._match_threshold]
        best_score = matches[0].similarity_score if matches else None
        has_sufficient = bool(above_threshold)

        kb_result = KBSearchResult(
            matches=matches,
            search_duration_ms=embed_time_ms + search_time_ms,
            query_embedding_model=self._embedding_model_id,
            best_match_score=best_score,
            has_sufficient_match=has_sufficient,
        )

        logger.info(
            "KB search complete",
            step="kb_search",
            total_matches=len(matches),
            above_threshold=len(above_threshold),
            best_score=best_score,
            has_sufficient=has_sufficient,
            embed_time_ms=embed_time_ms,
            search_time_ms=search_time_ms,
            correlation_id=correlation_id,
        )

        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="kb_search",
            status="success",
            duration_ms=embed_time_ms + search_time_ms,
            details={
                "total_matches": len(matches),
                "above_threshold": len(above_threshold),
                "best_score": best_score,
                "has_sufficient": has_sufficient,
                "embed_time_ms": embed_time_ms,
                "search_time_ms": search_time_ms,
            },
        )

        return {
            "kb_search_result": kb_result.model_dump(),
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    def _empty_result_state(self, start_time: float) -> dict:
        """Return an empty KB result (forces Path B)."""
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        empty_result = KBSearchResult(
            matches=[],
            search_duration_ms=duration_ms,
            query_embedding_model=self._embedding_model_id,
            best_match_score=None,
            has_sufficient_match=False,
        )
        return {
            "kb_search_result": empty_result.model_dump(),
            "updated_at": TimeHelper.ist_now().isoformat(),
        }
