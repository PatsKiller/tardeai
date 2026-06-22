#!/usr/bin/env python3
"""Seed percent-of-equity sizing policy for Schwab/Fidelity live accounts when unset.

Recommended defaults (operator-approved 2026-06-22):
  risk_per_trade_pct: 0.5%   (~$356/trade on $71k)
  max_position_allocation_pct: 3%  (~$2,135 position)
  daily_loss_pause_pct: 2%    (~$1,424/day pause)

Idempotent — only fills NULL fields; never overwrites admin edits.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn
from broker_promote_sizing import SCHWAB_LIVE_POLICY_DEFAULTS

SEED = """
UPDATE account_automation_policies p
   SET sizing_engine = COALESCE(NULLIF(p.sizing_engine, ''), %(engine)s),
       risk_per_trade_pct = COALESCE(p.risk_per_trade_pct, %(risk_pct)s),
       max_position_allocation_pct = COALESCE(p.max_position_allocation_pct, %(pos_pct)s),
       daily_loss_pause_pct = COALESCE(p.daily_loss_pause_pct, %(daily_loss_pct)s),
       max_new_positions_per_day = COALESCE(p.max_new_positions_per_day, %(max_new_per_day)s),
       max_concurrent_positions = COALESCE(p.max_concurrent_positions, %(max_concurrent)s),
       updated_by = 'migrate_schwab_live_policies'
  FROM broker_accounts b
 WHERE p.account_id = b.id
   AND (b.account_key ILIKE 'schwab%%' OR b.account_key ILIKE 'fidelity%%')
   AND b.environment != 'paper';
"""


def main():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(SEED, {
        "engine": SCHWAB_LIVE_POLICY_DEFAULTS["sizing_engine"],
        "risk_pct": SCHWAB_LIVE_POLICY_DEFAULTS["risk_per_trade_pct"],
        "pos_pct": SCHWAB_LIVE_POLICY_DEFAULTS["max_position_allocation_pct"],
        "daily_loss_pct": SCHWAB_LIVE_POLICY_DEFAULTS["daily_loss_pause_pct"],
        "max_new_per_day": 3,
        "max_concurrent": 3,
    })
    updated = cur.rowcount
    conn.commit()
    cur.execute("""SELECT b.account_key, p.sizing_engine, p.risk_per_trade_pct,
                          p.max_position_allocation_pct, p.daily_loss_pause_pct
                     FROM account_automation_policies p
                     JOIN broker_accounts b ON b.id = p.account_id
                    WHERE b.account_key ILIKE 'schwab%%' OR b.account_key ILIKE 'fidelity%%'
                    ORDER BY b.account_key""")
    print(f"schwab/fidelity policy seed: {updated} rows touched")
    for r in cur.fetchall():
        print(f"  {r[0]:22} engine={r[1]} risk%={r[2]} pos%={r[3]} daily_pause%={r[4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())