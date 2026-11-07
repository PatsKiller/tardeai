-- LQ-20261107-197 / DSN-20261107-ANTHROPIC-FIRST-ROUTING §5.2: the monthly Model Scout's system of record.
--
-- One row per real (--write) run of scripts/llm_model_scout.py. The JSON file
-- data/runtime/llm_model_scout/<YYYY-MM>.json is the backup copy of the same report. The scout is read-only and
-- advisory: nothing reads this table to route a call. Additive only; written by the lead, not applied by the worker.
-- No key value is ever stored: the report carries key NAMES only and passes a redactor before it is written.

CREATE TABLE IF NOT EXISTS llm_model_scout_runs (
    id            BIGSERIAL PRIMARY KEY,
    period        TEXT        NOT NULL,              -- YYYY-MM the run reports on
    generated_at  TIMESTAMPTZ NOT NULL,
    p1_count      INTEGER     NOT NULL DEFAULT 0,    -- routed models no longer listed / routed but marked retired
    new_count     INTEGER     NOT NULL DEFAULT 0,    -- listed ids the registry does not know
    discovery     JSONB       NOT NULL,              -- per provider: status, listed count, ids
    report        JSONB       NOT NULL,              -- the full LlmModelScoutRun@v1 report
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE llm_model_scout_runs IS
    'Monthly Model Scout runs (lane llm-model-scout). Advisory: the scout never changes routing. One row per --write run.';

CREATE INDEX IF NOT EXISTS llm_model_scout_runs_period_idx
    ON llm_model_scout_runs (period, generated_at DESC);

-- The lane writes as the application role. Granted only when that role exists, so the file also applies on a
-- scratch database.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trade_ai') THEN
        GRANT SELECT, INSERT ON llm_model_scout_runs TO trade_ai;
        GRANT USAGE ON SEQUENCE llm_model_scout_runs_id_seq TO trade_ai;
    END IF;
END
$$;
