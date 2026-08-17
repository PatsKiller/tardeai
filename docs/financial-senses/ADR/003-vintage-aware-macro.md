# ADR-003 — Vintage-aware macro

**Status:** Accepted

## Context

Historical decisions must be evaluated against what was actually knowable at
decision time, not revised future data.

## Decision

The macro provider always distinguishes `LATEST_REVISED_VALUE` from
`VALUE_AVAILABLE_AS_OF_DECISION_TIME`, and returns `revision_delta` and
`vintage_date`. Historical reads bound the FRED/ALFRED real-time period on BOTH
ends (`realtime_start = decision_date`, `realtime_end = decision_date`) and pin
`observation_end = decision_date` so only observations known as-of the decision
date are returned.

## Consequences

- No future observation leaks backward into a historical decision.
- `macro.compare_vintages` surfaces revision deltas explicitly.
