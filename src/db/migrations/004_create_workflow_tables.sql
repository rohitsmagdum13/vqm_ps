-- Migration 004: Create workflow schema tables
-- Central state table for query processing + ticket links + routing decisions

CREATE TABLE IF NOT EXISTS workflow.case_execution (
    id                  SERIAL PRIMARY KEY,
    query_id            VARCHAR(20) NOT NULL UNIQUE,
    correlation_id      VARCHAR(36) NOT NULL,
    execution_id        VARCHAR(36) NOT NULL,
    source              VARCHAR(10) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'RECEIVED',
    processing_path     VARCHAR(1),
    vendor_id           VARCHAR(50),
    analysis_result     JSONB,
    routing_decision    JSONB,
    draft_response      JSONB,
    quality_gate_result JSONB,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Index for looking up cases by status (for dashboard queries)
CREATE INDEX IF NOT EXISTS idx_case_status ON workflow.case_execution(status);
-- Index for looking up cases by vendor
CREATE INDEX IF NOT EXISTS idx_case_vendor ON workflow.case_execution(vendor_id);

CREATE TABLE IF NOT EXISTS workflow.ticket_link (
    id                  SERIAL PRIMARY KEY,
    query_id            VARCHAR(20) NOT NULL,
    ticket_id           VARCHAR(20) NOT NULL,
    servicenow_sys_id   VARCHAR(50),
    status              VARCHAR(20) NOT NULL DEFAULT 'New',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow.routing_decision (
    id                  SERIAL PRIMARY KEY,
    query_id            VARCHAR(20) NOT NULL,
    assigned_team       VARCHAR(100) NOT NULL,
    category            VARCHAR(100) NOT NULL,
    priority            VARCHAR(10) NOT NULL,
    sla_hours           INTEGER NOT NULL,
    routing_reason      TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);
