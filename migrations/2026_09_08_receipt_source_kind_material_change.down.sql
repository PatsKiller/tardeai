-- Rollback: restore the @v2 source_kind list without material_change.
-- Rows already carrying material_change are NOT deleted (AGENTS.md §0.6); the
-- constraint is re-added NOT VALID so existing rows are left in place.
ALTER TABLE communication_agent_consumption_receipts
    DROP CONSTRAINT IF EXISTS communication_agent_consumption_receipts_source_kind_ck;
ALTER TABLE communication_agent_consumption_receipts
    ADD CONSTRAINT communication_agent_consumption_receipts_source_kind_ck
    CHECK (source_kind IS NULL OR source_kind IN
           ('comm_event','research_object','memory_fact','operator_turn'))
    NOT VALID;
