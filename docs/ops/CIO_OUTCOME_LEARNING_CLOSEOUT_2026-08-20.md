# CIO Outcome Learning — Phase D thin closeout (2026-08-20)

**Authority:** READ_ONLY_ADVISORY · **MBI remains 0** · `eligible_runs` remains 0 until proven under gate.

## Shipped

- `scripts/lib/cio_outcome_observer.py` — disposition → `cio_outcomes.jsonl` + maturity projection
- Hook on `POST /api/v3/cio/decision/{id}/disposition` (fail-soft)
- `GET /api/v3/maturity/learning` includes `disposition_outcomes` block
- Unit tests: mature on done/ack; defer not immediate mature

## Honest residual

- Historical matured count was ~0; this starts the observer, does not invent past outcomes.
- Memory admission from research and influence gates remain separate; do not claim learning improves advice until `eligible_runs > 0`.
- Reflection timers / advisory scorers already exist; this path only closes disposition → matured visibility.

## LIVE HOST PROOF (2026-08-20)

| Field | Value |
|---|---|
| done | `plan_43043a4ccdbe` → event `3fc87660-fc53-4925-b2ad-5641d101e90f` matured=true · lineage `lin_4c9d72b25d58f05a6170` |
| ack | `plan_3d8d79ca5ec8` → event `2d16aef8-7973-42eb-b57d-5c552ff37556` matured=true |
| defer control | matured=false (expected) |
| GET /api/v3/maturity/learning | `disposition_outcomes.matured_count=2` · `eligible_runs=0` · **MBI=0** |

Residual #4 visibility **CLOSED** (count > 0). Influence still gated.

