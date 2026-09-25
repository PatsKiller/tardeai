-- Event lineage on operator conversation turns (M5 Module 1, item 1d).
-- Additive only; nullable; no backfill; never edits a shipped migration.
--
-- M5 audit 2026-09-23: only communication_events carried causation_id /
-- parent_event_id, and no hop an operator question takes (turn -> gap /
-- research request -> completion -> outbound reply) could be joined by event
-- id. The Hermes request/result and gap-request stores are JSONL and carry the
-- same two keys as plain fields; this adds them to the one relational hop.
--
--   event_id         the INBOUND communication_events.event_id of an operator
--                    turn (NULL for agent turns, which are not ledger events)
--   causation_id     the ledger event that caused this turn
--   parent_event_id  the ledger event this turn directly answers
--
-- Writers probe for these columns (scripts/lib/event_lineage.table_has_column)
-- so code may ship before this is applied.

ALTER TABLE operator_conversation_turns
    ADD COLUMN IF NOT EXISTS event_id        TEXT,
    ADD COLUMN IF NOT EXISTS causation_id    TEXT,
    ADD COLUMN IF NOT EXISTS parent_event_id TEXT;

CREATE INDEX IF NOT EXISTS operator_conversation_turns_event_idx
    ON operator_conversation_turns (event_id) WHERE event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS operator_conversation_turns_causation_idx
    ON operator_conversation_turns (causation_id) WHERE causation_id IS NOT NULL;
