-- Phase 193 — profit-protection advisory close-loop outcomes. Idempotent. 2026-06-02.
-- Learning telemetry only. No execution, no stop/order mutation.

CREATE TABLE IF NOT EXISTS protection_advisory_outcomes (
    trade_id bigint PRIMARY KEY,
    symbol text,
    reconciled_at timestamptz DEFAULT now(),
    record_kind text,                 -- 'final_closed' | 'interim_open'
    trade_status text,
    -- advisory linkage
    advisory_existed boolean,
    advisory_action text,
    hermes_opinion text,
    operator_action_required boolean,
    -- adjustment linkage
    adjustment_applied boolean,
    adjustment_action text,
    stop_before numeric,
    stop_after numeric,
    operator_decision text,           -- 'accepted' | 'ignored' | 'none'
    -- outcome
    entry_price numeric,
    exit_price numeric,
    current_price numeric,
    realized_pnl numeric,
    realized_pnl_pct numeric,
    unrealized_pnl numeric,
    r_multiple numeric,
    mfe_raw numeric,
    mae_raw numeric,
    profit_locked_by_adjustment numeric,
    giveback_avoided numeric,
    gave_back_profit boolean,
    profit_left_on_table_pct numeric,
    take_profit_would_have_helped boolean,
    trailing_would_have_helped boolean,
    advisory_accuracy text,           -- 'confirmed' | 'contradicted' | 'baseline_no_advisory' | 'in_flight'
    mfe_units_validated boolean,      -- false => MFE units inconsistent, flagged for pipeline review
    notes text
);
