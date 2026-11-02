# CC-DASH-FRESHNESS: Correct dashboard source clocks and missing-data states

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-174 in docs/governance/OPEN_ITEMS.md.
Priority: P0. Owner: platform. Review by: 2026-11-03.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Finish #2484 mixed-feed state handling and TODAY producer-clock trace; preserve positions/P&L/quotes as separate clocks. Publish reviewed risk provenance878b4cb55 and correct the consumed orchestrator health schedule source.

## Acceptance evidence

Every widget has source as_of versus captured_at; empty/failed sources are retryable and never green. Source age, session validity and served bundle identity are independently demonstrated.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 0. Member SHA256: not a job cohort.

Cross-cutting platform finding; no additional job denominator implied.
