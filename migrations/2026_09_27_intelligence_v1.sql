-- intelligence schema v1 — Global Intelligence Record read model, supervisor tables,
-- retrieval receipts and the approval-package ledger.
-- Package: docs/architecture/cognitive_transformation_20260927/ (02 §5, 03 §4, 06 §3–4, 13 §3).
-- Approval: pkg-20260927-cogx-w1-d9e1 items 6, 7, 8, 9 (operator 2026-09-27); schema + roles are
-- operator-executed (AGENTS.md §17; CREATE ROLE needs the superuser) — see the .down.sql for rollback.
--
-- Additive only. Every table here is a PROJECTION or a RECEIPT: zero authority, canonical stores keep
-- their single writers. Nothing existing is altered. Idempotent (IF NOT EXISTS everywhere) so a re-run
-- is harmless. The vector column is created only where the pgvector extension is installed (prod has
-- vector 0.8.6, measured 2026-09-27); elsewhere the embedding table is created without it and the
-- semantic ladder step returns MISS.
--
-- Roles (operator runs as superuser; the app role cannot CREATE ROLE):
--   CREATE ROLE intelligence_reader NOLOGIN;   -- silos, via the façade
--   CREATE ROLE intelligence_writer NOLOGIN;   -- projector, façade commit, supervisor
--   GRANT intelligence_reader TO <app role>; GRANT intelligence_writer TO <projector role>;
-- Role creation is deliberately NOT in this file so that the file can be applied on a lab database
-- by a non-superuser for proof.

CREATE SCHEMA IF NOT EXISTS intelligence;

-- 02 §5: entities (one row per namespaced GUID)
CREATE TABLE IF NOT EXISTS intelligence.gir_entity (
    guid          text PRIMARY KEY,                 -- namespaced key, e.g. SEC:<uuid>, DEC:<uuid>
    class         text NOT NULL CHECK (class IN ('COMPANY','RESEARCH','DECISION','AGENT','OPERATIONAL','LESSON','RISK','MARKET')),
    kind          text NOT NULL,
    tenant_id     text NOT NULL DEFAULT 'tradeai:tenant:primary',
    source_store  text NOT NULL,                    -- canonical store this row is projected from
    source_ref    text,                             -- record id / event id in that store
    source_sha    text,                             -- release sha of the projector
    first_seen    timestamptz NOT NULL DEFAULT now(),
    projected_at  timestamptz NOT NULL DEFAULT now(),
    projection_version text NOT NULL DEFAULT 'GIR@v1',
    idempotency_key text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS gir_entity_idem_idx ON intelligence.gir_entity (idempotency_key);
CREATE INDEX IF NOT EXISTS gir_entity_class_kind_idx ON intelligence.gir_entity (class, kind);

-- 02 §4: the eight-field envelope
CREATE TABLE IF NOT EXISTS intelligence.gir_envelope (
    guid            text PRIMARY KEY REFERENCES intelligence.gir_entity (guid) ON DELETE CASCADE,
    tenant_id       text NOT NULL DEFAULT 'tradeai:tenant:primary',
    memory          jsonb NOT NULL DEFAULT '{}'::jsonb,
    history         jsonb NOT NULL DEFAULT '{}'::jsonb,
    contradictions  jsonb NOT NULL DEFAULT '{"state":"UNKNOWN"}'::jsonb,
    confidence      jsonb NOT NULL DEFAULT '{"basis":"UNKNOWN"}'::jsonb,
    lineage         jsonb NOT NULL DEFAULT '{}'::jsonb,
    ownership       jsonb NOT NULL DEFAULT '{}'::jsonb,
    freshness       jsonb NOT NULL DEFAULT '{"state":"UNKNOWN"}'::jsonb,
    dependencies    jsonb NOT NULL DEFAULT '{}'::jsonb,
    projected_at    timestamptz NOT NULL DEFAULT now(),
    projection_version text NOT NULL DEFAULT 'GIR@v1',
    idempotency_key text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS gir_envelope_idem_idx ON intelligence.gir_envelope (idempotency_key);
CREATE INDEX IF NOT EXISTS gir_envelope_freshness_idx ON intelligence.gir_envelope ((freshness->>'state'));

-- 07 §2 / 09-27 §7: edges over namespaced GUIDs, bitemporal validity
CREATE TABLE IF NOT EXISTS intelligence.gir_edge (
    edge_id       bigserial PRIMARY KEY,
    tenant_id     text NOT NULL DEFAULT 'tradeai:tenant:primary',
    from_guid     text NOT NULL,
    to_guid       text NOT NULL,
    relation      text NOT NULL,
    valid_period  tstzrange NOT NULL DEFAULT tstzrange(now(), NULL, '[)'),
    source_ref    text,
    source_store  text,
    projected_at  timestamptz NOT NULL DEFAULT now(),
    idempotency_key text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS gir_edge_idem_idx ON intelligence.gir_edge (idempotency_key);
CREATE INDEX IF NOT EXISTS gir_edge_from_rel_idx ON intelligence.gir_edge (from_guid, relation);
CREATE INDEX IF NOT EXISTS gir_edge_to_rel_idx   ON intelligence.gir_edge (to_guid, relation);
CREATE INDEX IF NOT EXISTS gir_edge_valid_gist   ON intelligence.gir_edge USING gist (valid_period);

-- 03 §3 step 1: deterministic research index (subject × question_class × horizon → answer ref)
CREATE TABLE IF NOT EXISTS intelligence.research_index (
    subject_guid    text NOT NULL,
    question_class  text NOT NULL,
    horizon         text NOT NULL DEFAULT 'default',
    tenant_id       text NOT NULL DEFAULT 'tradeai:tenant:primary',
    answer_ref      text NOT NULL,                  -- research_id / thesis version / evidence id
    answer_store    text NOT NULL,
    answered_at     timestamptz NOT NULL,
    next_due        timestamptz,
    version         int NOT NULL DEFAULT 1,
    projected_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_guid, question_class, horizon, version)
);
CREATE INDEX IF NOT EXISTS research_index_latest_idx ON intelligence.research_index (subject_guid, question_class, horizon, answered_at DESC);

-- 03 §3 step 7: embeddings (vector column only where pgvector exists)
CREATE TABLE IF NOT EXISTS intelligence.embedding (
    ref             text PRIMARY KEY,               -- Q:<guid> | EVID:<id> | THESIS:<id>
    tenant_id       text NOT NULL DEFAULT 'tradeai:tenant:primary',
    subject_guid    text,
    model           text NOT NULL,                  -- e.g. nomic-embed-text (local)
    dims            int NOT NULL,
    projected_at    timestamptz NOT NULL DEFAULT now(),
    source_changed_at timestamptz                   -- ladder ignores rows older than the record's last_changed
);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        EXECUTE 'ALTER TABLE intelligence.embedding ADD COLUMN IF NOT EXISTS vec vector(768)';
    END IF;
END$$;

-- 03 §4: retrieval receipts (proof the ladder ran before generation)
CREATE TABLE IF NOT EXISTS intelligence.retrieval_receipt (
    receipt_id      text PRIMARY KEY,
    context_id      text,
    tenant_id       text NOT NULL DEFAULT 'tradeai:tenant:primary',
    lane_id         text NOT NULL,
    subject_guid    text,
    question_class  text,
    horizon         text,
    decision        text NOT NULL CHECK (decision IN ('HIT_FRESH','HIT_STALE','HIT_PARTIAL','MISS')),
    generated       boolean NOT NULL DEFAULT false,
    generation_reason text,
    ladder          jsonb NOT NULL,                 -- [{step, key, store, hit, refs, ms}]
    reused_refs     jsonb NOT NULL DEFAULT '[]'::jsonb,
    release_sha     text,
    mode            text NOT NULL DEFAULT 'SHADOW' CHECK (mode IN ('SHADOW','ENFORCED')),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS retrieval_receipt_lane_day_idx ON intelligence.retrieval_receipt (lane_id, created_at DESC);
CREATE INDEX IF NOT EXISTS retrieval_receipt_subject_idx ON intelligence.retrieval_receipt (subject_guid, question_class, created_at DESC);

-- 01 §3: memory contexts (open/commit) — receipts of read-before-act / write-after-act
CREATE TABLE IF NOT EXISTS intelligence.memory_context (
    context_id      text PRIMARY KEY,
    tenant_id       text NOT NULL DEFAULT 'tradeai:tenant:primary',
    lane_id         text NOT NULL,
    agent_id        text,
    purpose         text NOT NULL CHECK (purpose IN ('RESEARCH','DECIDE','ADVISE','MONITOR','CURATE','ANSWER_OPERATOR')),
    subjects        jsonb NOT NULL DEFAULT '[]'::jsonb,
    opened_at       timestamptz NOT NULL DEFAULT now(),
    as_of           timestamptz,
    degraded        boolean NOT NULL DEFAULT false,
    degraded_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    fact_ids        jsonb NOT NULL DEFAULT '[]'::jsonb,
    committed_at    timestamptz,
    outcome         jsonb,
    influence       jsonb,                          -- {consulted, changed_decision, mode}
    release_sha     text,
    mode            text NOT NULL DEFAULT 'SHADOW' CHECK (mode IN ('SHADOW','ENFORCED'))
);
CREATE INDEX IF NOT EXISTS memory_context_lane_day_idx ON intelligence.memory_context (lane_id, opened_at DESC);

-- 06 §3: heartbeat (one row per lane × boot)
CREATE TABLE IF NOT EXISTS intelligence.heartbeat (
    lane_id         text NOT NULL,
    boot_id         text NOT NULL,
    pid             int,
    release_sha     text,
    cwd             text,
    last_beat       timestamptz NOT NULL DEFAULT now(),
    last_success    timestamptz,
    last_output_signal timestamptz,
    work_claimed    int NOT NULL DEFAULT 0,
    work_done       int NOT NULL DEFAULT 0,
    work_failed     int NOT NULL DEFAULT 0,
    queue_depth     int,
    oldest_queued   timestamptz,
    memory_context_ok boolean,
    degraded_reasons text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (lane_id, boot_id)
);
CREATE INDEX IF NOT EXISTS heartbeat_lane_last_idx ON intelligence.heartbeat (lane_id, last_beat DESC);

-- 06 §4: SLA (one row per lane; seeded from config/lane_registry.json)
CREATE TABLE IF NOT EXISTS intelligence.sla (
    lane_id         text PRIMARY KEY,
    silo_id         text,
    owner           text,
    max_silence_s   int,
    max_run_s       int,
    max_queue_age_s int,
    max_failure_rate numeric,
    expected_output_signal text,
    event_to_effect_p95_s int,
    memory_context_required text CHECK (memory_context_required IN ('fail-closed','degraded','none')),
    ladder_max      int NOT NULL DEFAULT 3 CHECK (ladder_max BETWEEN 1 AND 5),
    alternate       text,
    seeded_from     text,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- 06 §5: breaches
CREATE TABLE IF NOT EXISTS intelligence.breach (
    breach_id       text PRIMARY KEY,
    lane_id         text NOT NULL,
    silo_id         text,
    kind            text NOT NULL CHECK (kind IN ('SILENT','HUNG','BACKLOG','FAILING','NO_OUTPUT','MEMORY_UNREACHABLE','SLO_MISS','UNGOVERNED')),
    detected_at     timestamptz NOT NULL DEFAULT now(),
    evidence        jsonb NOT NULL DEFAULT '{}'::jsonb,
    level           int NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 5),
    state           text NOT NULL DEFAULT 'OPEN' CHECK (state IN ('OPEN','RECOVERING','RECOVERED','ESCALATED','CLOSED')),
    recovery        jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS breach_open_idx ON intelligence.breach (state, lane_id) WHERE state <> 'CLOSED';

-- 13 §3: approval-package ledger projection (the JSONL in persistent-state is canonical)
CREATE TABLE IF NOT EXISTS intelligence.approval_package (
    package_id      text PRIMARY KEY,
    campaign        text NOT NULL,
    wave            text,
    created_at      timestamptz NOT NULL,
    expires_at      timestamptz,
    state           text NOT NULL CHECK (state IN ('DRAFT','SUBMITTED','PARTIAL','APPROVED','EXECUTING','VALIDATED','DENIED','EXPIRED')),
    items           jsonb NOT NULL,
    telegram        jsonb NOT NULL DEFAULT '{}'::jsonb,
    hash_prev       text,
    hash_self       text,
    projected_at    timestamptz NOT NULL DEFAULT now()
);

-- 11 S-3: RLS tenant policy, mirroring memory_r10_m2 (FORCE, app.tenant_id).
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['gir_entity','gir_envelope','gir_edge','research_index','embedding','retrieval_receipt','memory_context']
    LOOP
        EXECUTE format('ALTER TABLE intelligence.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE intelligence.%I FORCE ROW LEVEL SECURITY', t);
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='intelligence' AND tablename=t AND policyname='tenant_isolation') THEN
            EXECUTE format('CREATE POLICY tenant_isolation ON intelligence.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', t);
        END IF;
    END LOOP;
END$$;

-- Grants are applied by the operator once the roles exist (see header). Kept as a comment on purpose:
-- GRANT USAGE ON SCHEMA intelligence TO intelligence_reader, intelligence_writer;
-- GRANT SELECT ON ALL TABLES IN SCHEMA intelligence TO intelligence_reader;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA intelligence TO intelligence_writer;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA intelligence TO intelligence_writer;
