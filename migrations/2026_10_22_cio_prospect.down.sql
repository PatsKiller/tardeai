-- Reverse of 2026_10_22_cio_prospect.sql. Archives by RENAME; never drops (AGENTS.md section 0 rule 6).
-- After this runs, InstrumentRecordStore's Postgres dual-write reports the store absent (it probes to_regclass) and
-- the data-broker projection `cio_prospect` falls back to the shadow build, labelled source=shadow. The jsonl store
-- (cio_instrument_records.jsonl) stayed the store of record throughout P1, so nothing is lost.
-- The append-only/no-delete triggers stay attached to the archived tables, so the archive is still immutable.
-- Write grants are withdrawn from the archive (trade_ai keeps SELECT, to read it). Each step is guarded: idempotent.
-- Apply (operator only): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_cio_prospect.down.sql

BEGIN;
ALTER TABLE IF EXISTS cio_prospect RENAME TO cio_prospect_archived_20261022;
ALTER TABLE IF EXISTS cio_prospect_events RENAME TO cio_prospect_events_archived_20261022;
DO $$
BEGIN
    IF to_regclass('cio_prospect_archived_20261022') IS NOT NULL THEN
        REVOKE INSERT, UPDATE ON cio_prospect_archived_20261022 FROM trade_ai;
    END IF;
    IF to_regclass('cio_prospect_events_archived_20261022') IS NOT NULL THEN
        REVOKE INSERT ON cio_prospect_events_archived_20261022 FROM trade_ai;
    END IF;
    IF to_regclass('cio_prospect_events_id_seq') IS NOT NULL THEN
        REVOKE USAGE ON SEQUENCE cio_prospect_events_id_seq FROM trade_ai;
    END IF;
END
$$;
COMMIT;
