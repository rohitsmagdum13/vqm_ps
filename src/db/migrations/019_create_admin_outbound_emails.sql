-- Migration 019: Admin outbound emails (free-form admin send/reply)
--
-- Tracks every email an admin sends manually via /admin/email/send or
-- /admin/email/queries/{query_id}/reply. Separate from the AI draft path
-- (workflow.case_execution.draft_response) because admin-composed emails
-- are not tied to a query state machine and should not pollute that table.
--
-- Threading is preserved by storing the Graph reply_to_message_id when
-- the send goes through /messages/{id}/reply.

CREATE TABLE IF NOT EXISTS intake.admin_outbound_emails (
    outbound_id          VARCHAR(20)  PRIMARY KEY,             -- AOE-YYYY-NNNN
    request_id           VARCHAR(64)  NULL,                    -- X-Request-Id (idempotency)
    correlation_id       VARCHAR(36)  NOT NULL,
    query_id             VARCHAR(20)  NULL,                    -- nullable for ad-hoc sends
    actor                VARCHAR(255) NOT NULL,
    to_recipients        JSONB        NOT NULL,                -- list[str]
    cc_recipients        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    bcc_recipients       JSONB        NOT NULL DEFAULT '[]'::jsonb,
    subject              VARCHAR(500) NOT NULL,
    body_html            TEXT         NOT NULL,
    thread_mode          VARCHAR(10)  NOT NULL CHECK (thread_mode IN ('fresh','reply')),
    reply_to_message_id  TEXT         NULL,
    graph_message_id     TEXT         NULL,                    -- returned by Graph on send
    payload_hash         CHAR(64)     NULL,                    -- SHA-256 of canonical payload (idempotency-mismatch detection)
    status               VARCHAR(20)  NOT NULL DEFAULT 'QUEUED'
                         CHECK (status IN ('QUEUED','SENT','FAILED')),
    last_error           TEXT         NULL,
    sent_at              TIMESTAMP    NULL,
    failed_at            TIMESTAMP    NULL,
    created_at           TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- Idempotency: same (actor, request_id) must dedupe.
CREATE UNIQUE INDEX IF NOT EXISTS uq_aoe_actor_request_id
    ON intake.admin_outbound_emails (actor, request_id)
    WHERE request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aoe_query_id        ON intake.admin_outbound_emails(query_id);
CREATE INDEX IF NOT EXISTS idx_aoe_correlation_id  ON intake.admin_outbound_emails(correlation_id);
CREATE INDEX IF NOT EXISTS idx_aoe_sent_at         ON intake.admin_outbound_emails(sent_at DESC);


CREATE TABLE IF NOT EXISTS intake.admin_outbound_attachments (
    attachment_id        VARCHAR(40)  PRIMARY KEY,             -- ATT-<uuid8>
    outbound_id          VARCHAR(20)  NOT NULL
        REFERENCES intake.admin_outbound_emails(outbound_id) ON DELETE CASCADE,
    filename             VARCHAR(255) NOT NULL,
    content_type         VARCHAR(127) NOT NULL,
    size_bytes           BIGINT       NOT NULL,
    s3_key               TEXT         NOT NULL,
    upload_status        VARCHAR(20)  NOT NULL DEFAULT 'STAGED'
                         CHECK (upload_status IN ('STAGED','SENT','FAILED')),
    created_at           TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aoa_outbound_id ON intake.admin_outbound_attachments(outbound_id);
