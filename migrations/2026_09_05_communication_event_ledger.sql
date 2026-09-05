-- Trade AI Communications Gateway — CommunicationEvent ledger v1.
-- Additive only. Does not modify broker/order/2FA/guardrail tables.
-- Does NOT own delivery. Gateway mode defaults to OFF; provider calls remain
-- forbidden from this schema alone.
--
-- Verified: apply/down/apply on isolated Postgres before production.

CREATE TABLE IF NOT EXISTS communication_events (
    event_id              TEXT PRIMARY KEY,
    schema_version        TEXT NOT NULL DEFAULT 'CommunicationEvent@v2',
    direction             TEXT NOT NULL CHECK (direction IN ('INBOUND', 'OUTBOUND')),
    event_type            TEXT NOT NULL,
    message_class         TEXT NOT NULL,
    severity              TEXT NOT NULL DEFAULT 'info',
    audience              TEXT NOT NULL DEFAULT 'operator',
    producer              TEXT NOT NULL,
    producer_version      TEXT,
    producer_event_id     TEXT,
    idempotency_key       TEXT NOT NULL,
    subject_key           TEXT NOT NULL,
    thread_id             TEXT,
    correlation_id        TEXT,
    causation_id          TEXT,
    parent_event_id       TEXT,
    reply_to_event_id     TEXT,
    incident_id           TEXT,
    supersedes_event_id   TEXT,
    superseded_by         TEXT,
    version               INTEGER NOT NULL DEFAULT 1,
    entity_refs           JSONB NOT NULL DEFAULT '{}'::jsonb,
    protected_facts       JSONB NOT NULL DEFAULT '{}'::jsonb,
    protected_facts_hash  TEXT NOT NULL,
    authoritative_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    command_center_url    TEXT,
    external_links        JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_classification TEXT NOT NULL DEFAULT 'operational',
    retention_class       TEXT NOT NULL,
    expires_at            TIMESTAMPTZ,
    legal_hold            BOOLEAN NOT NULL DEFAULT FALSE,
    redaction_policy      TEXT,
    curation_mode         TEXT NOT NULL DEFAULT 'DETERMINISTIC'
                          CHECK (curation_mode IN (
                              'DETERMINISTIC', 'TEMPLATE', 'LLM_SUMMARY',
                              'LLM_CHALLENGE', 'LLM_CURATED', 'LLM_DECLINED', 'HUMAN_EDIT'
                          )),
    content_hash          TEXT NOT NULL,
    sanitized_body        TEXT,
    short_summary         TEXT,
    raw_body_ref          TEXT,
    provider_coordinates  JSONB NOT NULL DEFAULT '{}'::jsonb,
    delivery_policy       JSONB NOT NULL DEFAULT '{}'::jsonb,
    knowledge_eligibility TEXT NOT NULL DEFAULT 'ineligible',
    knowledge_status      TEXT NOT NULL DEFAULT 'none',
    build_sha             TEXT,
    release_id            TEXT,
    run_id                TEXT,
    source_system         TEXT,
    source_agent          TEXT,
    source_job            TEXT,
    observed_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    queued_at             TIMESTAMPTZ,
    payload               JSONB NOT NULL DEFAULT '{}'::jsonb,
    gateway_mode_at_write TEXT NOT NULL DEFAULT 'OFF',
    CONSTRAINT communication_events_idempotency_uq UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS communication_events_subject_idx
    ON communication_events (subject_key, created_at DESC);
CREATE INDEX IF NOT EXISTS communication_events_correlation_idx
    ON communication_events (correlation_id, created_at DESC)
    WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS communication_events_incident_idx
    ON communication_events (incident_id, created_at DESC)
    WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS communication_events_producer_idx
    ON communication_events (producer, created_at DESC);
CREATE INDEX IF NOT EXISTS communication_events_type_idx
    ON communication_events (event_type, message_class, created_at DESC);
CREATE INDEX IF NOT EXISTS communication_events_expires_idx
    ON communication_events (expires_at)
    WHERE expires_at IS NOT NULL AND legal_hold = FALSE;

-- Outbox intent rows (delivery ownership comes in later phases; Phase 1 records intent only).
CREATE TABLE IF NOT EXISTS communication_outbox (
    outbox_id             BIGSERIAL PRIMARY KEY,
    event_id              TEXT NOT NULL REFERENCES communication_events(event_id),
    channel               TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'recorded'
                          CHECK (status IN (
                              'recorded', 'reserved', 'sending', 'sent', 'delivered',
                              'acknowledged', 'failed', 'bounced', 'suppressed',
                              'expired', 'cancelled', 'unknown'
                          )),
    destination_policy_id TEXT,
    render_variant_id     TEXT,
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    last_error            TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT communication_outbox_event_channel_uq UNIQUE (event_id, channel)
);

CREATE INDEX IF NOT EXISTS communication_outbox_status_idx
    ON communication_outbox (status, created_at ASC);

CREATE TABLE IF NOT EXISTS communication_entity_links (
    event_id              TEXT NOT NULL REFERENCES communication_events(event_id) ON DELETE CASCADE,
    entity_type           TEXT NOT NULL,
    entity_id             TEXT NOT NULL,
    PRIMARY KEY (event_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS communication_entity_links_entity_idx
    ON communication_entity_links (entity_type, entity_id);
