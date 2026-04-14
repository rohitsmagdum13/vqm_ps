-- Migration 006: Create memory schema tables
-- Episodic memory, vendor profile cache, and KB article embeddings (pgvector)

CREATE TABLE IF NOT EXISTS memory.episodic_memory (
    id              SERIAL PRIMARY KEY,
    memory_id       VARCHAR(50) NOT NULL UNIQUE,
    vendor_id       VARCHAR(50) NOT NULL,
    query_id        VARCHAR(20) NOT NULL,
    intent          VARCHAR(100) NOT NULL,
    resolution_path VARCHAR(1) NOT NULL,
    outcome         VARCHAR(50) NOT NULL,
    resolved_at     TIMESTAMP NOT NULL,
    summary         TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Index for loading last N interactions for a vendor
CREATE INDEX IF NOT EXISTS idx_episodic_vendor ON memory.episodic_memory(vendor_id, resolved_at DESC);

CREATE TABLE IF NOT EXISTS memory.vendor_profile_cache (
    id              SERIAL PRIMARY KEY,
    vendor_id       VARCHAR(50) NOT NULL UNIQUE,
    profile_data    JSONB NOT NULL,
    cached_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory.embedding_index (
    id              SERIAL PRIMARY KEY,
    article_id      VARCHAR(50) NOT NULL,
    chunk_id        VARCHAR(50),
    title           TEXT NOT NULL,
    content_text    TEXT NOT NULL,
    category        VARCHAR(100) NOT NULL,
    source_url      VARCHAR(512),
    -- Titan Embed v2 outputs 1024 dims (v1 was 1536, but v1 is deprecated)
    embedding       vector(1024) NOT NULL,
    metadata        JSONB,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- HNSW index for fast cosine similarity search on KB embeddings
-- m=16, ef_construction=64 are good defaults for ~10K articles
CREATE INDEX IF NOT EXISTS idx_embedding_hnsw
    ON memory.embedding_index
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index for filtering by category before vector search
CREATE INDEX IF NOT EXISTS idx_embedding_category ON memory.embedding_index(category);
