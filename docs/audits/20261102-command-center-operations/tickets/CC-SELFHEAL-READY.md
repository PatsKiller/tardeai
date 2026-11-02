# CC-SELFHEAL-READY: Qualify and authorize the existing self-heal implementation

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-173 in docs/governance/OPEN_ITEMS.md.
Priority: P0. Owner: agents. Review by: 2026-11-03.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Complete the technical qualification and separate policy, lane push capability, budget and scheduler-install requirements in SELF_HEAL_READINESS.md. Keep main-red reruns separate from code repair.

## Acceptance evidence

The qualified worker fixes a synthetic defect under its real restricted identity, refuses protected scope, produces diagnostics and a reviewed draft, then demonstrates reclaim/idempotency. Activation remains a genuine operator decision.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 0. Member SHA256: not a job cohort.

Cross-cutting platform finding; no additional job denominator implied.
