# Site fix package (cross-cutting) — v001 (APPROVED 2026-10-24)

Approved boards: Site fix package (FINDINGS P1/P2/P3) — a fix package, not a layout board.
Approval: operator, 2026-10-24 — "fix EVERYTHING in FINDINGS.md (P1, P2, P3)" (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- Principle 1: one source owned by the CIO record. A read-only resolver serves stance + conviction, portfolio totals, today P/L, position count, stops (broker resting before planned), regime, sector posture, pending approvals, account labels and paper win rate; every surface reads it and a cross-surface consistency test proves agreement.
- Principle 2: every writer is a monitored n8n lane and appears in the missed-run watchdog.
- Monitoring truth: freshness is the last successful run (exit code + receipt), never a log mtime; failures show their real cause.
- Stop STATE is shown everywhere (active / pending activation / awaiting fill / none), never only a price. Read-only display; MBI_BEHAVIOR=0.
- Load budget: no endpoint above 500 KB per poll; lists paginated server-side; tabs fetch only when shown; GETs never start broker reads or jobs.
- P2/P3: weekend-aware freshness, URL-synced tabs, plain-English labels (no ids, schema names, paths or snake_case), raw hex replaced by tokens.

## What stays

- Redesigned pages (Home, Risk, Jobs & health, CIO Overview + Capital, Watch › Sectors) are restyled only from their own approved boards, never from this package.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- none
