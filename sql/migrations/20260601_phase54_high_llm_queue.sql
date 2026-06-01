-- Phase 54 — High-LLM Global Job Queue
BEGIN;

CREATE TABLE IF NOT EXISTS high_llm_job_queue (
    id                    BIGSERIAL PRIMARY KEY,
    job_type              TEXT NOT NULL,
    source_system         TEXT NOT NULL,
    process_type          TEXT,
    requested_model_class TEXT NOT NULL DEFAULT 'high',
    preferred_model       TEXT NOT NULL DEFAULT 'gemma3:12b',
    fallback_model        TEXT DEFAULT 'gemma3:4b',
    urgency               REAL NOT NULL DEFAULT 0.5,
    portfolio_impact      REAL NOT NULL DEFAULT 0.5,
    operator_value        REAL NOT NULL DEFAULT 0.5,
    evidence_gap_score    REAL NOT NULL DEFAULT 0.5,
    staleness_days        INTEGER DEFAULT 0,
    deadline_utc          TIMESTAMPTZ,
    expected_runtime_sec  INTEGER DEFAULT 300,
    context_tokens_est    INTEGER DEFAULT 4000,
    priority_score        REAL,
    quota_pool            TEXT NOT NULL DEFAULT 'flex',
    status                TEXT NOT NULL DEFAULT 'queued',
    advisory_only         BOOLEAN NOT NULL DEFAULT true,
    not_execution         BOOLEAN NOT NULL DEFAULT true,
    duplicate_hash        TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scheduled_for         TIMESTAMPTZ,
    started_at            TIMESTAMPTZ,
    finished_at           TIMESTAMPTZ,
    result_ref            BIGINT,
    error_message         TEXT,
    retry_count           INTEGER DEFAULT 0,
    CONSTRAINT hljq_status_check CHECK (status IN ('queued','scheduled','running','completed','failed','skipped','dry_run_candidate')),
    CONSTRAINT hljq_advisory CHECK (advisory_only = true),
    CONSTRAINT hljq_no_exec CHECK (not_execution = true),
    CONSTRAINT hljq_pool_check CHECK (quota_pool IN ('journal_backtest','portfolio_risk','hermes_research','flex','legacy_overnight'))
);

CREATE INDEX idx_hljq_status ON high_llm_job_queue (status, priority_score DESC);
CREATE INDEX idx_hljq_pool ON high_llm_job_queue (quota_pool, status);
CREATE INDEX idx_hljq_source ON high_llm_job_queue (source_system, created_at);

CREATE TABLE IF NOT EXISTS high_llm_job_results (
    id           BIGSERIAL PRIMARY KEY,
    job_id       BIGINT REFERENCES high_llm_job_queue(id),
    model_used   TEXT NOT NULL,
    runtime_sec  REAL,
    tokens_used  INTEGER,
    result_quality REAL,
    actionable   BOOLEAN DEFAULT false,
    output_summary TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE high_llm_job_queue IS 'Global high-LLM priority queue — Phase 54. Advisory only.';
COMMENT ON TABLE high_llm_job_results IS 'High-LLM job results — Phase 54.';

COMMIT;
