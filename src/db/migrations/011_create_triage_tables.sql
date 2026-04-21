-- Migration 011: Create triage tables for Path C (Low-Confidence Human Review)
-- Stores TriagePackages created when query analysis confidence < threshold
-- and ReviewerDecisions submitted by human reviewers.
--
-- Tables live in the workflow schema because triage is a workflow state
-- that pauses the LangGraph pipeline until a human reviewer acts.
--
-- Flow:
--   1. Query Analysis node detects confidence < 0.85 → status = PAUSED, processing_path = C
--   2. TriageNode inserts row into workflow.triage_packages with status PENDING
--   3. Reviewer fetches package via GET /triage/queue
--   4. Reviewer submits corrections via POST /triage/{id}/review
--      - inserts into workflow.reviewer_decisions
--      - updates workflow.triage_packages.status → REVIEWED
--      - updates workflow.case_execution with corrected analysis + re-enqueues to SQS
--   5. Workflow resumes from Routing node (post-analysis) with corrected data

CREATE TABLE IF NOT EXISTS workflow.triage_packages (
    id                       SERIAL PRIMARY KEY,
    query_id                 VARCHAR(20) NOT NULL UNIQUE,
    correlation_id           VARCHAR(36) NOT NULL,
    callback_token           VARCHAR(36) NOT NULL UNIQUE,
    package_data             JSONB NOT NULL,
    status                   VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    original_confidence      NUMERIC(4, 3) NOT NULL,
    suggested_category       VARCHAR(100),
    created_at               TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at              TIMESTAMP,
    reviewed_by              VARCHAR(100)
);

-- Dashboard queue: list pending packages ordered by oldest first
CREATE INDEX IF NOT EXISTS idx_triage_status_created
    ON workflow.triage_packages(status, created_at);

-- Lookup by callback token for resume
CREATE INDEX IF NOT EXISTS idx_triage_callback_token
    ON workflow.triage_packages(callback_token);

CREATE TABLE IF NOT EXISTS workflow.reviewer_decisions (
    id                       SERIAL PRIMARY KEY,
    query_id                 VARCHAR(20) NOT NULL,
    reviewer_id              VARCHAR(100) NOT NULL,
    decision_data            JSONB NOT NULL,
    corrected_intent         VARCHAR(100),
    corrected_vendor_id      VARCHAR(50),
    confidence_override      NUMERIC(4, 3),
    reviewer_notes           TEXT,
    decided_at               TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Lookup reviewer history for a query
CREATE INDEX IF NOT EXISTS idx_reviewer_decisions_query
    ON workflow.reviewer_decisions(query_id);

-- Lookup reviewer activity
CREATE INDEX IF NOT EXISTS idx_reviewer_decisions_reviewer
    ON workflow.reviewer_decisions(reviewer_id, decided_at DESC);
