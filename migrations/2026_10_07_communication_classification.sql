-- Communications hub: decision-support fields on every CommunicationEvent (2026-10-07).
--
-- Operator 2026-10-07: Communications is a decision-support system. Every item has a category, a priority, five
-- scores (priority, confidence, risk, reward, time sensitivity), a TTL + expiry (expires_at already exists, with
-- legal_hold), a status, an actionability flag and — for re-entry items — a re-entry status. Admins can keep an
-- item past its TTL (legal_hold or retain_until). Newer data on the same symbol + category supersedes older items.
-- Written by scripts/lib/comms/client.py (at publish, via scripts/lib/comms/classify.py) and
-- scripts/comms_lifecycle.py (backfill, expiry, archive-then-delete). Read by scripts/communications_portal.py.
--
-- Additive and idempotent: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS; constraints NOT VALID.
-- The writer classifies behind a SAVEPOINT, so code deployed before this migration changes nothing.

ALTER TABLE communication_events
    ADD COLUMN IF NOT EXISTS category          TEXT,
    ADD COLUMN IF NOT EXISTS priority          TEXT,
    ADD COLUMN IF NOT EXISTS priority_score    NUMERIC,
    ADD COLUMN IF NOT EXISTS confidence        NUMERIC,
    ADD COLUMN IF NOT EXISTS risk_score        NUMERIC,
    ADD COLUMN IF NOT EXISTS reward_score      NUMERIC,
    ADD COLUMN IF NOT EXISTS time_sensitivity  NUMERIC,
    ADD COLUMN IF NOT EXISTS reentry_status    TEXT,
    ADD COLUMN IF NOT EXISTS actionable        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS actionable_since  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS action_hint       TEXT,
    ADD COLUMN IF NOT EXISTS symbols           TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS classified_by     TEXT,
    ADD COLUMN IF NOT EXISTS topic_key         TEXT,
    ADD COLUMN IF NOT EXISTS status            TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS superseded_by     TEXT,
    ADD COLUMN IF NOT EXISTS acknowledged_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS acknowledged_by   TEXT,
    ADD COLUMN IF NOT EXISTS retain_until      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retained_by       TEXT;

ALTER TABLE communication_events DROP CONSTRAINT IF EXISTS communication_events_priority_ck;
ALTER TABLE communication_events ADD CONSTRAINT communication_events_priority_ck
    CHECK (priority IS NULL OR priority IN ('critical', 'high', 'medium', 'low')) NOT VALID;

ALTER TABLE communication_events DROP CONSTRAINT IF EXISTS communication_events_status_ck;
ALTER TABLE communication_events ADD CONSTRAINT communication_events_status_ck
    CHECK (status IN ('active', 'acknowledged', 'superseded', 'expired')) NOT VALID;

ALTER TABLE communication_events DROP CONSTRAINT IF EXISTS communication_events_reentry_ck;
ALTER TABLE communication_events ADD CONSTRAINT communication_events_reentry_ck
    CHECK (reentry_status IS NULL OR reentry_status IN
           ('opportunity', 'potential', 'confirmed', 'expired', 'invalidated')) NOT VALID;

CREATE INDEX IF NOT EXISTS communication_events_hub_idx
    ON communication_events (status, category, priority_score DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS communication_events_symbols_idx
    ON communication_events USING GIN (symbols);
CREATE INDEX IF NOT EXISTS communication_events_topic_idx
    ON communication_events (category, topic_key) WHERE status IN ('active', 'acknowledged');
CREATE INDEX IF NOT EXISTS communication_events_unclassified_idx
    ON communication_events (created_at) WHERE category IS NULL;
