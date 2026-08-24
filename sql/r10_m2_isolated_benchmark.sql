-- R10 M2 ISOLATED benchmark schema. NEVER apply to production.
-- Intended DSN: 127.0.0.1:55432 / m2_shadow (docker tradeai-m2-shadow).
-- Production :5432 is forbidden.

CREATE SCHEMA IF NOT EXISTS memory_r10_m2;

CREATE TABLE IF NOT EXISTS memory_r10_m2.memory_identity (
    identity_id     uuid NOT NULL,
    tenant_id       text NOT NULL,
    namespace       text NOT NULL,
    identity_kind   text NOT NULL,
    subject_guid    text NOT NULL,
    predicate       text NOT NULL,
    canonical_key   text NOT NULL,
    created_at      timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, identity_id),
    UNIQUE (tenant_id, identity_id),
    UNIQUE (tenant_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS memory_r10_m2.memory_fact_version (
    memory_version_id uuid PRIMARY KEY,
    memory_id         uuid NOT NULL,
    tenant_id         text NOT NULL,
    identity_id       uuid NOT NULL,
    subject_guid      text NOT NULL,
    predicate         text NOT NULL,
    object_json       jsonb NOT NULL,
    valid_from        timestamptz NOT NULL,
    valid_to          timestamptz,
    tx_from           timestamptz NOT NULL,
    tx_to             timestamptz,
    status            text NOT NULL,
    confidence        text NOT NULL,
    authority         text NOT NULL DEFAULT 'READ_ONLY_ADVISORY',
    source_type       text NOT NULL,
    source_id         text NOT NULL,
    source_as_of      timestamptz NOT NULL,
    trace_id          text,
    evidence_refs     jsonb NOT NULL DEFAULT '[]'::jsonb,
    contradiction_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    supersedes_id     uuid,
    content_summary   text,
    embedding         vector(768),
    embedding_model   text,
    embedding_dimension int,
    embedding_version text,
    source_sha        text,
    created_at        timestamptz NOT NULL,
    temporal_policy   text NOT NULL DEFAULT 'GAPS_ALLOWED',
    CHECK (valid_to IS NULL OR valid_from < valid_to),
    CHECK (tx_to IS NULL OR tx_from < tx_to),
    CHECK (temporal_policy IN ('CONTINUITY_REQUIRED', 'GAPS_ALLOWED', 'UNKNOWN_EXPLICIT')),
    FOREIGN KEY (tenant_id, identity_id)
        REFERENCES memory_r10_m2.memory_identity (tenant_id, identity_id)
);

CREATE INDEX IF NOT EXISTS fact_identity_idx
    ON memory_r10_m2.memory_fact_version (tenant_id, identity_id, tx_from);

CREATE INDEX IF NOT EXISTS fact_subject_pred_idx
    ON memory_r10_m2.memory_fact_version (tenant_id, subject_guid, predicate);

CREATE INDEX IF NOT EXISTS fact_valid_gist
    ON memory_r10_m2.memory_fact_version
    USING gist (tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz), '[)'));

CREATE INDEX IF NOT EXISTS fact_tx_gist
    ON memory_r10_m2.memory_fact_version
    USING gist (tstzrange(tx_from, COALESCE(tx_to, 'infinity'::timestamptz), '[)'));

CREATE TABLE IF NOT EXISTS memory_r10_m2.adjudication_receipt (
    adjudication_id     uuid PRIMARY KEY,
    tenant_id           text NOT NULL,
    subject_guid        text NOT NULL,
    predicate           text NOT NULL,
    conflict_id         text,
    candidate_fact_ids  jsonb NOT NULL DEFAULT '[]'::jsonb,
    selected_fact_id    uuid,
    rejected_fact_ids   jsonb NOT NULL DEFAULT '[]'::jsonb,
    policy              text NOT NULL,
    policy_version      text NOT NULL,
    provider            text,
    model               text,
    prompt_version      text,
    evidence_refs       jsonb NOT NULL DEFAULT '[]'::jsonb,
    trace_id            text,
    source_sha          text,
    recorded_at         timestamptz NOT NULL,
    chain_of_thought    boolean NOT NULL DEFAULT false,
    CHECK (chain_of_thought = false)
);

CREATE TABLE IF NOT EXISTS memory_r10_m2.relationship_candidate (
    candidate_relationship_id uuid PRIMARY KEY,
    tenant_id           text NOT NULL,
    source_entity_guid  text NOT NULL,
    target_entity_guid  text NOT NULL,
    relationship_hypothesis text NOT NULL,
    similarity          double precision,
    status              text NOT NULL,
    authoritative       boolean NOT NULL DEFAULT false,
    CHECK (status IN ('CANDIDATE','SUPPORTED','RATIFIED','DISPUTED','SUPERSEDED','RETRACTED')),
    CHECK (NOT (status = 'CANDIDATE' AND authoritative)),
    CHECK (NOT (authoritative AND status NOT IN ('RATIFIED')))
);

ALTER TABLE memory_r10_m2.memory_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.memory_fact_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.adjudication_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.relationship_candidate ENABLE ROW LEVEL SECURITY;
-- Table owner would otherwise bypass RLS; FORCE makes isolation measurable.
ALTER TABLE memory_r10_m2.memory_identity FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.memory_fact_version FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.adjudication_receipt FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.relationship_candidate FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_iso_identity ON memory_r10_m2.memory_identity;
CREATE POLICY tenant_iso_identity ON memory_r10_m2.memory_identity
    USING (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_iso_fact ON memory_r10_m2.memory_fact_version;
CREATE POLICY tenant_iso_fact ON memory_r10_m2.memory_fact_version
    USING (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_iso_adj ON memory_r10_m2.adjudication_receipt;
CREATE POLICY tenant_iso_adj ON memory_r10_m2.adjudication_receipt
    USING (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_iso_rel ON memory_r10_m2.relationship_candidate;
CREATE POLICY tenant_iso_rel ON memory_r10_m2.relationship_candidate
    USING (tenant_id = current_setting('app.tenant_id', true));

COMMENT ON SCHEMA memory_r10_m2 IS 'ISOLATED M2 benchmark only. Do not apply to production.';
