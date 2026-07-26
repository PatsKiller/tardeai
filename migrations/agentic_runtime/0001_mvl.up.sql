BEGIN;

CREATE SCHEMA IF NOT EXISTS agentic_runtime;

CREATE TABLE agentic_runtime.agent_runs (
    run_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    job_type TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('LAB', 'SHADOW')),
    objective TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'CREATED', 'RETRIEVING', 'READY_TO_REASON', 'REASONING',
        'REVIEW_REQUIRED', 'COMPLETED', 'CANCELLED', 'FAILED'
    )),
    input_hash TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    validation_hash TEXT NOT NULL CHECK (validation_hash ~ '^[0-9a-f]{64}$'),
    retrieval_count INTEGER NOT NULL DEFAULT 0 CHECK (retrieval_count >= 0),
    model_calls INTEGER NOT NULL DEFAULT 0 CHECK (model_calls >= 0),
    tool_calls INTEGER NOT NULL DEFAULT 0 CHECK (tool_calls >= 0),
    cost_usd NUMERIC(16, 8) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    checkpoint_seq INTEGER NOT NULL DEFAULT 0 CHECK (checkpoint_seq >= 0),
    checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
    budget JSONB NOT NULL DEFAULT '{}'::jsonb,
    cancellation_reason TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE agentic_runtime.agent_artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agentic_runtime.agent_runs(run_id),
    producer_agent_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    input_hash TEXT NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    validation_hash TEXT NOT NULL CHECK (validation_hash ~ '^[0-9a-f]{64}$'),
    retrieval_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_version TEXT NOT NULL,
    provider_family TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, payload_hash)
);

CREATE TABLE agentic_runtime.agent_tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agentic_runtime.agent_runs(run_id),
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('ALLOW', 'DENY')),
    decision_reason TEXT NOT NULL,
    arguments_hash TEXT NOT NULL CHECK (arguments_hash ~ '^[0-9a-f]{64}$'),
    result_hash TEXT CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE agentic_runtime.agent_reviews (
    review_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES agentic_runtime.agent_artifacts(artifact_id),
    producer_agent_id TEXT NOT NULL,
    reviewer_agent_id TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('PASS', 'CAUTION', 'REJECT', 'QUARANTINE', 'INSUFFICIENT_EVIDENCE')),
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifact_hash TEXT NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (producer_agent_id <> reviewer_agent_id)
);

CREATE TABLE agentic_runtime.agent_scores (
    score_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES agentic_runtime.agent_artifacts(artifact_id),
    producer_agent_id TEXT NOT NULL,
    scorer_agent_id TEXT NOT NULL,
    dimensions JSONB NOT NULL,
    outcome_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (producer_agent_id <> scorer_agent_id)
);

CREATE TABLE agentic_runtime.kb_lessons (
    lesson_id TEXT NOT NULL,
    lesson_version INTEGER NOT NULL CHECK (lesson_version > 0),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('CANDIDATE', 'RATIFIED', 'DISPUTED', 'RETIRED')),
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    provenance JSONB NOT NULL,
    counterevidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    created_by TEXT NOT NULL,
    reviewed_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (lesson_id, lesson_version),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE agentic_runtime.kb_cases (
    case_id TEXT PRIMARY KEY,
    case_type TEXT NOT NULL,
    source_refs JSONB NOT NULL,
    facts JSONB NOT NULL,
    decision_artifact_id TEXT REFERENCES agentic_runtime.agent_artifacts(artifact_id),
    outcome JSONB,
    outcome_observed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE agentic_runtime.kb_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding_provider TEXT,
    embedding_model TEXT,
    embedding_version TEXT,
    embedding_vector_ref TEXT,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (embedding_provider IS NULL AND embedding_model IS NULL AND embedding_version IS NULL)
        OR (embedding_provider IS NOT NULL AND embedding_model IS NOT NULL AND embedding_version IS NOT NULL)
    ),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX agent_runs_agent_status_idx ON agentic_runtime.agent_runs(agent_id, status, updated_at DESC);
CREATE INDEX agent_artifacts_run_idx ON agentic_runtime.agent_artifacts(run_id, created_at DESC);
CREATE INDEX agent_tool_calls_run_idx ON agentic_runtime.agent_tool_calls(run_id, started_at DESC);
CREATE INDEX agent_reviews_artifact_idx ON agentic_runtime.agent_reviews(artifact_id, created_at DESC);
CREATE INDEX agent_scores_artifact_idx ON agentic_runtime.agent_scores(artifact_id, created_at DESC);
CREATE INDEX kb_lessons_lifecycle_idx ON agentic_runtime.kb_lessons(lifecycle, valid_from DESC);
CREATE INDEX kb_cases_type_idx ON agentic_runtime.kb_cases(case_type, created_at DESC);
CREATE INDEX kb_chunks_source_idx ON agentic_runtime.kb_chunks(source_type, source_ref, valid_from DESC);

CREATE OR REPLACE FUNCTION agentic_runtime.reject_append_only_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'agentic runtime evidence is append-only: %.%', TG_TABLE_SCHEMA, TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'agent_artifacts', 'agent_tool_calls', 'agent_reviews', 'agent_scores',
        'kb_lessons', 'kb_cases', 'kb_chunks'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_append_only BEFORE UPDATE OR DELETE ON agentic_runtime.%I FOR EACH ROW EXECUTE FUNCTION agentic_runtime.reject_append_only_mutation()',
            table_name,
            table_name
        );
    END LOOP;
END;
$$;

COMMENT ON SCHEMA agentic_runtime IS 'LAB/SHADOW reflective-agent MVL control and evidence schema. No broker, order, approval, 2FA, secret, or config-promotion authority.';
COMMENT ON TABLE agentic_runtime.agent_runs IS 'Mutable run-control row; environment is restricted to LAB or SHADOW.';
COMMENT ON TABLE agentic_runtime.agent_artifacts IS 'Immutable, provenance-bound reflective artifacts.';
COMMENT ON TABLE agentic_runtime.agent_reviews IS 'Independent reviews; producer cannot review its own artifact.';
COMMENT ON TABLE agentic_runtime.agent_scores IS 'Independent Darwin-style scores; producer cannot score its own artifact.';

COMMIT;
