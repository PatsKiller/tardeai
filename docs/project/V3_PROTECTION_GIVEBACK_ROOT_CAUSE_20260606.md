# V3 Protection Give-Back — Root Cause (2026-06-06)

**Status:** Root cause established. Analytics/advisory only — no trading behavior changed.

## 1. Crawler finding

The v3 Journal Playwright audit rendered cleanly but surfaced a real investment-process failure in
the Protection tab: a high share of winners gave back profit, the operator acted on almost none of
them, and initial inspection showed most measurable winners carried `baseline_no_advisory` — i.e.
no profit-protection advisory was ever generated.

This is **not a UI bug**. It is a protection-intelligence coverage gap.

## 2. Canonical (honest) numbers

Measured from the canonical `trade_instances` all-trades layer (not paper-only):

| Metric | Value |
|--------|-------|
| Closed trades (all sources) | 196 |
| Measurable closed (bar-based MFE) | 34 |
| Winners | 130 |
| Winners with bar MFE (measurable) | 13 |
| Winners that gave back profit | 9 |
| Money left on the table (measurable winners) | **$1,239.29** |
| Winners with an advisory | 2 |
| Winners with operator action | 0 |
| Protection-missed (protectable, no/late advisory) | 5 |

> The earlier crawler snapshot ("28/28", "$2,938") came from a broader/looser measurability bar in
> `protection_advisory_outcomes`. The canonical layer scores give-back **only** where bar-based MFE
> exists (no fabrication), which yields the honest 13 measurable winners / 9 give-backs above.

Failure-class distribution (all 196 closed):
`DATA_INCOMPLETE 117` · `NOT_PROTECTABLE 74` · `NO_ADVISORY_GENERATED 5`.

## 3. Exact reason advisories were missing (the `baseline_no_advisory` cause)

The existing advisory engine (`scripts/profit_protection_advisory.py`) has three structural limits:

1. **Open-trade-only scope.** It runs `SELECT ... FROM paper_trades WHERE status='open'`. It never
   evaluates a trade once it has closed, so a closed winner only ever had an advisory if it was
   caught *while open* during a protectable-profit window with a fresh quote.
2. **Paper-only.** Advisories key to `paper_trade_id`; MFE analysis exists only for `paper_trades`.
   All **117 imported Schwab/Fidelity winners** are excluded entirely (no MFE, no advisory).
3. **Late start + thresholds.** The engine began emitting advisories at **2026-06-02 10:51**, with a
   ≥3% gain review threshold and a 30-minute quote-freshness gate.

Diagnostic (`diagnose_profit_protection_advisory_gaps.py`) over the 9 measurable give-back winners:

| Primary root cause | Trades | $ left |
|--------------------|--------|--------|
| `CLOSED_BEFORE_ENGINE` (closed before 2026-06-02) | 7 | $1,136.74 |
| `OPERATOR_ACTION_GAP` (advisory existed, ignored) | 2 | $102.55 |
| `PAPER_ONLY_EXCLUSION` (Schwab/Fidelity winners, total) | 117 | not bar-measurable |

The winning paper trades closed **2026-05-12 → 2026-06-03**; the engine did not exist for most of
that window. So `baseline_no_advisory` is overwhelmingly "closed before the engine existed," with a
secondary "operator did not act," and a whole population of imported winners the engine cannot see.

## 4. Architecture facts confirmed

- **Advisory source tables:** `atm_profit_protection_advisories` (keyed `paper_trade_id`),
  reconciled into `protection_advisory_outcomes` (keyed `trade_id` = paper trade id).
- **Paper-only / open-trade-only assumptions:** both confirmed in `profit_protection_advisory.py`.
- **Closed-trade learning tables:** `protection_advisory_outcomes`, `trade_mfe_analysis`
  (bar-based MFE/MAE, paper only), `trade_edge_comparison`.
- **Give-back is measured** in `trade_mfe_analysis.money_left` (authoritative $, paper only).
- **Canonical `trade_instance_id`** was **absent** from the protection path — advisories and
  outcomes keyed to `paper_trade_id`, never to `trade_instances.id`.
- **No threshold/backtest feedback loop** existed — thresholds were static and never tested against
  closed-trade outcomes.

## 5. Remediation (advisory/shadow only)

The fix is the canonical all-trades profit-capture layer (Phase 206) documented in
`V3_PROTECTION_PROFIT_CAPTURE_ENHANCEMENT_20260606.md`: a canonical analysis table keyed to
`trade_instance_id`, an advisory gap diagnostic, an evidence-only rule backtest, shadow threshold
recommendations (never grafted), an additively-enriched open-trade advisory engine, and a rebuilt
v3 Protection tab. **No broker writes, no order/stop/proposal/GO-WAIT/strategy mutation.**

## 6. Safety proof

`.env`: `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, no `LIVE_TRADING`. The running
Hermes drain was left untouched (read status only). `validate_profit_protection_enhancement.py`
asserts no broker/order/GO-WAIT/strategy mutation in any new/modified script — **10/10 PASS**.
