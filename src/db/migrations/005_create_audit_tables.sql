-- Migration 005: Create audit schema tables
-- Every state transition and validation result is recorded for compliance

CREATE TABLE IF NOT EXISTS audit.action_log (
    id              SERIAL PRIMARY KEY,
    correlation_id  VARCHAR(36) NOT NULL,
    query_id        VARCHAR(20),
    step_name       VARCHAR(50) NOT NULL,
    actor           VARCHAR(100) NOT NULL DEFAULT 'system',
    action          VARCHAR(100) NOT NULL,
    status          VARCHAR(20) NOT NULL,
    details         JSONB,
    duration_ms     INTEGER,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Index for tracing a query through the pipeline
CREATE INDEX IF NOT EXISTS idx_action_log_correlation ON audit.action_log(correlation_id);
CREATE INDEX IF NOT EXISTS idx_action_log_query ON audit.action_log(query_id);

CREATE TABLE IF NOT EXISTS audit.validation_results (
    id              SERIAL PRIMARY KEY,
    query_id        VARCHAR(20) NOT NULL,
    correlation_id  VARCHAR(36) NOT NULL,
    gate_name       VARCHAR(50) NOT NULL,
    passed          BOOLEAN NOT NULL,
    checks_run      INTEGER NOT NULL,
    checks_passed   INTEGER NOT NULL,
    failed_checks   JSONB,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
