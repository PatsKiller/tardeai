# ADR-003 — Vintage-aware macro

**Status:** Accepted

## Context

Historical decisions must be evaluated against what was actually knowable at
decision time, not revised future data.

## Decision

The macro provider always distinguishes `LATEST_REVISED_VALUE` from
`VALUE_AVAILABLE_AS_OF_DECISION_TIME`, and returns `revision_delta` and
`vintage_date`. Historical reads use ALFRED `realtime_end = decision_date`.

## Consequences

- No future observation leaks backward into a historical decision.
- `macro.compare_vintages` surfaces revision deltas explicitly.
