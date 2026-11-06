# Jobs & health — v001 (APPROVED 2026-10-24)

Approved boards: Board 16 Jobs & health.
Approval: operator, 2026-10-24 — "I approve the markups. Give it to Codex." (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- New /ops/jobs page: ONE job-execution truth (due / succeeded / failed / missed / paused-retired, last run, result, next due, real cause), driven by the missed-run watchdog.
- The same view is embedded in Health, Releases & Schedules, Ops Controls, Coordination and System.

## What stays

- Those pages keep their other tabs.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- remove: column "health columns of the five schedule views" — replaced by the one jobs view (change control satisfied by this board)
