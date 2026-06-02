-- Phase 192 — operator-approved paper protection adjustment proposals. Idempotent. 2026-06-02.
-- Advisory/proposal store; execution is guarded + operator-confirmed only.

CREATE TABLE IF NOT EXISTS paper_protection_adjustment_proposals (
    id bigserial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    trade_id bigint, symbol text, action text,
    current_stop numeric, proposed_stop numeric,
    current_take_profit numeric, proposed_take_profit numeric,
    current_risk numeric, proposed_risk numeric,
    profit_locked_before numeric, profit_locked_after numeric,
    giveback_before numeric, giveback_after numeric,
    downside_protection_improvement numeric, upside_limitation text,
    tradeai_reason text, hermes_reason text, evidence_refs jsonb,
    quote_timestamp text, quote_price numeric,
    requires_operator_approval boolean DEFAULT true,
    no_live_execution boolean DEFAULT true,
    alpaca_supported boolean, expected_api text,
    status text DEFAULT 'PROPOSED', expires_at timestamptz
);
