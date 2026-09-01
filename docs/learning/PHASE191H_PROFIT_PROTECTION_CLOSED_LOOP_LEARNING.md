# PHASE 191H — Profit-Protection Closed-Loop Learning Integration

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Design + capture schema.** Advisory only; learning feeds journaling/backtesting, not execution.

---

## Goal
When a position closes, evaluate whether the profit-protection advisory was right, whether the
operator acted, and what it cost or saved — so the scoring model and thresholds (191D) improve.

## Capture at close (per trade)
Persisted to `atm_profit_protection_advisories` (advisory rows already store the state) + a close
reconciliation (to add in Phase 192/learning cron):

| Field | Source |
|---|---|
| advisory_existed | was there an advisory row for this trade? |
| advisory_action | last `tradeai_action` before close |
| hermes_opinion | last `hermes_opinion` |
| operator_accepted / ignored | did a Phase 192 action follow the advisory? (null until 192 exists) |
| stop_adjusted_after_advisory | did `stop_order_id`/`current_stop` change after the advisory? |
| gave_back_profit | exit_price vs peak (MFE) — did the trade surrender gains? |
| take_profit_would_have_helped | compare exit vs a TP at advisory time |
| trailing_would_have_helped | simulate trailing from advisory time |
| max_favorable_excursion | `paper_trades.max_favorable_excursion` |
| profit_left_on_table | MFE − realized P&L |
| advisory_accuracy | did the outcome confirm the advisory direction? |

## Feedback loop
1. **Journal:** the Automated Journal shows, on each closed trade, the advisory that existed, whether
   it was acted on, and `profit_left_on_table`.
2. **Backtesting:** replay advisories vs actual exits to measure whether acting on
   `URGENT_PROTECTION_REVIEW` / `LOCK_PROFIT` / `TAKE_PROFIT` would have improved realized P&L.
3. **Threshold tuning:** if winners repeatedly give back > X% after a `REVIEW_STOP` (not urgent),
   lower `GAIN_PCT_LOCK`; if urgent advisories rarely improve outcomes, raise `GIVEBACK_FRACTION_URGENT`.
4. **Model calibration:** track advisory_accuracy by action type; surface in the learning dashboard.

## Wiring (Phase 192 / learning cron)
- On close, a reconciler computes the capture fields above (uses MFE/MAE, exit_reason, advisory
  history) and writes a `profit_protection_outcome` record.
- The learning loop aggregates accuracy by action/strategy and proposes threshold changes
  (advisory; no auto-tuning of GO/WAIT).

This phase ships the **design + capture surface**; the close reconciler is implemented alongside the
Phase 192 operator-approved adjustment workflow so accepted/ignored can be measured.
