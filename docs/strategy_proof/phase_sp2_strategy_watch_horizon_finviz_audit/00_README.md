# SP-2 — Strategy Watch Horizon and Finviz Screener Audit

**Status:** COMPLETE

## Purpose

Read-only strategy watch-horizon governance and Finviz screener quality auditing.
Proves whether the upstream pipeline (screeners, incubator, strategy routing) is
intelligently selecting and watching the right tickers.

## Scripts Created

- `scripts/strategy_watch_horizon_policy.py` — Pure function watch horizon policy
  (23 strategies, min/max days, required confirmations)
- `scripts/report_strategy_watch_horizon.py` — Candidate maturity state report
- `scripts/report_finviz_screener_quality.py` — Screener quality audit
- `scripts/report_strategy_assignment_engine_audit.py` — Strategy assignment engine audit

## Key Findings

### Watch Horizon
- 1,139 incubator candidates across 12 strategies
- Most candidates are in "observing" state (within watch window)
- momentum_scalp: 28 expired candidates exceeding 2-day max horizon
- 15 momentum_scalp + 113 "screener" candidates have insufficient data

### Screener Quality
- 18 screeners configured, all enabled
- screener_run_health uses different naming than screener_config — cross-reference needed
- No screeners clearly broken, but conversion data insufficient for quality grading

### Assignment Engine
- 74/83 proposals (89%) missing route audit (strategy_setup_matches)
- 6 proposals assigned "screener" as strategy (not a valid YAML strategy)
- 9 proposals have YAML/DB config hash drift
- 13 strategies never selected despite having YAML configs
- Quality: **missing_route_audit**

## Safety

- All read-only. No mutations, no screener changes, no YAML changes.
- All recommendations human_review_only.
- Tests: 16/16 pass, SP-1 regression 13/13 pass.
