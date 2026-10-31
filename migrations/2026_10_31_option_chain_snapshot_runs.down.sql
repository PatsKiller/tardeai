-- Reverse of 2026_10_31_option_chain_snapshot_runs.sql. Archives by RENAME; never drops (AGENTS.md §0 rule 6).
-- After this runs the writer logs "option_chain_snapshot_runs absent" and keeps writing option_chain_snapshots.
-- Apply (operator/coordinator only): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_31_option_chain_snapshot_runs.down.sql

BEGIN;
ALTER TABLE IF EXISTS option_chain_snapshot_runs RENAME TO option_chain_snapshot_runs_archived_20261031;
-- Rename its indexes too, so a later re-apply of the up migration creates fresh ones instead of skipping them.
ALTER INDEX IF EXISTS option_chain_snapshot_runs_pkey RENAME TO option_chain_snapshot_runs_archived_20261031_pkey;
ALTER INDEX IF EXISTS option_chain_snapshot_runs_symbol_time RENAME TO option_chain_snapshot_runs_archived_20261031_symbol_time;
COMMIT;
