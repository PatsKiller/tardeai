# CC-FAIL-JOB: Repair the nine observed failed jobs

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-154 in docs/governance/OPEN_ITEMS.md.
Priority: P0. Owner: platform. Review by: 2026-11-03.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Use the per-job causes in FAILURE_DIAGNOSTICS.md and its receipt addendum. Review the four source fixes, reuse #2444 relay changes, and investigate remaining exceptions from safely retained evidence. Protected members require their scoped grant.

## Acceptance evidence

Each member has a measured subsequent attempt or explicitly documented governance block; no retry with unknown prior effects, no enforcement bypass, no success inferred from log mtime.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 9. Member SHA256: 853f5034c918b8b864352fd409f4937bb0b20b05f574a81c4bbc5d32c3ab8c4a.

- cio-ask-lifecycle
- cio-prospect-shadow
- conflict-resolver
- disk-hygiene
- finviz-screener-runner
- macro-calendar-refresh
- n8n-incident-fanin
- trade-close-llm-analyzer-source
- watchlist-enrichment-sweep
