-- Trade AI Bitemporal Memory Substrate v2
-- =====================================================================
-- Canonical packaging of the M2 isolated schema (Google Notes reconciled).
-- NEVER apply to production :5432. Isolated DSN only: 127.0.0.1:55432 / m2_shadow.
--
-- Name map (prompt → this DDL):
--   MemoryIdentity@v1           → memory_r10_m2.memory_identity
--   MemoryFactVersion@v2        → memory_r10_m2.memory_fact_version
--   AdjudicationReceipt@v1      → memory_r10_m2.adjudication_receipt
--   ProvenanceEdge@v1           → memory_r10_m2.provenance_edge
--   save_bitemporal_fact_version→ memory_r10_m2.save_bitemporal_fact_version
--                                 (alias of write_fact_version)
--   exclude_bitemporal_overlap  → fact_single_valued_current_excl
--   row_kind / is_single_valued → REJECTED as stored columns by architect
--                                 reconciliation; CURRENT := upper_inf(tx_period).
--                                 row_kind is exposed as a COMPUTED column on
--                                 "MemoryFactVersion@v2" (current | audit);
--                                 SINGLE_VALUED via temporal_policy.
--
-- Constitutional rails:
--   * Cognitive memory only — never cash/positions/ledger prices.
--   * Link via GUID spine (issuer_guid → security_guid → listing_guid).
--   * DB owns tx_period (statement_timestamp + version_seq).
--   * Composite keys (tenant_id, guid) + FORCE RLS.
-- =====================================================================

-- Prerequisite: apply sql/r10_m2_isolated_benchmark.sql first (Python harness
-- does both). This file is the v2 packaging delta + prompt-name aliases only.

-- Explicit extensions named by the deploy brief (pgcrypto already supplies
-- gen_random_uuid; uuid-ossp is additive for callers that prefer uuid_generate_v4).
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Alias: prompt name → existing SECURITY DEFINER writer.
CREATE OR REPLACE FUNCTION memory_r10_m2.save_bitemporal_fact_version(
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
LANGUAGE sql
SECURITY DEFINER
SET search_path = memory_r10_m2, pg_temp
AS $$
    SELECT memory_r10_m2.write_fact_version(
        p_tenant_id, p_identity_guid, p_subject_guid, p_predicate, p_object,
        p_valid_period, p_status, p_temporal_policy, p_source_type, p_source_id,
        p_summary, p_embedding
    );
$$;

REVOKE ALL ON FUNCTION memory_r10_m2.save_bitemporal_fact_version(
    text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_r10_m2.save_bitemporal_fact_version(
    text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector
) TO m2_agent;
-- Role `m2` exists only on the isolated shadow container (its superuser). A
-- hard GRANT ... TO m2 made this delta fail on any database without that role,
-- production included. Grant only where the role exists.
DO $grant_m2$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'm2') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION memory_r10_m2.save_bitemporal_fact_version('
             || 'text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector) TO m2';
    END IF;
END
$grant_m2$;

-- Immutable audit protection: closed (historical) versions cannot be mutated
-- or deleted. CURRENT rows may only shrink tx_period via write_fact_version.
CREATE OR REPLACE FUNCTION memory_r10_m2.block_bitemporal_manipulation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF NOT upper_inf(OLD.tx_period) THEN
            RAISE EXCEPTION 'BITEMPORAL_AUDIT_IMMUTABLE: cannot DELETE closed fact version %',
                OLD.memory_version_id;
        END IF;
        RAISE EXCEPTION 'BITEMPORAL_AUDIT_IMMUTABLE: DELETE forbidden; close via write_fact_version';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NOT upper_inf(OLD.tx_period) THEN
            RAISE EXCEPTION 'BITEMPORAL_AUDIT_IMMUTABLE: cannot UPDATE closed fact version %',
                OLD.memory_version_id;
        END IF;
        -- Allow only tx_period upper-bound shrink on CURRENT (version closure).
        IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.identity_guid IS DISTINCT FROM OLD.identity_guid
           OR NEW.subject_guid IS DISTINCT FROM OLD.subject_guid
           OR NEW.predicate IS DISTINCT FROM OLD.predicate
           OR NEW.object_value IS DISTINCT FROM OLD.object_value
           OR NEW.valid_period IS DISTINCT FROM OLD.valid_period
           OR NEW.temporal_policy IS DISTINCT FROM OLD.temporal_policy
        THEN
            RAISE EXCEPTION 'BITEMPORAL_AUDIT_IMMUTABLE: CURRENT mutation limited to tx_period close';
        END IF;
    END IF;
    RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS trg_block_fact_manipulation ON memory_r10_m2.memory_fact_version;
CREATE TRIGGER trg_block_fact_manipulation
    BEFORE UPDATE OR DELETE ON memory_r10_m2.memory_fact_version
    FOR EACH ROW EXECUTE FUNCTION memory_r10_m2.block_bitemporal_manipulation();

-- Compatibility view names matching the deploy brief.
-- security_invoker: the views are owned by the schema owner, which may be a
-- superuser that bypasses RLS. Without security_invoker a reader granted the
-- view would see every tenant's rows; with it, the reader's own RLS applies.
-- row_kind is COMPUTED, never stored: the architect reconciliation rejected a
-- mutable row_kind column (it can disagree with tx_period); CURRENT is still
-- defined by upper_inf(tx_period) and the view only names it.
CREATE OR REPLACE VIEW memory_r10_m2."MemoryIdentity@v1"
    WITH (security_invoker = true) AS
    SELECT * FROM memory_r10_m2.memory_identity;
CREATE OR REPLACE VIEW memory_r10_m2."MemoryFactVersion@v2"
    WITH (security_invoker = true) AS
    SELECT f.*,
           CASE WHEN upper_inf(f.tx_period) THEN 'current' ELSE 'audit' END AS row_kind
      FROM memory_r10_m2.memory_fact_version f;
CREATE OR REPLACE VIEW memory_r10_m2."AdjudicationReceipt@v1"
    WITH (security_invoker = true) AS
    SELECT * FROM memory_r10_m2.adjudication_receipt;
CREATE OR REPLACE VIEW memory_r10_m2."ProvenanceEdge@v1"
    WITH (security_invoker = true) AS
    SELECT * FROM memory_r10_m2.provenance_edge;

-- subject_guid lookups ((tenant_id, subject_guid) is the join every reader
-- uses). Indexes, not UNIQUE: one subject legitimately carries many
-- identities (one per predicate) and many receipts.
CREATE INDEX IF NOT EXISTS identity_tenant_subject_idx
    ON memory_r10_m2.memory_identity (tenant_id, subject_guid);
CREATE INDEX IF NOT EXISTS adj_tenant_subject_idx
    ON memory_r10_m2.adjudication_receipt (tenant_id, subject_guid, recorded_at);

-- SINGLE_VALUED supersession (M5 Module 2.2). write_fact_version closes EVERY
-- current version of an identity and never touches valid time, so a SINGLE_VALUED
-- predicate could not change its mind: CURRENT rows carry open-ended valid
-- periods, every later assertion overlapped, and the caller suppressed it
-- ("first thesis wins forever"). This writer supersedes only the overlapping
-- current versions: each is closed in transaction time (audit is kept) and the
-- parts of its valid period OUTSIDE the new assertion are re-asserted as current
-- remnants, so "what did we believe for [t1, t2)" still answers with the old
-- belief while [t2, …) answers with the new one. The EXCLUDE constraint holds
-- because remnants and the new version never overlap.
CREATE OR REPLACE FUNCTION memory_r10_m2.supersede_single_valued_fact(
    p_tenant_id text,
    p_identity_guid uuid,
    p_subject_guid text,
    p_predicate text,
    p_object jsonb,
    p_valid_period tstzrange,
    p_status text,
    p_source_type text,
    p_source_id text,
    p_summary text DEFAULT NULL,
    p_new_version_id uuid DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = memory_r10_m2, pg_temp
AS $$
DECLARE
    v_now timestamptz := statement_timestamp();
    v_id uuid := COALESCE(p_new_version_id, gen_random_uuid());
    v_first_prev uuid;
    r memory_r10_m2.memory_fact_version%ROWTYPE;
    v_left tstzrange;
    v_right tstzrange;
BEGIN
    IF p_tenant_id IS NULL OR btrim(p_tenant_id) = '' THEN
        RAISE EXCEPTION 'TENANT_SCOPE_REQUIRED';
    END IF;
    IF p_valid_period IS NULL OR isempty(p_valid_period) THEN
        RAISE EXCEPTION 'VALID_PERIOD_REQUIRED';
    END IF;
    PERFORM set_config('app.tenant_id', p_tenant_id, true);

    FOR r IN
        SELECT * FROM memory_r10_m2.memory_fact_version
         WHERE tenant_id = p_tenant_id
           AND identity_guid = p_identity_guid
           AND predicate = p_predicate
           AND upper_inf(tx_period)
           AND temporal_policy = 'SINGLE_VALUED_CURRENT'
           AND valid_period && p_valid_period
         ORDER BY version_seq
         FOR UPDATE
    LOOP
        v_first_prev := COALESCE(v_first_prev, r.memory_version_id);
        UPDATE memory_r10_m2.memory_fact_version
           SET tx_period = tstzrange(lower(tx_period), v_now, '[)')
         WHERE memory_version_id = r.memory_version_id;

        v_left := NULL;
        v_right := NULL;
        IF NOT lower_inf(p_valid_period)
           AND (lower_inf(r.valid_period) OR lower(r.valid_period) < lower(p_valid_period)) THEN
            v_left := tstzrange(lower(r.valid_period), lower(p_valid_period), '[)');
        END IF;
        IF NOT upper_inf(p_valid_period)
           AND (upper_inf(r.valid_period) OR upper(r.valid_period) > upper(p_valid_period)) THEN
            v_right := tstzrange(upper(p_valid_period), upper(r.valid_period), '[)');
        END IF;

        IF v_left IS NOT NULL AND NOT isempty(v_left) THEN
            INSERT INTO memory_r10_m2.memory_fact_version (
                tenant_id, identity_guid, subject_guid, predicate, object_value,
                value_type, unit, currency, valid_period, tx_period, status,
                confidence, authority, source_type, source_id, source_as_of,
                trace_id, source_sha, supersedes_id, content_summary, embedding,
                embedding_model, embedding_dimension, embedding_version, temporal_policy
            ) VALUES (
                r.tenant_id, r.identity_guid, r.subject_guid, r.predicate, r.object_value,
                r.value_type, r.unit, r.currency, v_left, tstzrange(v_now, NULL, '[)'), r.status,
                r.confidence, r.authority, r.source_type, r.source_id, r.source_as_of,
                r.trace_id, r.source_sha, r.memory_version_id, r.content_summary, r.embedding,
                r.embedding_model, r.embedding_dimension, r.embedding_version, r.temporal_policy
            );
        END IF;
        IF v_right IS NOT NULL AND NOT isempty(v_right) THEN
            INSERT INTO memory_r10_m2.memory_fact_version (
                tenant_id, identity_guid, subject_guid, predicate, object_value,
                value_type, unit, currency, valid_period, tx_period, status,
                confidence, authority, source_type, source_id, source_as_of,
                trace_id, source_sha, supersedes_id, content_summary, embedding,
                embedding_model, embedding_dimension, embedding_version, temporal_policy
            ) VALUES (
                r.tenant_id, r.identity_guid, r.subject_guid, r.predicate, r.object_value,
                r.value_type, r.unit, r.currency, v_right, tstzrange(v_now, NULL, '[)'), r.status,
                r.confidence, r.authority, r.source_type, r.source_id, r.source_as_of,
                r.trace_id, r.source_sha, r.memory_version_id, r.content_summary, r.embedding,
                r.embedding_model, r.embedding_dimension, r.embedding_version, r.temporal_policy
            );
        END IF;
    END LOOP;

    INSERT INTO memory_r10_m2.memory_fact_version (
        memory_version_id, tenant_id, identity_guid, subject_guid, predicate, object_value,
        valid_period, tx_period, status, confidence, source_type, source_id,
        source_as_of, content_summary, temporal_policy, supersedes_id
    ) VALUES (
        v_id, p_tenant_id, p_identity_guid, p_subject_guid, p_predicate, p_object,
        p_valid_period, tstzrange(v_now, NULL, '[)'), p_status, 'low',
        p_source_type, p_source_id, v_now, p_summary, 'SINGLE_VALUED_CURRENT', v_first_prev
    );
    RETURN v_id;
END$$;

REVOKE ALL ON FUNCTION memory_r10_m2.supersede_single_valued_fact(
    text,uuid,text,text,jsonb,tstzrange,text,text,text,text,uuid
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_r10_m2.supersede_single_valued_fact(
    text,uuid,text,text,jsonb,tstzrange,text,text,text,text,uuid
) TO m2_agent;
DO $grant_m2_supersede$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'm2') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION memory_r10_m2.supersede_single_valued_fact('
             || 'text,uuid,text,text,jsonb,tstzrange,text,text,text,text,uuid) TO m2';
    END IF;
END
$grant_m2_supersede$;

COMMENT ON FUNCTION memory_r10_m2.supersede_single_valued_fact IS
    'SINGLE_VALUED writer: closes overlapping CURRENT versions in tx time, re-asserts '
    'their non-overlapping valid remnants, inserts the new version. DB owns tx_period.';

COMMENT ON FUNCTION memory_r10_m2.save_bitemporal_fact_version IS
    'Alias of write_fact_version. DB owns tx_period. Callers supply valid_period only.';
COMMENT ON FUNCTION memory_r10_m2.block_bitemporal_manipulation IS
    'Hard-stop DELETE/UPDATE of closed audit versions; CURRENT close via writer only.';
