-- Migration 013: Add recipient and metadata columns to intake.email_messages
--
-- Stores the full set of Graph API message fields that the /emails
-- dashboard API needs to surface: to/cc/bcc/reply-to recipients,
-- importance, has_attachments, web link, and the RFC Message-ID header.
--
-- Recipient columns use JSONB to hold a list of {name, email} objects
-- so the dashboard can render display names, not just email addresses.
--
-- All columns are nullable (or have safe defaults) so existing rows
-- keep working without a backfill.

ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS to_recipients      JSONB,
    ADD COLUMN IF NOT EXISTS cc_recipients      JSONB,
    ADD COLUMN IF NOT EXISTS bcc_recipients     JSONB,
    ADD COLUMN IF NOT EXISTS reply_to           JSONB,
    ADD COLUMN IF NOT EXISTS importance         VARCHAR(16),
    ADD COLUMN IF NOT EXISTS has_attachments    BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS web_link           TEXT,
    ADD COLUMN IF NOT EXISTS internet_message_id VARCHAR(512);
