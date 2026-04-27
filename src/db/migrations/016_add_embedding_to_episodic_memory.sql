-- Migration 016: Add embedding column to memory.episodic_memory
-- Required by the Path C reviewer copilot's `get_similar_past_queries` tool
-- (src/mcp_servers/reviewer/tools.py). Without this column the tool has
-- nowhere to run cosine similarity against resolved past queries — the
-- KB-only memory.embedding_index table doesn't carry vendor/intent/path
-- data, so it can't substitute.
--
-- Strategy:
--   - Add `embedding` as a NULLABLE vector(1024) column. Existing rows
--     stay valid; new rows can opt in once the writer is updated.
--   - Add a partial HNSW index that ignores NULL rows so the index size
--     stays small until backfill runs.
--   - 1024 dims matches Bedrock Titan Embed v2 (the production embed
--     model). Same dimensionality as memory.embedding_index for
--     consistency.
--
-- Follow-up (separate task — not part of this migration):
--   - Update src/services/episodic_memory.py → EpisodicMemoryWriter to
--     call llm_gateway.llm_embed(summary) and write the embedding on
--     every closure. The summary is the natural text to embed since it
--     captures intent + outcome in one line.
--   - Backfill existing rows with a one-shot script that loops over
--     resolved cases, embeds the summary, UPDATEs the row.

ALTER TABLE memory.episodic_memory
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- Partial HNSW index — only indexes rows that have a non-NULL embedding.
-- m=16, ef_construction=64 matches the existing memory.embedding_index
-- so cosine search behaves the same way for past queries as it does for
-- KB articles.
CREATE INDEX IF NOT EXISTS idx_episodic_embedding_hnsw
    ON memory.episodic_memory
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE embedding IS NOT NULL;
