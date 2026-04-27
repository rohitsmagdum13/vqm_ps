-- Migration 018: Portal query attachments + extracted entities
-- Mirrors intake.email_attachments for the portal path, and adds an
-- extracted_entities JSONB column to intake.portal_queries so the
-- entity extraction LLM output is queryable from SQL.

CREATE TABLE IF NOT EXISTS intake.portal_query_attachments (
    id                  SERIAL PRIMARY KEY,
    query_id            VARCHAR(20) NOT NULL,
    attachment_id       VARCHAR(64) NOT NULL,
    filename            VARCHAR(512) NOT NULL,
    content_type        VARCHAR(128) NOT NULL,
    size_bytes          INTEGER NOT NULL,
    s3_key              VARCHAR(512),
    extracted_text      TEXT,
    extraction_status   VARCHAR(20) NOT NULL DEFAULT 'pending',
    extraction_method   VARCHAR(32) NOT NULL DEFAULT 'none',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (query_id, attachment_id)
);

CREATE INDEX IF NOT EXISTS idx_portal_query_attachments_query_id
    ON intake.portal_query_attachments(query_id);

-- Add extracted_entities column to portal_queries.
-- JSONB so we can index specific keys (e.g. invoice_numbers) later
-- without schema migrations every time the entity contract grows.
ALTER TABLE intake.portal_queries
    ADD COLUMN IF NOT EXISTS extracted_entities JSONB NOT NULL DEFAULT '{}'::jsonb;
