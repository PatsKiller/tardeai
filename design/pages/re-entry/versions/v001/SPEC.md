# Re-Entry — v001 (APPROVED 2026-10-24)

Approved boards: Board 1 Re-Entry.
Approval: operator, 2026-10-24 — "I approve the markups. Give it to Codex." (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- Tabs: Ready now · Exits review · Resistance & levels · Analyst evidence.
- Look-through, rotation workspace and alerts become links (Board 13).
- Stale buy-ready packets (> 48 h) are hidden from Ready now and kept in history.

## What stays

- The classic page stays reachable at /portfolio/re-entry/classic until the desk is accepted.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- move: panel "Look-through" — link to Portfolio › Look-through
- move: panel "Rotation workspace" — link to Rotation
- move: panel "Alerts" — link to the alerts owner page
- hide: rows "buy-ready packets older than 48 h" — kept in history
