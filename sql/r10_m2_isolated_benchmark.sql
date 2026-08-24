-- R10 M2 ISOLATED benchmark schema v2 (Google Notes harmonized).
-- NEVER apply to production. DSN: 127.0.0.1:55432 / m2_shadow only.
-- Production :5432 is forbidden.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP SCHEMA IF EXISTS memory_r10_m2 CASCADE;
CREATE SCHEMA memory_r10_m2;

-- Agent role: not superuser, not BYPASSRLS, not table owner.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'm2_agent') THEN
    CREATE ROLE m2_agent LOGIN PASSWORD 'm2agent' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END$$;

CREATE TABLE memory_r10_m2.predicate_temporal_policy (
    tenant_id       text NOT NULL,
    predicate       text NOT NULL,
    policy          text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, predicate),
    CHECK (policy IN (
        'SINGLE_VALUED_CURRENT',
        'MULTI_VALUED',
        'CONTINUITY_REQUIRED',
        'GAPS_ALLOWED',
        'UNKNOWN_EXPLICIT'
    ))
);

CREATE TABLE memory_r10_m2.memory_identity (
    identity_guid   uuid NOT NULL,
    tenant_id       text NOT NULL,
    namespace       text NOT NULL,
    identity_kind   text NOT NULL,
    subject_guid    text NOT NULL,
    predicate       text NOT NULL,
    canonical_key   text NOT NULL,
    issuer_guid     text,
    security_guid   text,
    listing_guid    text,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, identity_guid),
    UNIQUE (tenant_id, canonical_key)
);

CREATE TABLE memory_r10_m2.memory_fact_version (
    memory_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         text NOT NULL,
    identity_guid     uuid NOT NULL,
    subject_guid      text NOT NULL,
    predicate         text NOT NULL,
    object_value      jsonb NOT NULL,
    value_type        text NOT NULL DEFAULT 'json',
    unit              text,
    currency          text,
    valid_period      tstzrange NOT NULL,
    tx_period         tstzrange NOT NULL,
    status            text NOT NULL,
    confidence        text NOT NULL,
    authority         text NOT NULL DEFAULT 'READ_ONLY_ADVISORY',
    source_type       text NOT NULL,
    source_id         text NOT NULL,
    source_as_of      timestamptz NOT NULL,
    trace_id          text,
    source_sha        text,
    supersedes_id     uuid,
    content_summary   text,
    embedding         vector(768),
    embedding_model   text,
    embedding_dimension int,
    embedding_version text,
    temporal_policy   text NOT NULL DEFAULT 'GAPS_ALLOWED',
    created_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (temporal_policy IN (
        'SINGLE_VALUED_CURRENT','MULTI_VALUED','CONTINUITY_REQUIRED','GAPS_ALLOWED','UNKNOWN_EXPLICIT'
    )),
    CHECK (NOT isempty(valid_period)),
    CHECK (NOT isempty(tx_period)),
    FOREIGN KEY (tenant_id, identity_guid)
        REFERENCES memory_r10_m2.memory_identity (tenant_id, identity_guid)
);

-- CURRENT = upper_inf(tx_period). No separately mutable row_kind.
CREATE INDEX fact_current_idx
    ON memory_r10_m2.memory_fact_version (tenant_id, identity_guid)
    WHERE upper_inf(tx_period);

CREATE INDEX fact_subject_pred_btree
    ON memory_r10_m2.memory_fact_version (tenant_id, subject_guid, predicate);

CREATE INDEX fact_valid_gist
    ON memory_r10_m2.memory_fact_version USING gist (valid_period);

CREATE INDEX fact_tx_gist
    ON memory_r10_m2.memory_fact_version USING gist (tx_period);

CREATE INDEX fact_id_pred_valid_gist
    ON memory_r10_m2.memory_fact_version
    USING gist (identity_guid, predicate, valid_period);

CREATE INDEX fact_valid_spgist
    ON memory_r10_m2.memory_fact_version USING spgist (valid_period);

-- DATABASE_ENFORCED_TEMPORAL_INVARIANT for SINGLE_VALUED_CURRENT only.
-- btree_gist allows text/uuid equality in GiST exclusion.
ALTER TABLE memory_r10_m2.memory_fact_version
    ADD CONSTRAINT fact_single_valued_current_excl
    EXCLUDE USING gist (
        tenant_id WITH =,
        identity_guid WITH =,
        predicate WITH =,
        valid_period WITH &&
    ) WHERE (upper_inf(tx_period) AND temporal_policy = 'SINGLE_VALUED_CURRENT');

CREATE TABLE memory_r10_m2.adjudication_receipt (
    adjudication_id     uuid PRIMARY KEY,
    tenant_id           text NOT NULL,
    subject_guid        text NOT NULL,
    predicate           text NOT NULL,
    conflict_id         text,
    candidate_fact_ids  uuid[] NOT NULL DEFAULT '{}',
    selected_fact_id    uuid,
    rejected_fact_ids   uuid[] NOT NULL DEFAULT '{}',
    deterministic_policy text NOT NULL,
    policy_version      text NOT NULL,
    provider            text,
    model               text,
    prompt_version      text,
    evidence_refs       text[] NOT NULL DEFAULT '{}',
    trace_id            text,
    source_sha          text,
    recorded_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    chain_of_thought    boolean NOT NULL DEFAULT false,
    CHECK (chain_of_thought = false)
);

CREATE TABLE memory_r10_m2.provenance_edge (
    edge_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       text NOT NULL,
    from_object_id  uuid NOT NULL,
    to_object_id    uuid NOT NULL,
    relation        text NOT NULL,
    source          text,
    trace_id        text,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (relation IN (
        'SUPPORTS','CONTRADICTS','SUPERSEDES','ADJUDICATED_BY','DERIVED_FROM','RETRACTS'
    ))
);
CREATE INDEX provenance_from_idx ON memory_r10_m2.provenance_edge (tenant_id, from_object_id);
CREATE INDEX provenance_to_idx ON memory_r10_m2.provenance_edge (tenant_id, to_object_id);

CREATE TABLE memory_r10_m2.relationship_candidate (
    candidate_relationship_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           text NOT NULL,
    source_entity_guid  text NOT NULL,
    target_entity_guid  text NOT NULL,
    relationship_hypothesis text NOT NULL,
    similarity          double precision,
    status              text NOT NULL,
    authoritative       boolean NOT NULL DEFAULT false,
    CHECK (status IN ('CANDIDATE','SUPPORTED','RATIFIED','DISPUTED','SUPERSEDED','RETRACTED')),
    CHECK (NOT (status = 'CANDIDATE' AND authoritative)),
    CHECK (NOT (authoritative AND status <> 'RATIFIED'))
);

-- Trusted write: callers may supply valid_period, NEVER authoritative tx_from.
CREATE OR REPLACE FUNCTION memory_r10_m2.write_fact_version(
    p_tenant_id text,
    p_identity_guid uuid,
    p_subject_guid text,
    p_predicate text,
    p_object jsonb,
    p_valid_period tstzrange,
    p_status text,
    p_temporal_policy text DEFAULT 'GAPS_ALLOWED',
    p_source_type text DEFAULT 'benchmark',
    p_source_id text DEFAULT 'bench',
    p_summary text DEFAULT NULL,
    p_embedding vector DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = memory_r10_m2, pg_temp
AS $$
DECLARE
    v_now timestamptz := clock_timestamp();
    v_id uuid;
    v_prev uuid;
BEGIN
    IF p_tenant_id IS NULL OR btrim(p_tenant_id) = '' THEN
        RAISE EXCEPTION 'TENANT_SCOPE_REQUIRED';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id, true);

    UPDATE memory_r10_m2.memory_fact_version
       SET tx_period = tstzrange(lower(tx_period), v_now, '[)')
     WHERE tenant_id = p_tenant_id
       AND identity_guid = p_identity_guid
       AND upper_inf(tx_period)
    RETURNING memory_version_id INTO v_prev;

    INSERT INTO memory_r10_m2.memory_fact_version (
        tenant_id, identity_guid, subject_guid, predicate, object_value,
        valid_period, tx_period, status, confidence, source_type, source_id,
        source_as_of, content_summary, embedding, embedding_model,
        embedding_dimension, embedding_version, temporal_policy, supersedes_id
    ) VALUES (
        p_tenant_id, p_identity_guid, p_subject_guid, p_predicate, p_object,
        p_valid_period, tstzrange(v_now, NULL, '[)'), p_status, 'low',
        p_source_type, p_source_id, v_now, p_summary, p_embedding,
        CASE WHEN p_embedding IS NULL THEN NULL ELSE 'synthetic-local' END,
        CASE WHEN p_embedding IS NULL THEN NULL ELSE 768 END,
        CASE WHEN p_embedding IS NULL THEN NULL ELSE 'bench-v1' END,
        p_temporal_policy, v_prev
    ) RETURNING memory_version_id INTO v_id;
    RETURN v_id;
END$$;

REVOKE ALL ON FUNCTION memory_r10_m2.write_fact_version(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_r10_m2.write_fact_version(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector) TO m2_agent;
GRANT EXECUTE ON FUNCTION memory_r10_m2.write_fact_version(text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector) TO m2;

-- Block direct INSERT that authors tx_period from agent role; owner may still seed.
CREATE OR REPLACE FUNCTION memory_r10_m2.forbid_client_tx_authoring()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF current_user = 'm2_agent' THEN
        RAISE EXCEPTION 'TX_TIME_RESERVED_FOR_PERSISTENCE_LAYER';
    END IF;
    RETURN NEW;
END$$;

CREATE TRIGGER trg_no_agent_direct_insert
    BEFORE INSERT ON memory_r10_m2.memory_fact_version
    FOR EACH ROW EXECUTE FUNCTION memory_r10_m2.forbid_client_tx_authoring();

ALTER TABLE memory_r10_m2.memory_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.memory_fact_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.adjudication_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.provenance_edge ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.relationship_candidate ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.predicate_temporal_policy ENABLE ROW LEVEL SECURITY;

ALTER TABLE memory_r10_m2.memory_identity FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.memory_fact_version FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.adjudication_receipt FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.provenance_edge FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.relationship_candidate FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_r10_m2.predicate_temporal_policy FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_iso_identity ON memory_r10_m2.memory_identity
    USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_fact ON memory_r10_m2.memory_fact_version
    USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_adj ON memory_r10_m2.adjudication_receipt
    USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_prov ON memory_r10_m2.provenance_edge
    USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_rel ON memory_r10_m2.relationship_candidate
    USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_pred ON memory_r10_m2.predicate_temporal_policy
    USING (tenant_id = current_setting('app.tenant_id', true));

GRANT USAGE ON SCHEMA memory_r10_m2 TO m2_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA memory_r10_m2 TO m2_agent;
GRANT INSERT, UPDATE ON memory_r10_m2.memory_identity TO m2_agent;
GRANT INSERT ON memory_r10_m2.adjudication_receipt TO m2_agent;
GRANT INSERT ON memory_r10_m2.provenance_edge TO m2_agent;
GRANT INSERT ON memory_r10_m2.relationship_candidate TO m2_agent;
GRANT INSERT, UPDATE ON memory_r10_m2.predicate_temporal_policy TO m2_agent;
-- No INSERT privilege on fact table for agent: writes go through SECURITY DEFINER function.

COMMENT ON SCHEMA memory_r10_m2 IS 'ISOLATED M2 v2. tstzrange. DB-owned tx_time. Do not apply to production.';
