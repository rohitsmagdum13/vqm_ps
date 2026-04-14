-- Migration 007: Create reporting schema tables
-- SLA metrics for dashboard and compliance reporting

CREATE TABLE IF NOT EXISTS reporting.sla_metrics (
    id                      SERIAL PRIMARY KEY,
    query_id                VARCHAR(20) NOT NULL,
    vendor_id               VARCHAR(50),
    processing_path         VARCHAR(1),
    sla_target_hours        INTEGER NOT NULL,
    sla_deadline            TIMESTAMP NOT NULL,
    warning_fired           BOOLEAN NOT NULL DEFAULT FALSE,
    l1_escalation_fired     BOOLEAN NOT NULL DEFAULT FALSE,
    l2_escalation_fired     BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at             TIMESTAMP,
    total_duration_hours    NUMERIC(8, 2),
    created_at              TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Index for SLA dashboard queries
CREATE INDEX IF NOT EXISTS idx_sla_query ON reporting.sla_metrics(query_id);
CREATE INDEX IF NOT EXISTS idx_sla_vendor ON reporting.sla_metrics(vendor_id);
