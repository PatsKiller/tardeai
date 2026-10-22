-- Reverse of 2026_10_21_release_queue.sql. Archives by RENAME; never drops (AGENTS.md section 0 rule 6).
-- After this runs, GET /api/v2/coordination/release-train* reports the store UNAVAILABLE / not_migrated (the read path
-- probes to_regclass), never zero. Anything that still reads the archived names is a finding.
-- The append-only triggers stay attached to the archived events table, so the archive is still immutable.
-- The write grants the up migration gave trade_ai are withdrawn from the archive (it keeps SELECT, to read it);
-- the sequence keeps its name and loses trade_ai's USAGE. Each step is guarded, so a second run is a no-op.
-- Apply (operator only): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_21_release_queue.down.sql

BEGIN;
ALTER TABLE IF EXISTS release_queue RENAME TO release_queue_archived_20261021;
ALTER TABLE IF EXISTS release_queue_events RENAME TO release_queue_events_archived_20261021;
DO $$
BEGIN
    IF to_regclass('release_queue_archived_20261021') IS NOT NULL THEN
        REVOKE INSERT, UPDATE ON release_queue_archived_20261021 FROM trade_ai;
    END IF;
    IF to_regclass('release_queue_events_archived_20261021') IS NOT NULL THEN
        REVOKE INSERT ON release_queue_events_archived_20261021 FROM trade_ai;
    END IF;
    IF to_regclass('release_queue_events_seq_seq') IS NOT NULL THEN
        REVOKE USAGE ON SEQUENCE release_queue_events_seq_seq FROM trade_ai;
    END IF;
END
$$;
COMMIT;
