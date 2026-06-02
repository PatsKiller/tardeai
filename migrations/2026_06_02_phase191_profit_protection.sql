-- Phase 191 — ATM profit-protection advisory intelligence. Idempotent. Applied 2026-06-02.
-- Advisory only: no stop/order mutation anywhere.

-- 191B/D: advisory store (TradeAI action + Hermes opinion + audit per open trade)
CREATE TABLE IF NOT EXISTS atm_profit_protection_advisories (
    id bigserial PRIMARY KEY,
    paper_trade_id bigint NOT NULL,
    symbol text,
    created_at timestamptz DEFAULT now(),
    data_state text,
    tradeai_action text,
    tradeai_reason text,
    supporting_actions jsonb,
    audit_json jsonb,
    hermes_opinion text,
    hermes_reason text,
    operator_action_required boolean
);

-- 191E: extend Hermes finding taxonomy with profit-protection second-opinion types
ALTER TABLE hermes_validation_findings DROP CONSTRAINT IF EXISTS hermes_validation_findings_finding_type_check;
ALTER TABLE hermes_validation_findings ADD CONSTRAINT hermes_validation_findings_finding_type_check
  CHECK (finding_type = ANY (ARRAY[
    'stale_data','conflicting_agents','weak_evidence','scoring_inconsistency','missing_source_link',
    'stale_proposal','outdated_rag','unsupported_thesis','broken_pipeline','missing_data',
    'hallucination_risk','confidence_drift',
    -- Phase 190E protection defects:
    'open_position_no_broker_stop','broker_stop_exists_db_untracked','large_gain_no_take_profit',
    'stop_note_unverified','protection_metadata_mismatch','stale_quote_blocking_protection_review',
    -- Phase 191E profit-protection second-opinion:
    'large_gain_loose_stop','profit_giveback_too_high','trailing_policy_not_triggered_but_review_needed',
    'stop_only_breakeven_on_large_gain','strategy_metadata_missing_cannot_advise'
  ]));
