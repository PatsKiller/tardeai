-- option_chain_snapshot_runs: one row per symbol per snapshot RUN (10:00 and 17:35 ET today), append-only.
--
-- Why: option_chain_snapshots keeps one row per (as_of, symbol) and the writer upserts, so the 17:35 ET run
-- overwrites the 10:00 ET row. The Market Risk Engine needs the intraday reading: at 10:00 ET on 2026-10-29
-- QQQ put/call volume was 3.31 (RCA, docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md), and by the evening
-- that row was replaced. Builder H's audit (PR #2341) flagged it.
-- Shape: option_chain_snapshots is unchanged (latest-of-day, every existing reader keeps working). This table is
-- the run history beside it, written by the same writer (scripts/options_chain_snapshot.py) in the same transaction.
-- Idempotent: a second run is a no-op. Reverse: 2026_10_31_option_chain_snapshot_runs.down.sql (rename, never drop).
-- Apply (operator/coordinator, after merge): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_31_option_chain_snapshot_runs.sql

BEGIN;

CREATE TABLE IF NOT EXISTS option_chain_snapshot_runs (
    as_of            date        NOT NULL,
    slot_et          text        NOT NULL,             -- 'HH:MM' America/New_York wall time of the run
    symbol           text        NOT NULL,
    put_oi           bigint,
    call_oi          bigint,
    put_vol          bigint,
    call_vol         bigint,
    pc_oi_ratio      numeric,
    pc_vol_ratio     numeric,
    atm_iv           numeric,
    skew25           numeric,
    underlying_price numeric,
    captured_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, slot_et, symbol)
);

CREATE INDEX IF NOT EXISTS option_chain_snapshot_runs_symbol_time
    ON option_chain_snapshot_runs (symbol, captured_at DESC);

COMMIT;
