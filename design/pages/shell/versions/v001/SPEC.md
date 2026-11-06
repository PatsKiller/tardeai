# App shell: nav rail, header strip, Ask bar, desk frame — v001 (APPROVED 2026-10-24)

Approved boards: Board 0 Main (nav rail + shared page pattern), Board 13 Ownership.
Approval: operator, 2026-10-24 — "I approve the markups. Give it to Codex." (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- Nav rail carries all eleven restored desks in the groups shown (Trade / Intel / Ops), each with a "back" badge for 14 days.
- Shared DeskPage frame on every desk: purpose line, URL tabs (?tab=), a Source clocks strip (each source: age + writer lane state ACTIVE / PAUSED / RETIRED / NONE from the lane registry + last successful run), in-panel gap notices, and a "Decisions for you" band.
- Board 13: each piece of content has one home; other pages summarize and link. docs/ops/CONTENT_OWNERSHIP.md lists the owners and a test proves the listed duplicates are gone.
- Tokens only (no raw hex); the raw-hex ratchet goes down.

## What stays

- Every existing route keeps working; restored desks add to the rail, nothing leaves it.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- move: content "duplicated panels listed in CONTENT_OWNERSHIP.md" — each keeps one home; other pages show a summary + link (Board 13)
