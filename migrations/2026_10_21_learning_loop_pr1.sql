-- Learning loop PR1 (2026-10-21): stable recommendation ids, trade linkage, R-multiple attribution.
--
-- Operator 2026-10-21, verbatim: "Approve learning-loop plan and begin PR1 immediately. Stable recommendation IDs,
-- trade linkage, and R-multiple attribution provide the highest long-term value and should be implemented before
-- calibration." Design: docs/ops/LEARNING_LOOP_PR1_2026-10-21.md.
--
-- Two NEW tables. Nothing existing is altered, so this migration is additive by construction.
--
--   recommendation_registry     one row per recommendation the operator sees (CIO opportunity plan, paper trade
--                               proposal, scalp GO alert, entry alert), keyed by a deterministic rec_id.
--                               Writer: scripts/lib/recommendation_registry.py (the only module that INSERTs/UPDATEs it;
--                               called by scripts/cio_opportunity_curator.py and scripts/recommendation_registry_sync.py).
--   trade_recommendation_links  one row per closed Schwab round trip: the recommendation it most plausibly came from
--                               (or origin = 'operator_initiated'), the link confidence, and the R attribution.
--                               Writer: scripts/trade_recommendation_linker.py.
--
-- Why not agent_recommendation_registry: it has no entry zone, stop, target, direction or expiry, and
-- scripts/agent_outcome_linker.py joins EVERY row of it to paper_trade_proposals by symbol — registering proposals
-- there would link proposals to themselves and contaminate agent calibration.
-- Why not trade_closed.signal_id / signal_linked_at: signal_id is INTEGER (a rec_id is text), and
-- scripts/schwab_journal_builder.py DELETEs and re-INSERTs every Schwab trade_closed row on each --apply
-- (every 15 min in market hours), so anything written onto trade_closed is wiped within minutes. The link is keyed
-- on schwab_round_trips.dedupe_key, which is the stable natural key of a round trip.
--
-- Column names say plan_stop / plan_target, never stop / target: these are the recommendation's published plan levels
-- kept for attribution, not an order or a stop (MBI_BEHAVIOR = 0; AGENTS.md §0 rule 1).
--
-- Idempotent: CREATE ... IF NOT EXISTS throughout. The writers wrap every write in a SAVEPOINT and skip when the
-- tables are absent, so code deployed before this migration changes nothing.
-- Apply (operator): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_21_learning_loop_pr1.sql
-- Reverse (operator): migrations/2026_10_21_learning_loop_pr1.down.sql (archives by rename; never drops).

BEGIN;

CREATE TABLE IF NOT EXISTS recommendation_registry (
    rec_id               TEXT PRIMARY KEY,
    source               TEXT NOT NULL,
    source_table         TEXT NOT NULL,
    source_id            TEXT NOT NULL,
    symbol               TEXT NOT NULL,
    direction            TEXT NOT NULL,
    entry_low            NUMERIC,
    entry_high           NUMERIC,
    plan_stop            NUMERIC,
    plan_target          NUMERIC,
    created_at           TIMESTAMPTZ NOT NULL,
    expires_at           TIMESTAMPTZ NOT NULL,
    last_seen_at         TIMESTAMPTZ,
    superseded_at        TIMESTAMPTZ,
    conviction_at_issue  NUMERIC,
    conviction_scale     TEXT,
    first_seen_run_id    TEXT,
    stance               TEXT,
    source_status        TEXT,
    payload              JSONB NOT NULL DEFAULT '{}'::jsonb,
    registry_writer      TEXT NOT NULL,
    registered_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT recommendation_registry_source_ck
        CHECK (source IN ('cio_opportunity', 'paper_trade_proposal', 'scalp_alert', 'entry_alert')),
    CONSTRAINT recommendation_registry_direction_ck CHECK (direction IN ('long', 'short')),
    CONSTRAINT recommendation_registry_window_ck CHECK (expires_at >= created_at),
    CONSTRAINT recommendation_registry_source_uq UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_rec_registry_symbol_created ON recommendation_registry (symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_rec_registry_expires ON recommendation_registry (expires_at);

CREATE TABLE IF NOT EXISTS trade_recommendation_links (
    round_trip_key       TEXT PRIMARY KEY,
    round_trip_id        BIGINT,
    trade_source         TEXT NOT NULL DEFAULT 'schwab_round_trips',
    symbol               TEXT NOT NULL,
    account              TEXT,
    direction            TEXT NOT NULL DEFAULT 'long',
    entry_time           TIMESTAMPTZ,
    exit_time            TIMESTAMPTZ,
    entry_price          NUMERIC,
    exit_price           NUMERIC,
    qty                  NUMERIC,
    origin               TEXT NOT NULL,
    rec_id               TEXT,
    rec_source           TEXT,
    link_confidence      TEXT NOT NULL,
    link_method          TEXT NOT NULL,
    link_detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan_entry_low       NUMERIC,
    plan_entry_high      NUMERIC,
    plan_stop            NUMERIC,
    plan_target          NUMERIC,
    stop_source          TEXT NOT NULL,
    r_multiple           NUMERIC,
    r_null_reason        TEXT,
    planned_rr           NUMERIC,
    target_hit           BOOLEAN,
    stop_hit             BOOLEAN,
    hit_basis            TEXT,
    linker_version       TEXT NOT NULL,
    linked_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trade_rec_links_origin_ck CHECK (origin IN ('recommendation', 'operator_initiated')),
    CONSTRAINT trade_rec_links_confidence_ck
        CHECK (link_confidence IN ('exact', 'zone', 'window_only', 'none')),
    CONSTRAINT trade_rec_links_origin_rec_ck CHECK (
        (origin = 'recommendation' AND rec_id IS NOT NULL AND link_confidence <> 'none')
        OR (origin = 'operator_initiated' AND rec_id IS NULL AND link_confidence = 'none')),
    CONSTRAINT trade_rec_links_stop_source_ck CHECK (stop_source IN ('recommendation', 'journal', 'none')),
    CONSTRAINT trade_rec_links_r_reason_ck CHECK (r_multiple IS NOT NULL OR r_null_reason IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_trade_rec_links_rec ON trade_recommendation_links (rec_id) WHERE rec_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trade_rec_links_symbol_exit ON trade_recommendation_links (symbol, exit_time);

COMMIT;
