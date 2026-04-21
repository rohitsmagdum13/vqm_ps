-- Migration 012: Create SLA checkpoints and closure tracking tables for Phase 6
--
-- Phase 6 introduces three new pieces of persistent state:
--   1. workflow.sla_checkpoints  — live scheduler state for the SLA monitor.
--      The SlaMonitor background task scans this table every minute and
--      fires SLAWarning70 / SLAEscalation85 / SLAEscalation95 events when
--      deadlines cross the configured thresholds. Columns warning_fired /
--      l1_fired / l2_fired are idempotency guards.
--   2. workflow.closure_tracking — tracks post-resolution state per query.
--      When delivery.py sends the resolution email, we insert a row with
--      auto_close_deadline = now + 5 business days. ClosureService closes
--      the case when the vendor confirms OR when AutoCloseScheduler finds
--      the deadline has passed.
--   3. workflow.case_execution.linked_query_id — links a new query to a
--      previously closed one when a reopen lands outside the configured
--      window. The new query gets a fresh query_id but keeps the thread.
--
-- Design notes:
--   - reporting.sla_metrics (migration 007) stays as the analytics
--     projection. workflow.sla_checkpoints is live scheduler state used
--     by the monitor loop — different concerns, different tables.
--   - All timestamps are IST (see src/utils/helpers.py → TimeHelper.ist_now).
--     NOW() is used at the DB layer only as a defensive default; application
--     code sets explicit IST timestamps.

CREATE TABLE IF NOT EXISTS workflow.sla_checkpoints (
    query_id             VARCHAR(20)  PRIMARY KEY,
    correlation_id       VARCHAR(36)  NOT NULL,
    sla_started_at       TIMESTAMP    NOT NULL,
    sla_deadline         TIMESTAMP    NOT NULL,
    sla_target_hours     INTEGER      NOT NULL,
    warning_fired        BOOLEAN      NOT NULL DEFAULT FALSE,
    l1_fired             BOOLEAN      NOT NULL DEFAULT FALSE,
    l2_fired             BOOLEAN      NOT NULL DEFAULT FALSE,
    last_checked_at      TIMESTAMP,
    last_status          VARCHAR(30)  NOT NULL DEFAULT 'ACTIVE',
    created_at           TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- Scheduler scan index: filter by status, order by deadline ASC
CREATE INDEX IF NOT EXISTS idx_sla_active
    ON workflow.sla_checkpoints(last_status, sla_deadline);

CREATE TABLE IF NOT EXISTS workflow.closure_tracking (
    query_id                         VARCHAR(20)  PRIMARY KEY,
    correlation_id                   VARCHAR(36)  NOT NULL,
    resolution_sent_at               TIMESTAMP    NOT NULL,
    auto_close_deadline              TIMESTAMP    NOT NULL,
    closed_at                        TIMESTAMP,
    closed_reason                    VARCHAR(30),
    vendor_confirmation_detected_at  TIMESTAMP,
    created_at                       TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at                       TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- AutoCloseScheduler scan: find rows past their auto-close deadline
CREATE INDEX IF NOT EXISTS idx_closure_pending_close
    ON workflow.closure_tracking(closed_at, auto_close_deadline);

-- ReopenHandler lookup by reason
CREATE INDEX IF NOT EXISTS idx_closure_reason
    ON workflow.closure_tracking(closed_reason, closed_at DESC);

-- Link a new query to a previously closed one when a reopen lands outside
-- the configured window. Nullable: only populated for reopen-outside-window cases.
ALTER TABLE workflow.case_execution
    ADD COLUMN IF NOT EXISTS linked_query_id VARCHAR(20);

CREATE INDEX IF NOT EXISTS idx_case_linked_query
    ON workflow.case_execution(linked_query_id)
    WHERE linked_query_id IS NOT NULL;
