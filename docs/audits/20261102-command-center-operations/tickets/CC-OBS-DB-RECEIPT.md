# CC-OBS-DB-RECEIPT: Expose existing database-backed run evidence

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-160 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Identify the registered read-only receipt query and clock. Validate run identity and completion semantics rather than reading arbitrary mutable success markers.

## Acceptance evidence

Each member exposes schedule/attempt/completion from its actual receipt owner with missing query errors preserved and a reproducible read-only proof.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 5. Member SHA256: 24e7f2138973d702cd1dc0d4a7e8a6c8eb49bee5a1bfbad87db7c194990f82bc.

- dof-rescan-tickets
- finviz-health-check
- hermes-pipeline-health
- schwab-stream-daemon
- system-rollup-snapshot
