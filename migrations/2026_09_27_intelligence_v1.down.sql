-- Rollback for 2026_09_27_intelligence_v1.sql.
-- Evidence preservation (AGENTS.md §0 rule 6): the SAFE rollback disables the policies and drops
-- the indexes only. The FULL revert drops the schema and is NEVER run automatically — it is the
-- operator's reviewed action (memory 2026-09-19: DROP SCHEMA CASCADE is destructive on re-run).

-- SAFE ROLLBACK
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['gir_entity','gir_envelope','gir_edge','research_index','embedding','retrieval_receipt','memory_context']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='intelligence' AND tablename=t AND policyname='tenant_isolation') THEN
            EXECUTE format('DROP POLICY tenant_isolation ON intelligence.%I', t);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='intelligence' AND tablename=t) THEN
            EXECUTE format('ALTER TABLE intelligence.%I NO FORCE ROW LEVEL SECURITY', t);
            EXECUTE format('ALTER TABLE intelligence.%I DISABLE ROW LEVEL SECURITY', t);
        END IF;
    END LOOP;
END$$;
DROP INDEX IF EXISTS intelligence.gir_entity_class_kind_idx;
DROP INDEX IF EXISTS intelligence.gir_envelope_freshness_idx;
DROP INDEX IF EXISTS intelligence.gir_edge_from_rel_idx;
DROP INDEX IF EXISTS intelligence.gir_edge_to_rel_idx;
DROP INDEX IF EXISTS intelligence.gir_edge_valid_gist;
DROP INDEX IF EXISTS intelligence.research_index_latest_idx;
DROP INDEX IF EXISTS intelligence.retrieval_receipt_lane_day_idx;
DROP INDEX IF EXISTS intelligence.retrieval_receipt_subject_idx;
DROP INDEX IF EXISTS intelligence.memory_context_lane_day_idx;
DROP INDEX IF EXISTS intelligence.heartbeat_lane_last_idx;
DROP INDEX IF EXISTS intelligence.breach_open_idx;

-- FULL REVERT ONLY — operator-reviewed, never automatic:
-- DROP SCHEMA intelligence CASCADE;
