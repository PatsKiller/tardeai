-- AgentConsumptionReceipt@v2 — source-neutral consumption receipts.
-- Campaign m2-canary-20260907, INTEGRATION_ORDER.md step 10.
-- Satisfies SFR-A-002 and SFR-B-002 (both lanes requested the same DDL).
-- Authored by the integration owner; migrations/** is never lane-leased.
--
-- @v1 was communications-shaped: event_id TEXT NOT NULL, no source discriminator.
-- It could not express a wake consuming a research dossier or a memory fact,
-- which is the A/B collision INTERFACE_CONTRACTS.md §6 froze. Additive and
-- backward-compatible: @v1 readers keep working.
--
-- FORWARD ONLY. Historic rows are NOT backfilled with invented identity.
-- Note: at authoring time every pre-existing row in this table (5) is an
-- orphan tombstoned on 2026-09-07 — see proposals/BASELINE_AMENDMENT_2026-09-07.md.

ALTER TABLE communication_agent_consumption_receipts
    ADD COLUMN IF NOT EXISTS source_kind  TEXT,
    ADD COLUMN IF NOT EXISTS source_id    TEXT,
    ADD COLUMN IF NOT EXISTS wake_id      TEXT,
    ADD COLUMN IF NOT EXISTS subject_guid TEXT,
    ADD COLUMN IF NOT EXISTS effect_kind  TEXT,
    ADD COLUMN IF NOT EXISTS effect_ref   TEXT,
    ADD COLUMN IF NOT EXISTS source_sha       TEXT,
    ADD COLUMN IF NOT EXISTS correlation_id   TEXT,
    ADD COLUMN IF NOT EXISTS idempotency_key  TEXT,
    ADD COLUMN IF NOT EXISTS parent_id        TEXT,
    ADD COLUMN IF NOT EXISTS parent_kind      TEXT,
    ADD COLUMN IF NOT EXISTS retention_class  TEXT,
    ADD COLUMN IF NOT EXISTS lifecycle_state  TEXT,
    ADD COLUMN IF NOT EXISTS provenance       JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Map @v1 rows onto the @v2 shape WITHOUT inventing identity: an existing
-- event_id becomes (source_kind='comm_event', source_id=event_id). Nothing else
-- is guessed; effect_kind stays NULL because @v1 never recorded an effect.
UPDATE communication_agent_consumption_receipts
   SET source_kind = 'comm_event',
       source_id   = event_id
 WHERE source_kind IS NULL
   AND event_id IS NOT NULL;

ALTER TABLE communication_agent_consumption_receipts
    ADD CONSTRAINT communication_agent_consumption_receipts_source_kind_ck
    CHECK (source_kind IS NULL OR source_kind IN
           ('comm_event','research_object','memory_fact','operator_turn'))
    NOT VALID;

ALTER TABLE communication_agent_consumption_receipts
    ADD CONSTRAINT communication_agent_consumption_receipts_effect_kind_ck
    CHECK (effect_kind IS NULL OR effect_kind IN
           ('none','changed_question','changed_priority','changed_view','changed_commitment'))
    NOT VALID;

-- Uniqueness moves from (agent_id, event_id, purpose) to the source-neutral key.
CREATE UNIQUE INDEX IF NOT EXISTS communication_agent_consumption_receipts_src_uq
    ON communication_agent_consumption_receipts (agent_id, source_kind, source_id, purpose)
 WHERE source_kind IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS communication_agent_consumption_receipts_idem_uq
    ON communication_agent_consumption_receipts (idempotency_key)
 WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS communication_agent_consumption_receipts_wake_idx
    ON communication_agent_consumption_receipts (wake_id, retrieved_at DESC)
 WHERE wake_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS communication_agent_consumption_receipts_effect_idx
    ON communication_agent_consumption_receipts (effect_kind, retrieved_at DESC)
 WHERE effect_kind IS NOT NULL AND effect_kind <> 'none';
