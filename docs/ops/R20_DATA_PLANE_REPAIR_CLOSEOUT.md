# R20 Data-Plane Repair Closeout

## Scope

This change reconnects read-only Command Center projections to canonical durable
stores and adds an append-only Hermes workflow lineage projection. It does not
change trading authority, notification policy, or provider spend policy.

## Implemented

- Control-plane readers resolve the configured persistent root through
  `CanonicalStoreRegistry` and support bounded JSON and JSONL projections.
- CIO workflow history reads `data/cio/cio_workflow_lineage.jsonl`; legacy
  `workflow_traces.json` remains a compatibility fallback.
- Watchlist synthesis uses the canonical `data/portfolios/state/watchlist.json`.
- Reconciliation and weekly-learning logical stores are registered with explicit
  schemas and ownership.
- Hermes enqueue and completion append idempotent workflow nodes, edges, and a
  deterministic checkpoint projection. Replays do not duplicate records.
- Hermes queue health is exposed as event-driven/queue state in the system
  projection. No daemon or paid-call policy was introduced.

## Verification

- Control-plane and lineage tests: 13 passed.
- Hermes/research/control-plane regression tests: 38 passed.
- Repository local acceptance: passed (release-equivalent 17/17; all listed
  targeted and regression suites green).

## Runtime status

This is an implementation/integration commit. Production deployment and a
natural operator-requested Hermes run remain separate acceptance steps. Missing
production records continue to be reported as typed unavailable/degraded state;
no synthetic records are created to make a page appear healthy.

## Authority

`READ_ONLY_ADVISORY` remains enforced and `MEMORY_BEHAVIOR_INFLUENCE` remains
zero. The lineage stream is an audit projection only and cannot place orders,
change risk, or mutate broker state.
