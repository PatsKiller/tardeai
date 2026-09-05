-- Trade AI Communications Gateway — inbound checkpoint + callback quarantine (Wave C).
-- Additive only. Does not modify broker/order/2FA/guardrail tables.
--
-- Wave C fixes the "offset advanced before processing" defect: the legacy poller
-- wrote its getUpdates offset before handling each update, so a crash after the
-- offset write permanently dropped that update. The gateway now advances a
-- committed update_id only after the CommunicationEvent is persisted, and holds
-- unresolved callback queries in a quarantine table rather than answering or
-- dropping them.

-- Single-row checkpoint. committed_update_id is the highest update_id whose
-- inbound event has been persisted. The poller reads it and passes
-- offset = committed_update_id + 1 to getUpdates.
CREATE TABLE IF NOT EXISTS communication_inbound_checkpoint (
    id                   INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    committed_update_id  BIGINT NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unresolved callback queries held for operator review.
CREATE TABLE IF NOT EXISTS communication_inbound_quarantine (
    quarantine_id        BIGSERIAL PRIMARY KEY,
    update_id            BIGINT NOT NULL,
    reason               TEXT NOT NULL,
    callback_query_id    TEXT,
    provider_coordinates JSONB NOT NULL DEFAULT '{}'::jsonb,
    quarantined_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved             BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at          TIMESTAMPTZ,
    resolution_note      TEXT,
    CONSTRAINT communication_inbound_quarantine_update_uq UNIQUE (update_id)
);

CREATE INDEX IF NOT EXISTS communication_inbound_quarantine_pending_idx
    ON communication_inbound_quarantine (resolved, quarantined_at ASC)
    WHERE resolved = FALSE;
