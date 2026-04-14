-- Migration 008: Create cache schema tables
-- PostgreSQL-based caching (replaces Redis) with TTL-based cleanup

-- Idempotency keys: prevent duplicate processing of the same email/query
-- Uses INSERT ON CONFLICT DO NOTHING for atomic check-and-insert
CREATE TABLE IF NOT EXISTS cache.idempotency_keys (
    id              SERIAL PRIMARY KEY,
    key             VARCHAR(512) NOT NULL,
    source          VARCHAR(10) NOT NULL,
    correlation_id  VARCHAR(36) NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_idempotency_key UNIQUE (key)
);

-- Vendor profile cache: 1-hour TTL, reduces Salesforce API calls
CREATE TABLE IF NOT EXISTS cache.vendor_cache (
    id              SERIAL PRIMARY KEY,
    vendor_id       VARCHAR(50) NOT NULL UNIQUE,
    cache_data      JSONB NOT NULL,
    cached_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL
);

-- Workflow state cache: 24-hour TTL, stores intermediate pipeline state
CREATE TABLE IF NOT EXISTS cache.workflow_state_cache (
    id              SERIAL PRIMARY KEY,
    query_id        VARCHAR(20) NOT NULL UNIQUE,
    state_data      JSONB NOT NULL,
    cached_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL
);

-- Indexes for TTL-based cleanup queries
CREATE INDEX IF NOT EXISTS idx_idempotency_created ON cache.idempotency_keys(created_at);
CREATE INDEX IF NOT EXISTS idx_vendor_cache_expires ON cache.vendor_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_workflow_cache_expires ON cache.workflow_state_cache(expires_at);
