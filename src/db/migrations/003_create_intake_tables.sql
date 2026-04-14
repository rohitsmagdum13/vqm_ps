-- Migration 003: Create intake schema tables
-- Stores parsed email metadata and attachment information

CREATE TABLE IF NOT EXISTS intake.email_messages (
    id              SERIAL PRIMARY KEY,
    message_id      VARCHAR(512) NOT NULL UNIQUE,
    query_id        VARCHAR(20) NOT NULL UNIQUE,
    correlation_id  VARCHAR(36) NOT NULL,
    sender_email    VARCHAR(320) NOT NULL,
    sender_name     VARCHAR(256),
    subject         TEXT NOT NULL,
    body_text       TEXT NOT NULL,
    body_html       TEXT,
    received_at     TIMESTAMP NOT NULL,
    parsed_at       TIMESTAMP NOT NULL,
    in_reply_to     VARCHAR(512),
    conversation_id VARCHAR(512),
    thread_status   VARCHAR(20) NOT NULL DEFAULT 'NEW',
    vendor_id       VARCHAR(50),
    vendor_match_method VARCHAR(20),
    s3_raw_email_key VARCHAR(512),
    source          VARCHAR(10) NOT NULL DEFAULT 'email',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS intake.email_attachments (
    id                  SERIAL PRIMARY KEY,
    message_id          VARCHAR(512) NOT NULL REFERENCES intake.email_messages(message_id),
    query_id            VARCHAR(20) NOT NULL,
    attachment_id       VARCHAR(512) NOT NULL UNIQUE,
    filename            VARCHAR(512) NOT NULL,
    content_type        VARCHAR(128) NOT NULL,
    size_bytes          INTEGER NOT NULL,
    s3_key              VARCHAR(512),
    extracted_text      TEXT,
    extraction_status   VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Index for looking up attachments by query
CREATE INDEX IF NOT EXISTS idx_attachments_query_id ON intake.email_attachments(query_id);
