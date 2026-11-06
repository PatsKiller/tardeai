# CC-OBS-ON-DEMAND: Model on-demand and event work explicitly

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-167 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Record nonrecurring trigger semantics, actual last attempt and output; do not invent a next-due time or a missed periodic run.

## Acceptance evidence

Every member is correctly typed and each actual invocation has a receipt; absence of a request is distinct from a failed request.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 8. Member SHA256: 15a3987d077fcc66459422d601920fc1d86fe4542248088c111cf36e367d1cf2.

- advisory-desk-run-now
- aegis-brief-regenerate
- analyst-prospectus-generate
- cio-situation-detector
- openclaw-reminder-claude-plan-1
- openclaw-reminder-claude-plan-2
- openclaw-reminder-sentinelone-earnings
- openclaw-reminder-supergrok-expiry
