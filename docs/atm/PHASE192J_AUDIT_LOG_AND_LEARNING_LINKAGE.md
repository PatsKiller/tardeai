# PHASE 192J — Audit Log & Journal/Learning Linkage

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**Audit file:** `data/atm/protection_adjustment_audit/<date>_actions.jsonl` (append-only JSONL)

---

## Every decision is audited (dry-run, blocked, or applied)
The engine writes one record per call with:
`action_id, timestamp, operator, proposal_id, trade_id, symbol, action, current_stop,
proposed_stop / proposed_stop_final, current_take_profit/proposed (when applicable), quote_age_min,
quote_price, broker_order_before, broker_order_after, alpaca_response_id, tradeai_recommendation,
hermes_recommendation, operator_reason, status (DRY_RUN_PREVIEW / BLOCKED / APPLIED), advisory_refs,
learning_outcome_tracking_required=true, paper_only=true, live_execution=false`.

## Verified record (today)
```
ppa-20-2026-06-02  DRY_RUN_PREVIEW  live_execution=False
  ANY MOVE_STOP_TO_PROFIT_LOCK  3.07 -> 3.555  lock $0 -> $201  giveback $501 -> $201
  broker_order_before.stop_price=3.07 (unchanged)
```

## Learning linkage (extends Phase 191H)
On close, the reconciler joins the audit log + advisory history + `paper_trades` (MFE/MAE,
exit_reason) to capture:
- advisory existed? operator **accepted / ignored**? (now measurable — the audit log records the
  decision + confirm flag)
- profit locked vs giveback avoided
- profit left on table (MFE − realized)
- did the adjustment help or hurt vs the KEEP baseline?

These feed the journal (per-trade advisory + decision) and backtesting (replay accepted vs ignored
advisories) to calibrate the 191D thresholds. `learning_outcome_tracking_required=true` on every
audited action marks it for the close reconciler.

## Guardrail
Audit is write-only telemetry; it triggers no execution. The only execution path is the guarded
`/approve` endpoint with `confirm=true` on explicit operator action.
