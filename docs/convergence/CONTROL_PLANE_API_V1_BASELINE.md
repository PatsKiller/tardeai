# CONTROL_PLANE_API_V1_BASELINE

**R21_BASELINE_ACCEPTED=true**

Frozen HTTP consumption contract for R22–R24.

| Field | Value |
|---|---|
| Freeze name | `CONTROL_PLANE_API_V1_BASELINE` |
| Baseline commit | `084674c560abd7bb910726f62e41508703c07e40` |
| Integrator branch | `convergence/r20-r24` |
| Methods | GET only |
| Mutation | POST/PUT/PATCH/DELETE → HTTP 405 |
| Envelope key for payload | `data` (not `payload`) |
| Authority | READ_ONLY_ADVISORY |
| MEMORY_BEHAVIOR_INFLUENCE | 0 |

This freeze **supersedes ControlPlane@v1.0.0 as the HTTP envelope** that UI streams consume.
ControlPlane@v1.0.0 remains the **field vocabulary** (RuntimeStatus, EvidenceClass, lineage node names).
It is not the HTTP response shape.

Do not casually rename routes or envelope keys while R22–R24 consume this freeze.
R21.1 (detail / lineage / extra proof) must be additive and backward-compatible unless a
formal contract change is logged.

## Envelope (every summary response)

```
ok: boolean
as_of: ISO-8601 string
source_sha: string | null
freshness: string          # 084674c5 emits CURRENT_SMOKE
data_quality: string
evidence_class: string
data: object
```

`ok` is false only when `data_quality` is `BROKEN` or `INVALID_SCHEMA`.
`UNAVAILABLE` still has `ok: true` and HTTP 200. Pages must read `data_quality`, not `ok`.

## Collection `data` (all summary routes except `/system`)

```
items: object[]
pagination: { limit, offset, total }
```

`limit` is bounded 1..200 (default 50). `offset` >= 0.

## `/system` `data`

```
authority: READ_ONLY_ADVISORY
memory_behavior_influence: 0
runtime: { source_sha, state, persistent_state }
services: []
timers: []
workers: []
queues: []
research: { state }
notifications: { state }
```

084674c5 `_system()` currently projects `state=UNKNOWN`. That is **not** LIVE.
R21 admin visibility ≠ R20 specialist-office activation.

## Summary routes (frozen)

- GET `/api/v3/control-plane/system`
- GET `/api/v3/control-plane/agents`
- GET `/api/v3/control-plane/workflows`
- GET `/api/v3/control-plane/research`
- GET `/api/v3/control-plane/stores`
- GET `/api/v3/control-plane/identity`
- GET `/api/v3/control-plane/notifications`
- GET `/api/v3/control-plane/learning`
- GET `/api/v3/control-plane/maturity`
- GET `/api/v3/control-plane/audit`

## Degradation (render honestly; do not invent rows)

| data_quality | meaning |
|---|---|
| AVAILABLE | projection succeeded; items may still be empty (`EMPTY_VALID` = AVAILABLE + total=0) |
| UNAVAILABLE | canonical store missing |
| INVALID_SCHEMA | store present but not JSON / not a row list |
| STALE / DEGRADED | pass through if a store emits them; do not synthesize |
| BROKEN | envelope `ok=false` |
| NO_RELEVANT_EVENTS | unknown route or no matching id (R21.1 detail) |

Frontend must not infer RuntimeStatus, LIVE, materiality, notification class, or maturity.

## Canonical stores (084674c5 readers)

| Route | File under `data/runtime/` |
|---|---|
| agents | `agent_registry.json` |
| workflows | `workflow_traces.json` |
| research | `research_attention.json` |
| identity | `identity_registry.json` |
| notifications | `notification_receipts.json` |
| learning | `learning_evidence.json` |
| maturity | `maturity.json` |
| audit | `audit_capability_claims.json` |
| stores | `canonical_store_registry.json` then `store_registry.json` |

Missing file → UNAVAILABLE. That is legitimate, not a bug to paper over with populated mocks.

## R21.1 (pending Codex handoff; local preview exists)

Additive only. Not part of this freeze:

- GET `/api/v3/control-plane/agents/{id}`
- GET `/api/v3/control-plane/workflows/{id}`
- canonical lineage adapter / cross-id lookup

Local integrator preview: `c3b105a7` on this branch. R22 must keep labeled detail/trace
fixtures until Codex R21.1 is formally accepted.

## Coexisting artifacts

- Vocabulary: `ControlPlane@v1.0.0` in `schemas/control_plane/v1.0.0/`
- HTTP freeze: this document + `fixtures/control_plane/api_v1_baseline/`
- Implementation: `scripts/control_plane_api.py` @ 084674c5 (summary) + later additive commits

## Machine snapshot

`docs/convergence/CONTROL_PLANE_API_V1_BASELINE.json`
`fixtures/control_plane/api_v1_baseline/SCHEMA.json`
