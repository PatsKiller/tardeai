-- CommunicationEvent@v2 — two terminal settlement states (2026-09-30).
--
-- Measured 2026-09-30 (read-only): 7,366 communication_events UNSETTLED in 7 days, of which
-- 7,158 were SUPPRESSED deliveries (delivery_owner=legacy). SUPPRESSED is terminal in the
-- delivery state machine (scripts/lib/comms/delivery.py _TRANSITIONS) but had no settlement
-- mapping, so the event stayed UNSETTLED forever and "UNSETTLED" stopped meaning "in flight".
--
--   SUPPRESSED — the channel policy deliberately did not send (dedupe, quiet hours, cap).
--   WITHDRAWN  — the delivery expired or was cancelled before a provider accepted it.
--
-- FORWARD ONLY. Historic rows are NOT backfilled: a later read-only report may count how many
-- old UNSETTLED events have a SUPPRESSED delivery, but rewriting them is a separate, granted step.
-- The code (settlement_state_for) retries without the state when this constraint is absent, so
-- deploying code before this migration changes nothing.

ALTER TABLE communication_events
    DROP CONSTRAINT IF EXISTS communication_events_settlement_state_ck;

ALTER TABLE communication_events
    ADD CONSTRAINT communication_events_settlement_state_ck
    CHECK (provider_settlement_state IS NULL OR provider_settlement_state IN
           ('UNSETTLED','SETTLED','FAILED','UNKNOWN_LEGACY','SUPPRESSED','WITHDRAWN')) NOT VALID;
