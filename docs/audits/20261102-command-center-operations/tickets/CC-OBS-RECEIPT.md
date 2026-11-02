# CC-OBS-RECEIPT: Wire missing run receipts

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-168 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Reuse the existing shared receipt writer at the original execution boundary, after real output and before success is reported.

## Acceptance evidence

Every member's synthetic and naturally scheduled runs yield identity-bound immutable attempts; missing output or writer failure cannot return success.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 6. Member SHA256: e153390abce3ceb4974480cc92ee99357c585bc419ae7d26f9064bd9fe1a93be.

- cio-entry-state
- cio-wake-dispatch
- cron-outage-watchdog
- governed-research-producer
- investment-costs
- run-ensemble-worker
