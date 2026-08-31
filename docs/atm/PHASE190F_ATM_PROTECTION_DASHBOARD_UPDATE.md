# PHASE 190F — ATM Protection Dashboard Update

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**File:** `scripts/api_v2.py` (additive route + handler) · Alpaca paper only

---

## Endpoint added (read-only)
`GET /api/v2/atm/protection-coverage` → `_atm_protection_coverage()`. Additive entry in the
`ROUTES` dict; does not alter existing routes. Sources the broker-verified
`hermes_v_open_position_protection_context` view (paper_trades), **not** brokerage JSON.

### Response contract
```json
{
  "total_open_positions": 6,
  "protected_at_broker": 6,
  "db_tracked_stops": 6,
  "untracked_broker_stops": 0,
  "no_broker_stop": 0,
  "take_profit_missing": 6,
  "large_gain_no_profit_protection": 1,
  "trailing_active": 0,
  "last_protection_verification": "<timestamp>",
  "defects_by_symbol": [{"symbol": "ANY", "defect": "large_gain_no_take_profit", "pnl": 535.4}],
  "operator_action_required": true
}
```
Validated against the live view (standalone mirror): 6 total / 6 protected / 6 db-tracked / 0
untracked / 0 naked / 6 tp-missing / operator_action_required=true. `ast.parse` clean.

## Activation
The route is live **on next API restart** of the `:7777` service. I did **not** restart the
running production API (outward-facing/disruptive — requires operator OK). To activate:
restart the api_v2 service, then the ATM/Paper Trading dashboard can fetch the endpoint.

## Dashboard panel spec (UI — to render on next frontend build)
A "Protection Coverage" card on the ATM/Automated-Trading page:
- Headline counts: total open · protected-at-broker · DB-tracked · **untracked** (amber) ·
  **naked** (red) · take-profit-missing · large-gain-no-protection · trailing-active.
- "Last verified" timestamp (from `last_protection_verification`).
- Defects-by-symbol list (each row clickable → trade drilldown).
- "Operator action required" banner when `operator_action_required=true`.

Color rule: naked>0 → red; untracked>0 or large_gain_no_pp>0 → amber; else green. This makes the
exact defect that hid for days (untracked stops, big winners without TP) impossible to miss.
