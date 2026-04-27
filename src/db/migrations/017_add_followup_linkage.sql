-- Migration 017: Follow-up reply linkage
--
-- Use case: a vendor sends an initial query, then replies in the same email
-- thread with a missing PDF / extra detail. Today the reply spawns a brand
-- new query_id with its own ServiceNow ticket and a duplicate LLM run. This
-- migration adds the columns ClosureService.handle_followup_info needs to
-- merge the reply into the prior case instead of cloning it:
--
--   * workflow.case_execution.parent_query_id
--       Set on the *new* query_id when its email was merged into a prior
--       case. Lets dashboards and audits trace the merge after the fact.
--   * workflow.case_execution.additional_context (JSONB)
--       Set on the *prior* query_id when a follow-up arrives mid-pipeline.
--       The orchestrator's context_loading node reads this and feeds the
--       merged corpus back into the next Query Analysis run.
--
-- Both columns are nullable — existing rows stay valid and the legacy code
-- path (no follow-up handling) still works exactly as before.
--
-- Note: there is no CHECK constraint on case_execution.status today, so
-- the new MERGED_INTO_PARENT status used by the merged child rows does
-- not require a constraint update — only application-level enums need to
-- accept it.

ALTER TABLE workflow.case_execution
    ADD COLUMN IF NOT EXISTS parent_query_id    VARCHAR(20),
    ADD COLUMN IF NOT EXISTS additional_context JSONB;

-- Lookups: "show every child merged into this prior case" — used by audit
-- and the dashboard's drill-down. Partial index keeps it small until the
-- feature sees real traffic.
CREATE INDEX IF NOT EXISTS idx_case_parent_query
    ON workflow.case_execution(parent_query_id)
    WHERE parent_query_id IS NOT NULL;
