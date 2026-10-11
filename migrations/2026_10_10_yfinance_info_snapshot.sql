-- yfinance_info_snapshot — one raw yfinance `.info` payload per symbol (2026-10-10).
--
-- Operator decision 2026-10-10 ~17:45 ET, CONSOLIDATION_PLAN.md §D.13 ("create store
-- yfinance_info_snapshot: migration + single declared writer + broker projection"); design in
-- API_OVERLAP_CONSOLIDATION.md §3.4 (S3): ten lanes fetch `.info` (~5,770 calls/wk) and four
-- symbol_profiles columns have more than one writer. One snapshot per symbol per freshness window
-- lets the reference owner fetch once and every consumer read without a network call.
--
-- Single writer: scripts/lib/writers/yfinance_info_snapshot_writer.py (registry domain
-- yfinance_info_snapshot). tests/test_broker_domains_q1_20261010.py fails the build if any other
-- file writes this table. Read path: lib.data_broker.yfinance_info (projection yfinance_info).
--
-- No producer is scheduled by this migration: the yfinance-reference-ingest owner lane is §D.12,
-- which was not decided. Until it is, the table is empty and the projection reports no_coverage.
--
-- `status` carries the negative cache: 'no_profile' (yfinance returned no quoteType / an empty
-- info) and 'error' are stored with their fetched_at so a refetch waits its window instead of
-- hammering the same dead symbol.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS only. Nothing is dropped or rewritten. There is
-- deliberately no .down.sql: rollback is to stop writing (nothing reads the table but the
-- projection); dropping a store is an operator decision (AGENTS.md §0 rule 6, §17).

CREATE TABLE IF NOT EXISTS yfinance_info_snapshot (
    symbol        TEXT PRIMARY KEY CHECK (symbol <> '' AND symbol = upper(symbol)),
    fetched_at    TIMESTAMPTZ NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('ok', 'no_profile', 'error')),
    quote_type    TEXT,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_keys  INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    source        TEXT NOT NULL DEFAULT 'yfinance',
    written_by    TEXT NOT NULL DEFAULT 'scripts/lib/writers/yfinance_info_snapshot_writer.py',
    run_id        TEXT,
    written_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS yfinance_info_snapshot_fetched_idx
    ON yfinance_info_snapshot (fetched_at DESC);

COMMENT ON TABLE yfinance_info_snapshot IS
    'Raw yfinance .info per symbol (registry domain yfinance_info_snapshot). Single writer: '
    'scripts/lib/writers/yfinance_info_snapshot_writer.py. Read through lib.data_broker.yfinance_info.';
