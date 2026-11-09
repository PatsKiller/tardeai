-- stop_lifecycle — the stop-monitor snapshot table, full shape (2026-11-09, LQ-20261107-1686).
--
-- scripts/stop_lifecycle_monitor.py::_persist() used to run CREATE TABLE IF NOT EXISTS plus four
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS on EVERY scan — and the scan runs from stop_health_check
-- (*/10 9-16) and from the 45 s-cached /api/v2/stops/lifecycle. Each ALTER took an ACCESS EXCLUSIVE
-- lock on stop_lifecycle to assert a column that was already there; with db_adapter's 3 s lock_timeout
-- that is the shape that produced 124 lock timeouts and 5 deadlocks on 2026-11-09 14:18–15:19 ET.
-- _persist() now asks the catalog first (lib.ddl_guard.relation_exists / column_exists) and on an
-- up-to-date table writes only its snapshot: DELETE + INSERTs, no DDL.
--
-- Verified read-only against production on 2026-11-09 21:3xZ: stop_lifecycle has 21 columns, i.e. the
-- base shape below plus all four additive columns. Applying this file there is a no-op.
--
-- Additive and idempotent. No .down.sql: the table is a latest-scan snapshot (rewritten every run) and
-- a down script that dropped it would race a live scan; nothing here needs unwinding.
BEGIN;

CREATE TABLE IF NOT EXISTS stop_lifecycle (
    id SERIAL PRIMARY KEY,
    account TEXT,
    symbol TEXT,
    broker TEXT,
    order_id TEXT,
    order_type TEXT,
    status TEXT,
    stop_price NUMERIC,
    qty NUMERIC,
    held_qty NUMERIC,
    current_price NUMERIC,
    proximity_pct NUMERIC,
    coverage TEXT,
    lifecycle TEXT,
    health TEXT,
    flags JSONB,
    snapshot_at TIMESTAMPTZ DEFAULT NOW()
);

-- A trailing order has no fixed trigger price: its trail offset IS the protection (codex review of
-- PR 2180). Price provenance (LQ-20261107-03) lets a stored-only page show that a current_price is a
-- stale mark; as_of is TEXT because the Finviz cache stamps "YYYY-MM-DD HH:MM:SS ET".
ALTER TABLE stop_lifecycle
    ADD COLUMN IF NOT EXISTS trail_offset NUMERIC,
    ADD COLUMN IF NOT EXISTS price_source TEXT,
    ADD COLUMN IF NOT EXISTS price_as_of TEXT,
    ADD COLUMN IF NOT EXISTS price_stale BOOLEAN;

COMMIT;
