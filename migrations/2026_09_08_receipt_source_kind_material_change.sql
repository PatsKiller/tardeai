-- AgentConsumptionReceipt@v2: allow source_kind='material_change'.
-- Campaign m2-canary-20260907, SFR-A-FOLLOWUP3-002.
--
-- The wake subject selector selects on MaterialChange@v1, so a consumption
-- receipt must be able to name one as its source. The @v2 CHECK constraint
-- listed only comm_event/research_object/memory_fact/operator_turn, so the
-- Python-side extension alone would have failed at write time.
ALTER TABLE communication_agent_consumption_receipts
    DROP CONSTRAINT IF EXISTS communication_agent_consumption_receipts_source_kind_ck;
ALTER TABLE communication_agent_consumption_receipts
    ADD CONSTRAINT communication_agent_consumption_receipts_source_kind_ck
    CHECK (source_kind IS NULL OR source_kind IN
           ('comm_event','research_object','memory_fact','operator_turn','material_change'))
    NOT VALID;
