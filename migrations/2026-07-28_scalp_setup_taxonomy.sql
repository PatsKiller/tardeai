-- Multi-setup scalp taxonomy — ADDITIVE columns on scalp_ignition_events (arch-owner 2026-07-27).
-- A lane (IGN_60/IGN_ACCEL/TRIGGER) is NOT a setup. These columns record which NAMED, VERSIONED,
-- DETERMINISTIC setup(s) actually matched/fired, alongside the preserved lane. Purely additive: every
-- existing column, index, and consumer is untouched. SHADOW: no order path, no proposal reference.
--
-- setup_state semantics:
--   SCANNING          watching, no pattern yet
--   ARMED             partial match — mandatory criteria not all satisfied (NOT a fire)
--   FIRED             ALL mandatory deterministic criteria true on a closed bar / valid book event,
--                     inside the setup-specific window, with the universal execution gate passing
--   INVALIDATED       an invalidation rule triggered (e.g. L2 book flip, leg void)
--   EXPIRED           setup window closed without a fire
--   DATA_UNAVAILABLE  required tier absent (e.g. L2 setup with no entitled book)
--   OUTSIDE_WINDOW    evaluated outside the setup's session/time window

ALTER TABLE scalp_ignition_events
    ADD COLUMN IF NOT EXISTS primary_setup_id     TEXT,
    ADD COLUMN IF NOT EXISTS primary_setup_label  TEXT,
    ADD COLUMN IF NOT EXISTS matched_setup_ids    JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS matched_setup_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS setup_state          TEXT,
    ADD COLUMN IF NOT EXISTS setup_version        TEXT,
    ADD COLUMN IF NOT EXISTS setup_fired_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS market_session       TEXT,   -- 'PREMARKET' | 'REGULAR'
    ADD COLUMN IF NOT EXISTS confirmation_labels  JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS setup_evidence       JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS setup_fail_reasons   JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS registry_hash        TEXT;

-- query paths for the setup-events API (primary setup by session; fired setups)
CREATE INDEX IF NOT EXISTS idx_sie_primary_setup
    ON scalp_ignition_events (primary_setup_id, session_date);
CREATE INDEX IF NOT EXISTS idx_sie_setup_state
    ON scalp_ignition_events (setup_state, session_date);
CREATE INDEX IF NOT EXISTS idx_sie_market_session
    ON scalp_ignition_events (market_session, session_date);
