# CC-ALERT-REPEAT: Restore watchdog reminder delivery semantics

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-172 in docs/governance/OPEN_ITEMS.md.
Priority: P0. Owner: comms. Review by: 2026-11-03.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Integrate e6ad137a1 only after its two independent exact-head MERGE reviews. Preserve every routing/interdict/transport hold and the ordinary 20-hour duplicate window; expose why a current critical reminder is held.

## Acceptance evidence

Synthetic due/early/slot-boundary/forgery/hold cases pass; a governed TEST and a naturally due receipt retain typed delivery evidence. No accepted/HELD result is called delivered.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 0. Member SHA256: not a job cohort.

Cross-cutting platform finding; no additional job denominator implied.
