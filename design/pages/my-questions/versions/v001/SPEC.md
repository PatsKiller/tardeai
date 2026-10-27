# My questions — v001 (APPROVED 2026-10-24)

Approved boards: My questions grouped (Questions board).
Approval: operator, 2026-10-24 — "I approved all of your markups. Please make sure that they're implemented per your design." (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- Search, a Group by segmented control (security / sector / theme / date / none; aria-pressed), channel select, grouped list with per-group CIO memory summary.
- Thread detail adds "Related from CIO memory" (the asks the answer actually recalled), tracking chips and a follow-up box.
- Theme grouping appears only when theme data exists; unknown sector → "Unclassified", never guessed.
- Manual regroup (⋯ menu) is an operator override stored as an event, never by editing history.

## What stays

- Everything not listed under What changes or Removals.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- none
