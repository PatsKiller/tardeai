# Control-Plane Contracts v1

The Command Center control plane is a read-only projection of canonical Trade AI state.
Every response carries `evidence_class`, `source_sha`, `as_of`, and `data_quality`.

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
