# Control-Plane Contracts v1

Status:      ACTIVE
as_of:       2026-08-26T13:11:11-04:00
Measured at: efcc51365 / not measured

**HTTP freeze (consume this): CONTROL_PLANE_API_V1_BASELINE** (`084674c5`)
See `CONTROL_PLANE_API_V1_BASELINE.md` / `.json`. Envelope key is `data`.

**Field vocabulary (do not infer; render if present): ControlPlane@v1.0.0**
See `docs/convergence/CONTROL_PLANE_CONTRACT_VERSION` and `CONTRACT_CHANGE_LOG.md`.
Machine-readable schema: `schemas/control_plane/v1.0.0/envelope.json`.

The Command Center control plane is a read-only projection of canonical Trade AI state.
Every HTTP response carries `ok`, `as_of`, `source_sha`, `freshness`, `data_quality`,
`evidence_class`, and `data`. API existence is not a LIVE claim.

Core shared concepts:

- `RuntimeStatus`: LIVE_EVENT_DRIVEN, LIVE_SCHEDULED, CALLABLE_ONLY, EXPECTED_IDLE, SHADOW, DISABLED, BROKEN.
- `EvidenceClass`: SOURCE_ONLY, UNIT, INTEGRATION, HISTORICAL_REPLAY, GOLDEN_SHADOW, SHADOW, DRY_RUN, OPERATOR_REQUESTED_LIVE, CURRENT_SMOKE, NATURAL_CURRENT, NATURAL_LONGITUDINAL.
- `WorkflowTrace`: immutable lineage references from source event through entity, research, specialists, CIO product, notification, checkpoint, outcome, and learning.
- `ResearchAttentionStatus`: eligible, due, event-woken, researching, blocked, stale, completed.
- `CanonicalStoreStatus`: verified, stale, conflicted, unavailable, legacy, orphaned.
- `NotificationStatus`: candidate, classified, interdicted, rendered, delivered, acknowledged, suppressed, failed.
- `LearningEvidenceStatus`: candidate, shadow, review-ready, promoted; promotion never changes financial policy automatically.
- `MaturityDimension`: score, evidence class, proof references, limiting factor, next proof.

Frontend pages must consume typed backend responses and must not infer these states.
