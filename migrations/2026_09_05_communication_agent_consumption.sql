-- Trade AI Communications Gateway — AgentConsumptionReceipt@v1 + subscriptions.
-- Persistent agents (CIO, Hermes, Advisory, Darwin, Maria, …) subscribe via
-- contracts, acknowledge consumption, and declare influence lineage.
-- Agents must NOT self-certify institutional truth (no ACCEPTED writes).
-- Additive only. Does not modify broker/order/2FA/guardrail or librarian tables.

CREATE TABLE IF NOT EXISTS communication_agent_subscriptions (
    subscription_id       TEXT PRIMARY KEY,
    agent_id              TEXT NOT NULL,
    agent_version         TEXT NOT NULL,
    filter                JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- filter keys: message_classes[], severities[], subject_domains[]
    enabled               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS communication_agent_subscriptions_agent_idx
    ON communication_agent_subscriptions (agent_id, enabled, created_at DESC);

CREATE TABLE IF NOT EXISTS communication_agent_consumption_receipts (
    receipt_id              TEXT PRIMARY KEY,
    agent_id                TEXT NOT NULL,
    agent_version           TEXT,
    event_id                TEXT NOT NULL,
    thread_id               TEXT,
    artifact_ids            JSONB NOT NULL DEFAULT '[]'::jsonb,
    purpose                 TEXT NOT NULL,
    policy_decision         TEXT,
    retrieved_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at         TIMESTAMPTZ,
    derived_artifact_ids    JSONB NOT NULL DEFAULT '[]'::jsonb,
    influence_declaration   TEXT,
    influence_event_ids     JSONB NOT NULL DEFAULT '[]'::jsonb,
    schema_version          TEXT NOT NULL DEFAULT 'AgentConsumptionReceipt@v1',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Soft uniqueness: one receipt purpose per agent+event (optional guard).
CREATE UNIQUE INDEX IF NOT EXISTS communication_agent_consumption_receipts_agent_event_purpose_uq
    ON communication_agent_consumption_receipts (agent_id, event_id, purpose);

CREATE INDEX IF NOT EXISTS communication_agent_consumption_receipts_agent_idx
    ON communication_agent_consumption_receipts (agent_id, retrieved_at DESC);
CREATE INDEX IF NOT EXISTS communication_agent_consumption_receipts_event_idx
    ON communication_agent_consumption_receipts (event_id, retrieved_at DESC);
