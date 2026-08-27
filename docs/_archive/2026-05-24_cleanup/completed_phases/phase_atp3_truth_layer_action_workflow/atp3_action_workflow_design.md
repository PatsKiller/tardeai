# ATP-3 — Action Workflow Design

## Operator Action Order

1. **Refresh Quote** — Get fresh execution-eligible price
2. **Check Execution** — Validate bid/ask/spread/session/broker readiness
3. **Run Strategy Fit** — Confirm strategy match still valid
4. **Run Technical Snapshot** — EMA alignment, Fib levels, support/resistance
5. **Validate Catalyst Quality** — Verify catalyst is real and current
6. **Run AI Review** — LLM analysis of setup quality
7. **Run Backtest/Context** — Historical pattern validation
8. **Revalidate Proposal** — Confirm all gates pass
9. **Approve Paper Test** — Only if ALL hard gates pass
10. **Rebuild or Expire** — If stale, invalid, or gates permanently fail

## Hard Gates (must pass for approval)

- Quote checked: execution-eligible, not stale
- Execution readiness: bid/ask/spread/session validated
- R:R >= 2.0
- Stop not breached
- Price within entry zone
- Strategy fit valid

## Soft Gates (recommended but not blocking)

- AI review completed
- Backtest run
- Technical snapshot recent
- Catalyst verified
