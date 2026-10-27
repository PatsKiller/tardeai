# Home — v001 (APPROVED 2026-10-24)

Approved boards: Board 14 Home.
Approval: operator, 2026-10-24 — "I approve the markups. Give it to Codex." (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- Do-now list ranked by the CIO (max 7).
- Protection card: broker stops, awaiting fill, nearest stop — by stop STATE, never collapsing awaiting fill into "no stop".
- CIO market view from the same regime / VIX / sectors source as every other page.
- Waiting on you: approvals count equals the header count.
- Weekend-aware freshness wording (market closed · last broker sync · next sync) instead of a stale warning on non-trading days.
- Plain English only; "Set stops" opens the stop review / advisory view, never a broker action.

## What stays

- Header metrics stay in the header.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- remove: panel "repeat of header metrics" — the header already shows them
- remove: widget "dead tiles" — tiles with no live source are removed (Board 14)
