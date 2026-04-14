"""Module: models/memory.py

Pydantic models for episodic memory, vendor context, and knowledge base search results.

Episodic memory stores summaries of past vendor interactions.
The Context Loading Node (Step 7) loads the last 5 interactions
for a vendor to give the AI historical context.

The KB Search Node (Step 9B) embeds the query text and runs
a cosine similarity search against KB article embeddings
in PostgreSQL (pgvector). Results determine Path A vs Path B.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from models.ticket import TicketInfo
from models.vendor import VendorProfile


class EpisodicMemoryEntry(BaseModel):
    """A single past interaction with a vendor.

    Stored in memory.episodic_memory table and loaded
    by the Context Loading Node to give the AI historical
    context about this vendor's query patterns.
    """

    model_config = ConfigDict(frozen=True)

    memory_id: str = Field(description="Unique memory entry ID")
    vendor_id: str = Field(description="Vendor this memory belongs to")
    query_id: str = Field(description="Query ID from the original interaction")
    intent: str = Field(description="Classified intent of the original query")
    resolution_path: Literal["A", "B", "C"] = Field(description="Which processing path was used")
    outcome: str = Field(description="How the query was resolved (e.g., resolved, escalated, closed)")
    resolved_at: datetime = Field(description="When the query was resolved (IST)")
    summary: str = Field(description="Brief summary of the interaction for AI context")


class VendorContext(BaseModel):
    """Full context for a vendor loaded at pipeline start (Step 7).

    Combines the vendor profile, recent interaction history,
    and any open tickets to give the AI complete context.
    """

    model_config = ConfigDict(frozen=True)

    vendor_id: str = Field(description="Vendor ID")
    vendor_profile: VendorProfile = Field(description="Full vendor profile from Salesforce")
    recent_interactions: list[EpisodicMemoryEntry] = Field(
        default_factory=list,
        description="Last 5 vendor interactions for historical context",
    )
    open_tickets: list[TicketInfo] = Field(
        default_factory=list,
        description="Currently open tickets for this vendor",
    )


class KBArticleMatch(BaseModel):
    """A single KB article matched by vector similarity.

    Similarity scores above 0.80 indicate a strong match.
    The content_snippet is included for the Resolution Agent
    to use when drafting the response.
    """

    model_config = ConfigDict(frozen=True)

    article_id: str = Field(description="Unique KB article ID")
    title: str = Field(description="Article title")
    content_snippet: str = Field(description="Relevant text excerpt from the article")
    similarity_score: float = Field(ge=0.0, le=1.0, description="Cosine similarity score (0.0-1.0)")
    category: str = Field(description="Article category for filtered search")
    source_url: str | None = Field(default=None, description="URL to the full article")


class KBSearchResult(BaseModel):
    """Aggregated result from KB vector search.

    has_sufficient_match determines the processing path:
    - True: KB has relevant articles -> Path A (AI resolves)
    - False: KB lacks relevant articles -> Path B (human team investigates)
    """

    model_config = ConfigDict(frozen=True)

    matches: list[KBArticleMatch] = Field(default_factory=list, description="Ranked KB article matches")
    search_duration_ms: int = Field(description="Time taken for the vector search in milliseconds")
    query_embedding_model: str = Field(description="Model used for query embedding")
    best_match_score: float | None = Field(default=None, description="Highest similarity score among matches")
    has_sufficient_match: bool = Field(
        description="True if best match >= KB_MATCH_THRESHOLD (0.80) with specific facts",
    )
