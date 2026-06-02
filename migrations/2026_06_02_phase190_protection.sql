-- Phase 190 — Durable protection guardrails (paper trading).
-- Idempotent. Safe to re-run. Applied 2026-06-02.

-- 190B: protection metadata columns on paper_trades
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_verified_source text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS broker_stop_status text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS current_stop numeric;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_type text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS take_profit_order_id text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS profit_protection_status text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS trailing_active boolean;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS trailing_policy_version text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS protection_status text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS protection_defect_reason text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS last_broker_protection_check_at timestamptz;

-- 190E: extend Hermes finding taxonomy with protection defect types
ALTER TABLE hermes_validation_findings DROP CONSTRAINT IF EXISTS hermes_validation_findings_finding_type_check;
ALTER TABLE hermes_validation_findings ADD CONSTRAINT hermes_validation_findings_finding_type_check
  CHECK (finding_type = ANY (ARRAY[
    'stale_data','conflicting_agents','weak_evidence','scoring_inconsistency','missing_source_link',
    'stale_proposal','outdated_rag','unsupported_thesis','broken_pipeline','missing_data',
    'hallucination_risk','confidence_drift',
    -- Phase 190E protection defects:
    'open_position_no_broker_stop','broker_stop_exists_db_untracked','large_gain_no_take_profit',
    'stop_note_unverified','protection_metadata_mismatch','stale_quote_blocking_protection_review'
  ]));

-- 190E: Hermes safe view exposing open-position protection state
CREATE OR REPLACE VIEW hermes_v_open_position_protection_context AS
SELECT
  pt.id                         AS paper_trade_id,
  pt.symbol,
  pt.strategy_id                AS strategy,
  pt.shares                     AS qty,
  pt.entry_price,
  pt.current_price,
  pt.unrealized_pnl,
  pt.planned_stop,
  pt.stop_loss,
  pt.stop_order_id              AS broker_stop_order_id,
  pt.stop_verified_at,
  pt.broker_stop_status,
  pt.take_profit_order_id,
  pt.take_profit_price,
  COALESCE(pt.trailing_active,false) AS trailing_active,
  COALESCE(pt.protection_status,
    CASE WHEN pt.stop_order_id IS NOT NULL THEN 'PROTECTED_TRACKED'
         WHEN pt.stop_loss IS NOT NULL THEN 'PROTECTED_UNRECORDED'
         ELSE 'NAKED' END)      AS protection_status,
  pt.protection_defect_reason,
  pt.last_broker_protection_check_at
FROM paper_trades pt
WHERE pt.status = 'open';
