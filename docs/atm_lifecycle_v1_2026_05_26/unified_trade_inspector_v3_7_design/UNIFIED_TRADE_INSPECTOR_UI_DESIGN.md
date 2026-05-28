# UnifiedTradeInspector.tsx Design

## Trigger
Clickable from any row: "View Lifecycle" button.

## Layout
Full-width slide-out or modal with 12 tabs.

## Tabs
1. Overview — identity, status, P&L, R, account
2. Source — prospect/signal origin, score, grade
3. Proposal — proposal record, gates pass/fail, decision
4. Risk / Approval — gate audit, risk checks, classifier
5. Execution — fill, timing, slippage, order lifecycle
6. Stops — DB stop, broker proof, trailing tier, time-stop, change history
7. Reconciliation — matched/unmatched, journal vs DB
8. Journal — win/loss, exit reason, lesson
9. Learning — strategy performance, calibration
10. Backtest — paper vs simulated comparison
11. LLM Review — close analysis, delayed review, monthly meta-review status
12. Data Quality — missing traces, TCA, stop audit, backtest links, LLM review gaps
13. Raw — JSON dump of all source data

## LLM Review Tab Detail
Shows for this trade:
- Stage 1 close-of-trade analysis: status, model, generated_at, key findings
- Stage 2 delayed post-close review: status, model, generated_at, outcome comparison
- Stage 3 monthly meta-review: status, model, generated_at, pattern/lesson summary
- "Not yet generated" if no analysis exists
- Blocked actions: run model, modify journal, change strategy, place trade

## Rules
- Read-only
- No trade/broker/mutation buttons
- Safe actions are labels only
- Missing data shows "Unavailable" not blank
