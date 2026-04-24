-- Migration 014: Claim-check idempotency + transactional outbox
--
-- Two correctness fixes applied in the same migration because they
-- work together:
--
-- 1. Idempotency keys become a two-phase "claim → complete" record
--    instead of a fire-and-forget INSERT. A crash between claim and
--    commit used to silently drop emails; now the claim expires and
--    the next poll reclaims the message.
--
-- 2. cache.outbox_events pairs every DB write with a queued event.
--    Write and event go into the same transaction, so a partial
--    failure can never produce orphan rows without a matching SQS
--    message.

-- --- Part 1: Add claim-check columns to idempotency_keys ---

ALTER TABLE cache.idempotency_keys
    ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'COMPLETED';

ALTER TABLE cache.idempotency_keys
    ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMP;

-- Backfill: anything already in the table is a pre-migration success.
-- Marking them COMPLETED means they still act as duplicate guards.
UPDATE cache.idempotency_keys
   SET status = 'COMPLETED'
 WHERE status IS NULL OR status = '';

-- Fast lookup of stale claims during reclaim.
CREATE INDEX IF NOT EXISTS idx_idempotency_claim
    ON cache.idempotency_keys (status, claim_expires_at);


-- --- Part 2: Outbox table for transactional DB→SQS handoff ---

CREATE TABLE IF NOT EXISTS cache.outbox_events (
    id              SERIAL PRIMARY KEY,
    event_key       VARCHAR(64) NOT NULL UNIQUE,
    queue_url       VARCHAR(512) NOT NULL,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    sent_at         TIMESTAMP,
    attempt_count   INT NOT NULL DEFAULT 0,
    last_error      TEXT
);

-- Partial index: only unsent rows need to be scanned by the publisher.
CREATE INDEX IF NOT EXISTS idx_outbox_unsent
    ON cache.outbox_events (created_at)
 WHERE sent_at IS NULL;
