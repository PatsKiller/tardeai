# v3.3 implementation status

Status: ACTIVE
as_of: 2026-09-27
Authority: READ_ONLY_ADVISORY

This annex records what the canonical architecture v3.3 does not. It does not
replace that document.

## Live and not named in v3.3

- Persistent wake, the CIO event bus, and the wake dispatcher.
- The re-entry decision desk.
- The options pipeline (advisory, Schwab, operator Path B).
- DecisionIntegrity@v1 on the re-entry desk.
- Release-grant binding and the worker-pin check.

## Named in v3.3 and not built

- Observation envelope §5.2.
- RES/RRS scoring and runner promotion §16C.
- Quasi-parallel dashboard switch §16E.
- Feature control / test modal §16I.
- Intelligent sell §16H.6.
- Session envelope §16A.
- `scalp_live_order_intents` §17.
- Embedding migration §10.6.
- Order-flow imbalance §16B.
- `/v3/scalp` (the built route is `/v3/active-trader`).

## Still partial

- Learning loop: beliefs are written; an hourly due record advances by its own
  cadence. A missing cadence is not invented. Outcome validation is not closed.
- Most cron jobs still start in the dev tree. The options reconcile and the
  gate-measurement bridge start in the served release.
- API routes are counted in `data/runtime/route_access_counts.json`. Nothing
  is removed from that count alone.
- Append-only stores are rotated only by `scripts/rotate_append_only_store.py`,
  which keeps the tail and archives the head. It does not run itself.
