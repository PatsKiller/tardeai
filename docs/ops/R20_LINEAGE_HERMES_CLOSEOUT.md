# R20 Hermes lineage and queue persistence

Status:      ACTIVE
as_of:       2026-08-26T21:12:25-04:00
Measured at: efcc51365 / not measured

The Hermes request/result lifecycle now emits a durable, append-only lineage projection at
`data/cio/cio_workflow_lineage.jsonl`. Requests, completed results, and checkpoints retain
the existing plan/research/result identifiers and are joined by a deterministic `workflow_id`.
Writes are idempotent by semantic key, so retries and worker restarts cannot duplicate nodes
or edges. The projection is an audit read model; canonical Hermes request/result stores remain
authoritative and no financial or notification authority is introduced.

The queue remains free-first and event/queue/on-demand. This change does not create an always-on
crawler or add paid model calls. Missing specialist, CIO, or notification stages remain explicit
partial lineage rather than fabricated nodes.
