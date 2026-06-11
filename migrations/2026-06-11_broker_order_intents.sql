-- Canonical order-intent persistence + append-only audit (ADR-B2). No execution columns by design.
CREATE TABLE IF NOT EXISTS broker_order_intents (
    intent_id UUID PRIMARY KEY,
    correlation_id UUID NOT NULL,
    broker TEXT NOT NULL,
    account_key TEXT,
    symbol TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'DRAFT',
    intent_json JSONB NOT NULL,         -- original product-level intent (canonical form)
    validation_json JSONB,              -- errors/warnings at last validation
    translation_json JSONB,             -- exact broker payload(s) that WOULD be sent
    capability_json JSONB,              -- capability annotations (native/composed/degraded/blocked)
    blocked_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_boi_broker_state ON broker_order_intents (broker, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS intent_state_events (
    id BIGSERIAL PRIMARY KEY,
    intent_id UUID NOT NULL,
    correlation_id UUID NOT NULL,
    event TEXT NOT NULL,                -- state:X | guard:action:ALLOW|BLOCK:MODE
    detail TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ise_intent ON intent_state_events (intent_id, created_at);
