-- Trade AI Communications Gateway — ChannelDelivery@v1 ledger.
-- Additive only. Does not modify broker/order/2FA/guardrail tables.
-- SHADOW / Phase 3: records delivery attempts; does NOT own provider egress.
-- Telegram is the first channel; other channels use the same row shape.
--
-- Verified: apply/down/apply on isolated Postgres before production.

CREATE TABLE IF NOT EXISTS communication_deliveries (
    delivery_id             TEXT PRIMARY KEY,
    attempt_id              TEXT NOT NULL DEFAULT '1',
    event_id                TEXT NOT NULL REFERENCES communication_events(event_id),
    channel                 TEXT NOT NULL,
    adapter_version         TEXT,
    destination_policy_id   TEXT,
    recipient_set_hash      TEXT,
    render_variant_id       TEXT,
    chunk_count             INTEGER NOT NULL DEFAULT 1,
    part_sequence           INTEGER NOT NULL DEFAULT 0,
    reply_thread_coordinates JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key         TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'RESERVED'
                            CHECK (status IN (
                                'RESERVED', 'SENDING', 'SENT', 'DELIVERED',
                                'ACKNOWLEDGED', 'FAILED', 'BOUNCED', 'SUPPRESSED',
                                'EXPIRED', 'CANCELLED', 'UNKNOWN'
                            )),
    request_fingerprint     TEXT,
    response_fingerprint    TEXT,
    provider_message_id     TEXT,
    provider_coordinates    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_taxonomy          TEXT,
    reserved_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at                 TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    retry_policy            JSONB NOT NULL DEFAULT '{}'::jsonb,
    schema_version          TEXT NOT NULL DEFAULT 'ChannelDelivery@v1',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT communication_deliveries_idempotency_uq UNIQUE (idempotency_key),
    CONSTRAINT communication_deliveries_event_channel_attempt_uq
        UNIQUE (event_id, channel, attempt_id)
);

CREATE INDEX IF NOT EXISTS communication_deliveries_event_idx
    ON communication_deliveries (event_id, reserved_at DESC);
CREATE INDEX IF NOT EXISTS communication_deliveries_status_idx
    ON communication_deliveries (status, reserved_at ASC);
CREATE INDEX IF NOT EXISTS communication_deliveries_channel_idx
    ON communication_deliveries (channel, reserved_at DESC);
CREATE INDEX IF NOT EXISTS communication_deliveries_provider_msg_idx
    ON communication_deliveries (provider_message_id)
    WHERE provider_message_id IS NOT NULL;
