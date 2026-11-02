# CC-UX-STATE: Make health and incident state truthful and actionable

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-175 in docs/governance/OPEN_ITEMS.md.
Priority: P0. Owner: platform. Review by: 2026-11-03.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Integrate Health/Incidents1529cd017 and complete Releases2494/2495 joint acceptance. Apply the narrow truthful-state fixes first; broader IA proposal remains reviewable in UX_REVIEW.md.

## Acceptance evidence

Unknown values remain Unknown, producer health direction is respected, only confirmed delivery is labeled delivered, severity/owner/blocked next step are visible; critical state and root-cause path fit the proposed 60-second workflow.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 0. Member SHA256: not a job cohort.

Cross-cutting platform finding; no additional job denominator implied.
