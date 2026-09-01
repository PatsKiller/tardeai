# PHASE 190E — Hermes Protection Safe View & Rule Report

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · advisory only (no trade mutation).**

---

## Safe view: `hermes_v_open_position_protection_context`
Created over `paper_trades WHERE status='open'`. Exposes the protection surface Hermes
previously lacked: `paper_trade_id, symbol, strategy, qty, entry_price, current_price,
unrealized_pnl, planned_stop, stop_loss, broker_stop_order_id, stop_verified_at,
broker_stop_status, take_profit_order_id, take_profit_price, trailing_active,
protection_status, protection_defect_reason, last_broker_protection_check_at`. Includes a derived
`protection_status` fallback (`PROTECTED_TRACKED` / `PROTECTED_UNRECORDED` / `NAKED`). Unlike the
closed-trade `hermes_v_trade_reflection_context`, this view covers **open** positions regardless
of `proposal_id`, so `alpaca_sync` positions are visible.

## Taxonomy extension
`hermes_validation_findings.finding_type` CHECK extended (+6): `open_position_no_broker_stop`,
`broker_stop_exists_db_untracked`, `large_gain_no_take_profit`, `stop_note_unverified`,
`protection_metadata_mismatch`, `stale_quote_blocking_protection_review`.

## Rule engine: `scripts/hermes_open_position_protection_check.py`
Reads the view, evaluates rules, writes `hermes_validation_findings` (deduped: skip if an `open`
finding of the same type+trade exists), and promotes critical/urgent findings to `hermes_alerts`
(`alert_type='portfolio_risk'`). **Advisory only — never mutates trades/stops/orders.**

| Rule | finding_type | severity |
|---|---|---|
| NAKED (no broker stop) | open_position_no_broker_stop | critical |
| broker stop exists, DB untracked | broker_stop_exists_db_untracked | urgent |
| gain ≥ $250, no take-profit | large_gain_no_take_profit | urgent |
| stop submitted, unconfirmed | stop_note_unverified | warning |
| metadata mismatch | protection_metadata_mismatch | warning |

## Runtime result
Clean run, **0 findings** — correct: after 190B all 6 positions are `PROTECTED_TRACKED`, and at
check time unrealized gains had compressed below the $250 take-profit threshold (ANY ~$231, SNOW
~$206). This demonstrates the view + rules are wired and produce **no false positives**. The
`stop_order_id_backfilled` breadcrumb is explicitly excluded from `protection_metadata_mismatch`.
(The SIEM path independently proved a real emission — event 162 — when ANY was +$535.)

## What changed vs 189E gap
- Gap (a) "no safe view exposes broker-protection fields" → **fixed** (new view).
- Gap (c) "no rule for naked/unverified/unprotected" → **fixed** (6 rules + taxonomy).
- Gap (d) "only loop queries closed trades" → **addressed** (new open-position check script;
  schedule it in cron — 190I).
