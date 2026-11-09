-- market-event-lifecycle — the transition log after ENTERED (LQ-20261107-1656 design, LQ-20261107-1674 build).
--
-- ADDITIVE ONLY. One new table; no existing table is touched. Single writer:
--   market_event_lifecycle -> scripts/lib/market_event_lifecycle.py (the lane scripts/market_event_lifecycle.py)
--
-- Why a table and not just the plan column: the stage machine's CURRENT stage is a small map in
-- market_event_candidates.plan->'lifecycle' (one entry per account LABEL), and that map is overwritten on every
-- stage change. The history has to survive the map, because the alert/digest reads "what transitioned" and the
-- reconcile step re-sends a transition whose alert never landed. Append-only: a row is never updated except to
-- record that its alert was sent, and never deleted.
--
-- The unique index is the alert dedup (design PROCESS 6): one row per (episode, symbol, account label, to_stage),
-- so a stage that is revisited (TRIM_READY -> HELD_T2 -> TRIM_READY) cannot alert a second time, and a replayed
-- run cannot double-insert. The writer uses ON CONFLICT DO NOTHING.
--
-- Privilege shape: the account LABEL is the only account identifier stored. No account number, key or id reaches
-- this table (tests/test_market_event_lifecycle_lane_20261109.py asserts it on the rendered row).
--
-- DO NOT APPLY THIS FILE FROM AN ENGINE LANE: the lead applies it through the release.
BEGIN;

CREATE TABLE IF NOT EXISTS market_event_lifecycle (
    id              bigserial PRIMARY KEY,
    episode_id      text NOT NULL,
    symbol          text NOT NULL,
    account_label   text NOT NULL,
    from_stage      text NOT NULL,
    to_stage        text NOT NULL,
    trigger         text NOT NULL,
    gates           jsonb NOT NULL DEFAULT '{}'::jsonb,
    evidence        jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- set when the transition's alert was handed to the brief; the reconcile step looks for NULLs
    alert_event_id  text,
    alerted_at      timestamptz,
    -- when the transition was observed (the lane's clock, not the row's insert clock)
    at              timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT market_event_lifecycle_stage_ck CHECK (from_stage <> to_stage)
);

-- The alert dedup and the replay guard. scoped to a stage, not to time: the design's alert id is
-- (episode, symbol, label, to_stage).
CREATE UNIQUE INDEX IF NOT EXISTS market_event_lifecycle_once_idx
    ON market_event_lifecycle (episode_id, symbol, account_label, to_stage);

CREATE INDEX IF NOT EXISTS market_event_lifecycle_episode_idx
    ON market_event_lifecycle (episode_id, at DESC);

-- The reconcile step's only query: transitions whose alert has not been recorded as sent.
CREATE INDEX IF NOT EXISTS market_event_lifecycle_unalerted_idx
    ON market_event_lifecycle (id) WHERE alert_event_id IS NULL;

COMMIT;
