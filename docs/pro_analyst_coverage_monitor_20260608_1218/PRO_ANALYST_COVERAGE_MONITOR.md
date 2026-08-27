# Professional Analyst Coverage Monitor (2026-06-08)
Tracks Yahoo analyst coverage of the actionable universe as it expands.

- `scripts/pro_analyst_monitor.py` (daily, appended to the 06:10 pro-analyst chain, read-only): snapshots
  total/with_consensus/coverage_pct + coverage_by_tier + stale/targets_only/divergent + covered_symbols →
  data/runtime/pro_analyst_coverage_history.json (last 90). Diffs vs prior: newly_covered/lost_coverage;
  status EXPANDING / STABLE / REGRESSED.
- Baseline: 121 symbols, 14 with consensus (11.6%); held 29% scalp 5%; 4 targets-only; 0 stale.
- v3: /api/v2/pro-analyst/pills → coverage_health (status + 14-day trend); System→Hermes Professional Analyst
  card shows the coverage-trend line.
- As pro_analyst_fetch (polite, rate-limit-bounded) covers more actionable symbols, with_consensus climbs and
  newly_covered lists the additions — coverage expansion is now visible day over day. Read-only; no scoring change.
