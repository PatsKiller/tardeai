# R20 Data-Plane V2 — shared integrator contract

Baseline: `cc55cf64baa6eb7a616a458f0c840d6302382ede`
Authority: `READ_ONLY_ADVISORY`. MBI=0. No broker/order/stop/risk/2FA. Never mint security_guid from ticker.

This is a functional repair spec, not a docs-only release. Implementers must land code+tests.

## Envelope (Lane A)

Schema `CIOWorkflowEnvelope@v1`. Persist as JSONL records with `record_type=envelope` in `data/cio/cio_workflow_lineage.jsonl` (same file as nodes/edges). Upsert by `workflow_id` (rewrite by appending a newer envelope; readers take latest per workflow_id).

Required keys (nullable allowed; missing stage uses `stage_status`):

- workflow_id, subject_id, entity_type, subject_guid
- event_id, context_id
- research_request_id, research_artifact_id
- specialist_dispatch_id, specialist_artifact_id
- cio_generation_id
- notification_id, notification_classification, suppression_reason
- checkpoint_id
- created_at, updated_at, source_sha
- authority, memory_behavior_influence, schema
- stage_status: map of research/specialist/cio/notification/checkpoint →
  `NOT_REQUIRED | SUPPRESSED | UNAVAILABLE | FAILED | NOT_YET_CREATED | COMPLETED`

Notification classification values: `IMMEDIATE | DIGEST | COMMAND_CENTER_ONLY | SUPPRESSED | NOT_REQUIRED | FAILED`

CIO skip reasons: `NON_MATERIAL | NO_CIO_REQUIRED | UPSTREAM_UNAVAILABLE`

## Checkpoint (Lane A)

Do **not** invent a second checkpoint schema. Use `OutcomeCheckpoint@v1` via
`scripts.lib.cio_institutional_learning.persist_checkpoint` / `r17_checkpoint_binding.enrich_checkpoint`.

Required fields (existing contract + workflow link):

schema, checkpoint_id, decision_id, horizon, due_at, status, duplicate,
observational_only, trading, authority, memory_behavior_influence,
subject_guid, entity_type, subject_id, lineage_id, decision_generation,
semantic_key, runtime_source_sha, context_receipt, original_decision_state,
created_at, workflow_id, notification_id (nullable)

Idempotent on semantic_key (same generation + horizon → wrote=false).

Lineage `LineageStore.checkpoint` may still add a graph NODE pointing at the
**same** OutcomeCheckpoint checkpoint_id. It must not mint a competing `cp_*`
identity when an OutcomeCheckpoint id exists.

Default lineage path must resolve through `production_state_root()`, not only code ROOT.

## Control plane (Lane B)

Every domain goes through one registry map `CONTROL_PLANE_DOMAINS`.
No endpoint may use a bare filename that is not in that map.

First-AVAILABLE must **not** accept an unrelated JSONL of dicts.

Row extraction:

1. JSON list of dicts → rows
2. dict.items/rows/data list → rows
3. dict.by_research_id values → rows (research projection)
4. dict wrapping a domain object (maturity/audit) → single-item list
5. agent_run_traces jsonl → unique agents `{agent_id, role, last_wake, runtime_state}`

If a path exists but shape is unusable, **skip to next path** (do not AVAILABLE empty).
If a path exists, valid, and zero rows → AVAILABLE total=0.
If no usable path → UNAVAILABLE.

Workflows primary: `cio.workflow_lineage` only. Never `cio.operator_product.history`.

Notifications primary: `notifications.audit` = `data/cio/cio_notification_audit.jsonl`
(alias outbox).

Register missing stores: cio.agent_traces, identity.registry, runtime.maturity,
runtime.audit_claims, research.hermes_requests, notifications.audit.

## Hermes (Lane C)

New helper `scripts/lib/hermes_runtime_status.py` classifying:

ON_DEMAND_READY, ON_DEMAND_RUNNING, EVENT_DRIVEN_IDLE, QUEUE_WAITING,
QUEUE_ACTIVE, SCHEDULED, EXPECTED_IDLE, DEGRADED, FAILED, DISABLED, UNKNOWN

oneshot + pending=0 + no worker → EXPECTED_IDLE (not FAILED, not BROKEN).
pending>0 + no worker → QUEUE_WAITING.
worker running → QUEUE_ACTIVE or ON_DEMAND_RUNNING.

`control_plane_api._system()` must use this classifier. Empty queue ≠ unhealthy.

## Notification idempotency (Lane C)

`notification_id` must be deterministic for (lineage, material_generation_id, class).
Do not hash wall-clock into the id.

`NotificationStateStore.record` must not append a new audit row when the latest
row for that lineage already has the same notification_id / material_generation_id
and class (including SUPPRESSED).

## Tests required

- same workflow twice, same CIO generation twice, same notify twice, changed generation
- 100 identical replays: 0 extra workflows/research/CIO gens/notifications/checkpoints
- skip path: NO_CIO_REQUIRED, SUPPRESSED, checkpoint per business rules
- full chain persist+reload complete_to_checkpoint=true
- CP domain registry coverage
- source precedence (canonical production over retired watchlist / missing fixture)
- Hermes EXPECTED_IDLE vs FAILED
- frontend unchanged except compatibility
