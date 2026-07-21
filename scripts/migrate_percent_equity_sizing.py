#!/usr/bin/env python3
"""Migration: percent-of-equity sizing + admin-configurable policy + unified trade queue + audit.

Additive + idempotent (ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS). Safe to re-run.
Operator 2026-06-19: switch sizing from fixed-dollar caps to percent-of-equity; move all sizing/risk
controls into account_automation_policies (admin-editable); unify automated + manual trades into one
queue; prep Charles Schwab routing; audit every override/approval.

Unit convention: all *_pct columns hold WHOLE percents (5 = 5%, 20 = 20%).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

DDL = """
-- 1) Percent-of-equity policy fields (req 1,2,3,5) ---------------------------------------------------
ALTER TABLE account_automation_policies
  ADD COLUMN IF NOT EXISTS sizing_engine TEXT NOT NULL DEFAULT 'percent_equity';   -- 'percent_equity' | 'fixed_dollar'
ALTER TABLE account_automation_policies
  ADD COLUMN IF NOT EXISTS max_position_allocation_pct NUMERIC;                     -- per-single-position cap (NEW)
ALTER TABLE account_automation_policies
  ADD COLUMN IF NOT EXISTS pct_unit TEXT NOT NULL DEFAULT 'whole_percent';          -- documents 5 = 5%

-- 2) Unified queue + Schwab-routing prep (req 8,9) — extend the existing proposal table ---------------
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS origin TEXT DEFAULT 'auto';            -- auto|manual_web|manual_telegram
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS target_account TEXT;                   -- account_key
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS intended_broker TEXT DEFAULT 'tradeai_automated';
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS routing_state TEXT DEFAULT 'queued';   -- queued|approved|routing|routed|filled|rejected|expired
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS equity_at_proposal NUMERIC;            -- equity snapshot used for sizing
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS sizing_basis JSONB DEFAULT '{}';       -- {engine,risk_pct,pos_pct,risk_cap,size_cap,binding,equity}

CREATE OR REPLACE VIEW unified_trade_queue AS
  SELECT id, symbol, strategy_id,
         COALESCE(origin,'auto') AS origin,
         COALESCE(target_account, 'tradeai_automated') AS target_account,
         COALESCE(intended_broker,'tradeai_automated') AS intended_broker,
         status, COALESCE(routing_state,'queued') AS routing_state,
         proposed_shares, final_shares, sizing_basis, equity_at_proposal,
         created_at, expires_at
  FROM paper_trade_proposals;

-- 3) Override + approval audit (req 10) --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS queue_decision_audit (
  id BIGSERIAL PRIMARY KEY,
  proposal_id BIGINT,
  intent_id   UUID,
  action      TEXT NOT NULL,            -- approve|deny|modify_size|modify_risk|route|policy_edit
  actor       TEXT,                     -- operator / telegram user / 'system'
  channel     TEXT,                     -- web|telegram|system
  before_value JSONB,
  after_value  JSONB,
  reason      TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qda_proposal ON queue_decision_audit(proposal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qda_action   ON queue_decision_audit(action, created_at DESC);
"""

# Seed the paper account onto the percent-of-equity engine with industry-informed defaults.
# Operator 2026-06-19: risk 5% (already set), position cap 20% (≈84 SNOW sh; textbook is 1-2% risk /
# 5-10% position — these are deliberately on the concentrated-active end, tune in the admin modal).
SEED = """
UPDATE account_automation_policies p
   SET sizing_engine = 'percent_equity',
       risk_per_trade_pct = COALESCE(risk_per_trade_pct, 5),
       max_position_allocation_pct = COALESCE(max_position_allocation_pct, 20)
  FROM broker_accounts b
 WHERE p.account_id = b.id AND b.account_key = 'tradeai_automated';
"""


def main():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()
    cur.execute(SEED)
    seeded = cur.rowcount
    conn.commit()
    # report
    cur.execute("""SELECT b.account_key, p.sizing_engine, p.risk_per_trade_pct, p.max_position_allocation_pct,
                          p.max_concurrent_positions
                     FROM account_automation_policies p JOIN broker_accounts b ON b.id=p.account_id
                    ORDER BY b.account_key""")
    print(f"migration applied; paper seed rows: {seeded}")
    for r in cur.fetchall():
        print(f"  {r[0]:20} engine={r[1]} risk%={r[2]} pos%={r[3]} maxconc={r[4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
