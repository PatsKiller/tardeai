# PHASE 191F — Inline ATM/Open-Trade Profit-Protection Panel

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Endpoint:** `GET /api/v2/atm/profit-protection-advisory` (`api_v2.py` → `_atm_profit_protection_advisory()`,
additive route). **Read-only / advisory-only.** Live on next `tradeai-portfolio-server` restart.

---

## Data contract (per open trade)
```json
{
  "trade_id": 48, "symbol": "ANY", "as_of": "...", "data_state": "STRATEGY_METADATA_MISSING",
  "tradeai": {
    "action": "URGENT_PROTECTION_REVIEW", "reason": "Large gain $402 (20.1%) ...",
    "supporting": ["TAKE_PROFIT_ADVISORY","LOCK_PROFIT_ADVISORY"],
    "unrealized_pnl": 402.35, "unrealized_pct": 20.12, "current_broker_stop": 3.07,
    "stop_locks_profit": false, "profit_locked_usd": 0.0, "giveback_to_stop_usd": ...,
    "take_profit_exists": false, "trailing_threshold_met": false
  },
  "hermes": {"opinion": "caution", "reason": "Strategy/risk metadata missing ..."},
  "operator_action_required": true,
  "decision_support": ["Keep current stop","Move to breakeven review","Lock profit review",
                       "Convert to trailing review","Add take-profit review","Needs more data"]
}
```

## Panel layout (renders on next frontend build)
Per open-trade entry on the ATM / Automated-Trading page:

**TradeAI Protection View** — current P&L, stop status (locks profit?), profit locked, giveback
risk, take-profit status, trailing status, **recommended action** (color by severity:
URGENT→red, LOCK/TAKE_PROFIT/MOVE_BREAKEVEN→amber, NO_ACTION→green).

**Hermes Second Opinion** — agree / caution / needs-evidence, risk warning, missing evidence,
alternative recommendation.

**Decision support (advisory-only buttons):** Keep current stop · Move to breakeven review · Lock
profit review · Convert to trailing review · Add take-profit review · Needs more data.

## Execution gating
Buttons are **read-only/advisory** in this phase. Any button that would modify an Alpaca paper
order is deferred to **Phase 192 — operator-approved paper stop/take-profit adjustment workflow**
(explicit operator click → propose → confirm → modify paper order). No mutation here.

## Validation
Endpoint query (`DISTINCT ON (paper_trade_id) ... ORDER BY created_at DESC`) returns the latest
advisory per trade; validated against the persisted table (ANY=URGENT, SNOW=TAKE_PROFIT, 4×NO_ACTION).
`ast.parse` clean.
