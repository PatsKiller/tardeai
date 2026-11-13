-- LQ-20261107-2148: lane_health_current — per-lane scheduler health for the Home v010 Schedulers row.
-- Spec: HOME-BACKEND-SPEC-20261111 section LQ-2148 (columns as specified, plus failed_count_24h, pending_slots,
-- cause_code, source_of_record and detail, all additive).
-- Writer: n8n lane lane-health-snapshot (scripts/lane_health_snapshot.py --apply), UPSERT on lane_id, one
-- transaction per run. The writer never runs DDL: this file is applied by the operator, off-hours, AS THE
-- OWNER ROLE (the agent login is pg_read_all_data only, and a table created as postgres is unwritable by the lane):
--   sudo -u postgres psql -d trade_ai -X -v ON_ERROR_STOP=1 -c "SET ROLE trade_ai" -f migrations/2026_11_12_lane_health_current.sql
-- Verify: SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'public.lane_health_current'::regclass;  -> trade_ai
-- Dry-run evidence (scratch PostgreSQL 17 on a private socket, 2026-11-13): applied twice (second run only NOTICEs),
-- 26 columns, lane_health.write() upserted 409 rows twice, the Home provider read them as a real WARN, down applied.
-- BEFORE: SELECT to_regclass('lane_health_current');  -> NULL (measured read-only 2026-11-11 23:04 ET; the spec
-- also records "lane_health_current does not exist").
-- AFTER:  \d lane_health_current
-- Readers select only the newest run (scripts/lib/lane_health.READ_CURRENT_SQL); a lane that leaves ACTIVE keeps
-- its last row and drops out of the read. Nothing deletes rows (AGENTS.md rule 6).
-- Idempotent: safe to re-run.
BEGIN;
CREATE TABLE IF NOT EXISTS lane_health_current (
    lane_id            TEXT PRIMARY KEY,
    scheduler_kind     TEXT NOT NULL,
    stage              TEXT,
    owner              TEXT,
    value_class        TEXT,
    schedule_expr      TEXT,
    expected_cadence_h NUMERIC,
    expected_slots_24h INTEGER,
    done_slots_24h     INTEGER,
    late_count_24h     INTEGER,
    missed_count_24h   INTEGER,
    failed_count_24h   INTEGER,
    pending_slots      INTEGER,
    last_expected_at   TIMESTAMPTZ,
    last_run_done_at   TIMESTAMPTZ,
    last_ok_receipt_at TIMESTAMPTZ,
    output_signal_kind TEXT,
    output_signal_at   TIMESTAMPTZ,
    output_age_s       INTEGER,
    state              TEXT NOT NULL CHECK (state IN ('OK','LATE','STALE','FAILING','UNKNOWN','NOT_MEASURED')),
    cause_code         TEXT,
    cause              TEXT,
    source_of_record   TEXT,
    detail             JSONB,
    measured_at        TIMESTAMPTZ NOT NULL,
    run_id             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lane_health_current_measured_idx ON lane_health_current (measured_at DESC);
CREATE INDEX IF NOT EXISTS lane_health_current_run_idx ON lane_health_current (run_id);
COMMIT;
