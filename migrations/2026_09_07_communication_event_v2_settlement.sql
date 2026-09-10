-- CommunicationEvent@v2 — provider settlement identity. Satisfies SFR-B-003.
-- Campaign m2-canary-20260907. Closes validated defect 6.
--
-- FORWARD ONLY, and this is the important part: historic legacy rows keep
-- provider_settlement_state='UNKNOWN_LEGACY'. Defect 6 is that recent legacy
-- delivery records lack complete provider settlement identity. Backfilling them
-- with invented identity would CLOSE THE DEFECT ON PAPER while making the ledger
-- less truthful. INTERFACE_CONTRACTS.md §5 forbids it.
--
-- CORRECTION 2026-09-10 (Grok-closure preflight): the settlement index below
-- originally referenced ``occurred_at``, which is not a column on
-- ``communication_events`` (the ledger table uses ``created_at`` / ``observed_at``).
-- The migration had never been applied to any database (verified 2026-09-10:
-- settlement columns absent from live schema), so the index column was corrected
-- to ``created_at DESC`` to match the existing ledger index convention before
-- first application. This is a documented, non-silent correction of an un-applied
-- migration, not a rewrite of shipped history.

ALTER TABLE communication_events
    ADD COLUMN IF NOT EXISTS provider_message_id       TEXT,
    ADD COLUMN IF NOT EXISTS provider_settled_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS provider_settlement_state TEXT,
    ADD COLUMN IF NOT EXISTS delivery_owner            TEXT,
    ADD COLUMN IF NOT EXISTS gateway_mode_at_dispatch  TEXT,
    ADD COLUMN IF NOT EXISTS curation_kind             TEXT,
    ADD COLUMN IF NOT EXISTS curation_provenance       JSONB,
    ADD COLUMN IF NOT EXISTS thread_id                 TEXT,
    ADD COLUMN IF NOT EXISTS subject_guid              TEXT,
    ADD COLUMN IF NOT EXISTS correlation_id            TEXT;

-- Every pre-existing row is legacy by definition: the gateway has never owned
-- delivery (COMMS_GATEWAY_MODE resolves OFF). Marking them UNKNOWN_LEGACY is a
-- statement of fact, not invented identity.
UPDATE communication_events
   SET provider_settlement_state = 'UNKNOWN_LEGACY',
       delivery_owner            = 'legacy'
 WHERE provider_settlement_state IS NULL;

ALTER TABLE communication_events
    ADD CONSTRAINT communication_events_settlement_state_ck
    CHECK (provider_settlement_state IS NULL OR provider_settlement_state IN
           ('UNSETTLED','SETTLED','FAILED','UNKNOWN_LEGACY')) NOT VALID;

ALTER TABLE communication_events
    ADD CONSTRAINT communication_events_delivery_owner_ck
    CHECK (delivery_owner IS NULL OR delivery_owner IN ('gateway','legacy')) NOT VALID;

-- Prefer created_at: live communication_events has created_at (not occurred_at).
CREATE INDEX IF NOT EXISTS communication_events_settlement_idx
    ON communication_events (provider_settlement_state, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS communication_events_provider_msg_uq
    ON communication_events (provider_message_id)
 WHERE provider_message_id IS NOT NULL;
