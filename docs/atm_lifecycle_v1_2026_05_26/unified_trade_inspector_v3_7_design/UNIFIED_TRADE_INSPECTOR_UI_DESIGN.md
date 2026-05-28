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
11. Data Quality — missing traces, TCA, stop audit, backtest links
12. Raw — JSON dump of all source data

## Rules
- Read-only
- No trade/broker/mutation buttons
- Safe actions are labels only
- Missing data shows "Unavailable" not blank
