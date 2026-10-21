-- Reverse of 2026_10_21_release_queue.sql. Archives by RENAME; never drops (AGENTS.md section 0 rule 6).
-- After this runs, GET /api/v2/coordination/release-train* reports the store UNAVAILABLE / not_migrated (the read path
-- probes to_regclass), never zero. Anything that still reads the archived names is a finding.
-- The append-only triggers stay attached to the archived events table, so the archive is still immutable.
-- Apply (operator only): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_21_release_queue.down.sql

BEGIN;
ALTER TABLE IF EXISTS release_queue RENAME TO release_queue_archived_20261021;
ALTER TABLE IF EXISTS release_queue_events RENAME TO release_queue_events_archived_20261021;
COMMIT;
