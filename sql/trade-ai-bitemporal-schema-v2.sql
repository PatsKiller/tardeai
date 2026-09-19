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
--   row_kind / is_single_valued → REJECTED by architect reconciliation;
--                                 CURRENT := upper_inf(tx_period);
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
GRANT EXECUTE ON FUNCTION memory_r10_m2.save_bitemporal_fact_version(
    text,uuid,text,text,jsonb,tstzrange,text,text,text,text,text,vector
) TO m2;

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
CREATE OR REPLACE VIEW memory_r10_m2."MemoryIdentity@v1" AS
    SELECT * FROM memory_r10_m2.memory_identity;
CREATE OR REPLACE VIEW memory_r10_m2."MemoryFactVersion@v2" AS
    SELECT * FROM memory_r10_m2.memory_fact_version;
CREATE OR REPLACE VIEW memory_r10_m2."AdjudicationReceipt@v1" AS
    SELECT * FROM memory_r10_m2.adjudication_receipt;
CREATE OR REPLACE VIEW memory_r10_m2."ProvenanceEdge@v1" AS
    SELECT * FROM memory_r10_m2.provenance_edge;

COMMENT ON FUNCTION memory_r10_m2.save_bitemporal_fact_version IS
    'Alias of write_fact_version. DB owns tx_period. Callers supply valid_period only.';
COMMENT ON FUNCTION memory_r10_m2.block_bitemporal_manipulation IS
    'Hard-stop DELETE/UPDATE of closed audit versions; CURRENT close via writer only.';
