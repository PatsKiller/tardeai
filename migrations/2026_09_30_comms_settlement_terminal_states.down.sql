-- Down: restore the four-state CHECK. Rows already stamped SUPPRESSED/WITHDRAWN would violate
-- it, so they are returned to UNSETTLED first (their delivery rows keep the true status).
UPDATE communication_events
   SET provider_settlement_state = 'UNSETTLED', provider_settled_at = NULL
 WHERE provider_settlement_state IN ('SUPPRESSED','WITHDRAWN');

ALTER TABLE communication_events
    DROP CONSTRAINT IF EXISTS communication_events_settlement_state_ck;

ALTER TABLE communication_events
    ADD CONSTRAINT communication_events_settlement_state_ck
    CHECK (provider_settlement_state IS NULL OR provider_settlement_state IN
           ('UNSETTLED','SETTLED','FAILED','UNKNOWN_LEGACY')) NOT VALID;
