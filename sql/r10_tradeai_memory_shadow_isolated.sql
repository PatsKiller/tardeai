-- Isolated TRADEAI MEMORY SHADOW (R10.10).
-- SHADOW_ONLY. CANONICAL_READERS_UNCHANGED. MEMORY_BEHAVIOR_INFLUENCE=0.
-- NEVER apply to production :5432. Isolated DSN: 127.0.0.1:55432 / m2_shadow.
-- Production apply requires an explicit production-sql-write grant (absent here).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP SCHEMA IF EXISTS tradeai_memory_shadow CASCADE;
CREATE SCHEMA tradeai_memory_shadow;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradeai_memory_shadow_owner') THEN
    CREATE ROLE tradeai_memory_shadow_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradeai_memory_shadow_writer') THEN
    CREATE ROLE tradeai_memory_shadow_writer LOGIN PASSWORD 'shadowwriter'
      NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradeai_memory_shadow_reader') THEN
    CREATE ROLE tradeai_memory_shadow_reader LOGIN PASSWORD 'shadowreader'
      NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END$$;

ALTER SCHEMA tradeai_memory_shadow OWNER TO CURRENT_USER;

CREATE TABLE tradeai_memory_shadow.predicate_temporal_policy (
    tenant_id  text NOT NULL,
    predicate  text NOT NULL,
    policy     text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, predicate),
    CHECK (policy IN ('SINGLE_VALUED_CURRENT','MULTI_VALUED','CONTINUITY_REQUIRED','GAPS_ALLOWED','UNKNOWN_EXPLICIT'))
);

CREATE TABLE tradeai_memory_shadow.memory_identity (
    identity_guid uuid NOT NULL,
    tenant_id     text NOT NULL,
    namespace     text NOT NULL,
    identity_kind text NOT NULL,
    subject_guid  text NOT NULL,
    predicate     text NOT NULL,
    canonical_key text NOT NULL,
    issuer_guid   text,
    security_guid text,
    listing_guid  text,
    ticker_guid   text,
    created_at    timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (tenant_id, identity_guid),
    UNIQUE (tenant_id, canonical_key)
);

CREATE TABLE tradeai_memory_shadow.memory_fact_version (
    memory_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         text NOT NULL,
    identity_guid     uuid NOT NULL,
    subject_guid      text NOT NULL,
    predicate         text NOT NULL,
    object_value      jsonb NOT NULL,
    valid_period      tstzrange NOT NULL,
    tx_period         tstzrange NOT NULL,
    status            text NOT NULL,
    confidence        text NOT NULL DEFAULT 'low',
    authority         text NOT NULL DEFAULT 'READ_ONLY_ADVISORY',
    source_type       text NOT NULL,
    source_id         text NOT NULL,
    source_version    text,
    source_as_of      timestamptz NOT NULL,
    source_sha        text,
    projection_version text NOT NULL DEFAULT 'v1',
    projection_run_id  text,
    idempotency_key    text NOT NULL,
    supersedes_id      uuid,
    content_summary    text,
    embedding          vector(768),
    embedding_model    text,
    temporal_policy    text NOT NULL DEFAULT 'SINGLE_VALUED_CURRENT',
    version_seq        bigserial NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (NOT isempty(valid_period)),
    CHECK (NOT isempty(tx_period)),
    CHECK (authority = 'READ_ONLY_ADVISORY'),
    FOREIGN KEY (tenant_id, identity_guid)
      REFERENCES tradeai_memory_shadow.memory_identity (tenant_id, identity_guid)
);

CREATE UNIQUE INDEX fact_idemp_current
  ON tradeai_memory_shadow.memory_fact_version (tenant_id, idempotency_key)
  WHERE upper_inf(tx_period);

CREATE INDEX fact_current_idx
  ON tradeai_memory_shadow.memory_fact_version (tenant_id, identity_guid)
  WHERE upper_inf(tx_period);

CREATE INDEX fact_valid_gist ON tradeai_memory_shadow.memory_fact_version USING gist (valid_period);
CREATE INDEX fact_tx_gist ON tradeai_memory_shadow.memory_fact_version USING gist (tx_period);

ALTER TABLE tradeai_memory_shadow.memory_fact_version
  ADD CONSTRAINT fact_single_valued_current_excl
  EXCLUDE USING gist (
    tenant_id WITH =,
    identity_guid WITH =,
    predicate WITH =,
    valid_period WITH &&
  ) WHERE (upper_inf(tx_period) AND temporal_policy = 'SINGLE_VALUED_CURRENT');

CREATE TABLE tradeai_memory_shadow.provenance_edge (
    edge_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   text NOT NULL,
    from_fact_id uuid,
    to_fact_id   uuid,
    relation    text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE tradeai_memory_shadow.adjudication_receipt (
    adjudication_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       text NOT NULL,
    subject_guid    text NOT NULL,
    predicate       text NOT NULL,
    selected_fact_id uuid,
    policy          text NOT NULL,
    chain_of_thought boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE tradeai_memory_shadow.shadow_run_receipt (
    run_id     text PRIMARY KEY,
    source_sha text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    created    int NOT NULL DEFAULT 0,
    unchanged  int NOT NULL DEFAULT 0,
    versioned  int NOT NULL DEFAULT 0,
    unresolved int NOT NULL DEFAULT 0,
    excluded   int NOT NULL DEFAULT 0,
    failed     int NOT NULL DEFAULT 0,
    status     text NOT NULL,
    authority  text NOT NULL DEFAULT 'READ_ONLY_ADVISORY',
    influence  int NOT NULL DEFAULT 0
);

CREATE TABLE tradeai_memory_shadow.projection_receipt (
    receipt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     text NOT NULL,
    tenant_id  text NOT NULL,
    source_type text NOT NULL,
    source_id   text NOT NULL,
    identity_guid uuid,
    memory_version_id uuid,
    outcome    text NOT NULL,
    reason     text,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE OR REPLACE FUNCTION tradeai_memory_shadow.write_fact_version(
    p_tenant_id text,
    p_identity_guid uuid,
    p_subject_guid text,
    p_predicate text,
    p_object jsonb,
    p_valid_period tstzrange,
    p_status text,
    p_source_type text,
    p_source_id text,
    p_source_version text,
    p_source_sha text,
    p_idempotency_key text,
    p_run_id text,
    p_temporal_policy text DEFAULT 'SINGLE_VALUED_CURRENT'
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = tradeai_memory_shadow, pg_temp
AS $$
DECLARE
    v_now timestamptz := statement_timestamp();
    v_id uuid;
    v_prev uuid;
    v_exist uuid;
    v_obj jsonb;
BEGIN
    IF p_tenant_id IS NULL OR btrim(p_tenant_id) = '' THEN
        RAISE EXCEPTION 'TENANT_SCOPE_REQUIRED';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id, true);

    SELECT memory_version_id, object_value INTO v_exist, v_obj
      FROM tradeai_memory_shadow.memory_fact_version
     WHERE tenant_id = p_tenant_id AND idempotency_key = p_idempotency_key AND upper_inf(tx_period);
    IF v_exist IS NOT NULL AND v_obj IS NOT DISTINCT FROM p_object THEN
        RETURN v_exist;
    END IF;

    UPDATE tradeai_memory_shadow.memory_fact_version
       SET tx_period = tstzrange(lower(tx_period), v_now, '[)')
     WHERE tenant_id = p_tenant_id
       AND identity_guid = p_identity_guid
       AND predicate = p_predicate
       AND upper_inf(tx_period)
       AND (p_temporal_policy = 'SINGLE_VALUED_CURRENT' OR idempotency_key = p_idempotency_key)
    RETURNING memory_version_id INTO v_prev;

    INSERT INTO tradeai_memory_shadow.memory_fact_version (
        tenant_id, identity_guid, subject_guid, predicate, object_value,
        valid_period, tx_period, status, source_type, source_id, source_version,
        source_as_of, source_sha, projection_run_id, idempotency_key,
        temporal_policy, supersedes_id
    ) VALUES (
        p_tenant_id, p_identity_guid, p_subject_guid, p_predicate, p_object,
        p_valid_period, tstzrange(v_now, NULL, '[)'), p_status,
        p_source_type, p_source_id, p_source_version, v_now, p_source_sha,
        p_run_id, p_idempotency_key, p_temporal_policy, v_prev
    ) RETURNING memory_version_id INTO v_id;
    RETURN v_id;
END$$;

REVOKE ALL ON FUNCTION tradeai_memory_shadow.write_fact_version(
  text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION tradeai_memory_shadow.write_fact_version(
  text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,text,text,text)
  TO tradeai_memory_shadow_writer;

ALTER TABLE tradeai_memory_shadow.memory_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.memory_fact_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.provenance_edge ENABLE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.adjudication_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.projection_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.predicate_temporal_policy ENABLE ROW LEVEL SECURITY;

ALTER TABLE tradeai_memory_shadow.memory_identity FORCE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.memory_fact_version FORCE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.provenance_edge FORCE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.adjudication_receipt FORCE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.projection_receipt FORCE ROW LEVEL SECURITY;
ALTER TABLE tradeai_memory_shadow.predicate_temporal_policy FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_iso_identity ON tradeai_memory_shadow.memory_identity
  USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_fact ON tradeai_memory_shadow.memory_fact_version
  USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_prov ON tradeai_memory_shadow.provenance_edge
  USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_adj ON tradeai_memory_shadow.adjudication_receipt
  USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_proj ON tradeai_memory_shadow.projection_receipt
  USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_iso_pred ON tradeai_memory_shadow.predicate_temporal_policy
  USING (tenant_id = current_setting('app.tenant_id', true));

GRANT USAGE ON SCHEMA tradeai_memory_shadow TO tradeai_memory_shadow_writer, tradeai_memory_shadow_reader;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA tradeai_memory_shadow TO tradeai_memory_shadow_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tradeai_memory_shadow TO tradeai_memory_shadow_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA tradeai_memory_shadow TO tradeai_memory_shadow_reader;
-- Writer has no BYPASSRLS; fact inserts go through SECURITY DEFINER function.
REVOKE INSERT ON tradeai_memory_shadow.memory_fact_version FROM tradeai_memory_shadow_writer;

COMMENT ON SCHEMA tradeai_memory_shadow IS 'NON-AUTHORITATIVE cognition shadow. Isolated. Do not apply to production without grant.';
