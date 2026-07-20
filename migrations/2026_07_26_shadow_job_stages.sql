-- 2026_07_26_shadow_job_stages.sql
-- Stage C: on-demand job runner support on decision_runs.
--
-- SHADOW ONLY. The runner produces a shadow decision packet; it touches no
-- proposal, order, approval, or execution path.
--
-- The spec requires the operator to see a run move QUEUED -> RUNNING -> per-stage
-- -> COMPLETE/FAILED without the HTTP request ever blocking on a model lane. The
-- run row already carries state and provider fields; these columns add the
-- per-stage progress the UI polls, the produced packet link, and the SLA the
-- worker enforces so a hung lane fails explicitly rather than hanging forever.

BEGIN;

ALTER TABLE decision_runs
    ADD COLUMN IF NOT EXISTS symbol       TEXT,
    ADD COLUMN IF NOT EXISTS stages       JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS current_stage TEXT,
    ADD COLUMN IF NOT EXISTS packet_id    BIGINT REFERENCES decision_packets(packet_id),
    ADD COLUMN IF NOT EXISTS sla_seconds  INT,
    ADD COLUMN IF NOT EXISTS sla_deadline TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS worker_pid   INT,
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

-- A queued/running job the operator is polling, found fast by symbol.
CREATE INDEX IF NOT EXISTS idx_decision_runs_symbol_state
    ON decision_runs (upper(symbol), state, requested_at DESC);

-- Live (non-terminal) runs, for the watchdog that fails jobs whose worker died
-- without reaching a terminal state.
CREATE INDEX IF NOT EXISTS idx_decision_runs_live
    ON decision_runs (state) WHERE state IN ('QUEUED', 'RUNNING');

COMMIT;
