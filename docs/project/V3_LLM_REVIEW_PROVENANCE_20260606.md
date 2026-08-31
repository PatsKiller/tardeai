# v3 LLM-Review Per-Row Provenance (2026-06-06, audit #9)

Status:      ACTIVE
as_of:       2026-06-06T10:54:25-04:00
Measured at: efcc51365 / not measured

## Gap
`trade_llm_reviews` rows mixed simulation, imported-backtest, and paper sources with no visible provenance
or canonical lineage — the operator couldn't tell what each analytic row represented.

## Change (additive, read-only analysis)
- `scripts/backfill_llm_review_provenance.py`: links trade_llm_reviews.trade_instance_id where an EXACT
  key exists (paper review → trade_instance via paper_trade_id). Imported-backtest reviews have NULL
  backtest_trade_id (no exact FK) → left unlinked; simulation rows are backtest sims (no real trade) →
  correctly NULL. Never fabricated.
- `/api/v2/lifecycle/llm-review-status`: adds `provenance` summary {kind: rows, trade_instance_linked}
  and per-row `provenance` (paper|imported_backtest|simulation) + `linked` + `trade_instance_id`.
- v3 LLM Review Coverage tab: latest-reviews table now shows **Provenance** (colored kind badge) +
  **Lineage** (`ti#<id>` when linked, else `sim (no trade)` / `unlinked`), plus a provenance summary line.

## Result
- paper: 4 rows, 4 linked to trade_instance_id (100%)
- imported_backtest: 51 rows, 0 linked (no backtest_trade_id FK — honest)
- simulation: 2050 rows, 0 linked (sim rows; no real trade by design)
Every visible row now states its source kind + canonical link status.

## Safety
ALPACA_MODE=paper, live disabled. Additive link backfill (trade_instance_id from NULL) + read-only
endpoint/UI. No broker/order/proposal/GO-WAIT/strategy/live/Phase-205 changes.
