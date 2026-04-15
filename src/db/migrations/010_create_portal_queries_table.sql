-- Migration 010: Create intake.portal_queries table
-- Stores portal submission details (subject, type, priority, description).
-- Mirrors intake.email_messages for the email path — both live in the
-- intake schema because they hold raw ingestion data, not workflow state.
-- workflow.case_execution tracks processing state; this table tracks
-- what the vendor actually submitted.

CREATE TABLE IF NOT EXISTS intake.portal_queries (
    id                  SERIAL PRIMARY KEY,
    query_id            VARCHAR(20) NOT NULL UNIQUE,
    vendor_id           VARCHAR(50) NOT NULL,
    query_type          VARCHAR(50) NOT NULL,
    subject             VARCHAR(500) NOT NULL,
    description         TEXT NOT NULL,
    priority            VARCHAR(20) NOT NULL DEFAULT 'Medium',
    reference_number    VARCHAR(100),
    sla_deadline        TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Lookup by vendor for dashboard and query list
CREATE INDEX IF NOT EXISTS idx_portal_queries_vendor
    ON intake.portal_queries(vendor_id);

-- Lookup by query_id for detail page (UNIQUE constraint also serves as index)
-- Status filtering uses workflow.case_execution, not this table
