-- Migration 015: Index email_messages.conversation_id
--
-- Thread correlation and Phase 6 closure detection both look up the
-- most recent case_execution row whose underlying email shares a
-- conversation_id. That JOIN filters on intake.email_messages
-- conversation_id; without this index every correlation check does a
-- seq scan of the email table.

CREATE INDEX IF NOT EXISTS idx_email_messages_conversation_id
    ON intake.email_messages (conversation_id)
 WHERE conversation_id IS NOT NULL;
