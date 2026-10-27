# Watch — v001 (APPROVED 2026-10-24)

Approved boards: Watch › My Watchlist row redesign (+ conviction / setup sort and filter addendum); Board 18 Sectors.
Approval: operator, 2026-10-24 — "Watch › My Watchlist row redesign — APPROVED SPEC (operator, 2026-10-24)" (+ ADDENDUM: sort and filter on conviction) + "I approve the markups. Give it to Codex." (recorded in handoff, back-filled 2026-10-25).
Source: the 10-24 handoff spec, summarized here as text only. The mockups and the original spec stay
private on the host (see status.json `private_assets`); this file carries no real numbers, holdings or accounts.

## What changes

- My Watchlist desktop (≥ 821 px): one card per symbol on a 5-column grid — Company · Setup / why · Price vs levels · Conviction · Next step — with a header row of column labels; house row rail on the left edge (conflict → breach, needs review → attention, ready → favorable, otherwise neutral).
- Company column: star, ticker, company name, one-line description, sector + industry chips, ownership line (names only, never numbers).
- Setup column: stage + why, catalyst line ("None on file" when absent), ONE blocking callout "Not actionable: <reason>" (all conflict / Trade-AI / desk disagreement messages collapse into it), "Missing: …" footnote.
- Price vs levels: price + freshness label, a 34 px ladder (track, entry-zone band, price marker), Support / Zone / Resistance cells, ONE level-provenance footnote.
- Conviction: score / 100, bar, stance badge; "n/a" + "no stance" when missing.
- Next step: primary button by state + a quiet secondary "Set alert · Remove" button; existing handlers unchanged.
- Phone (≤ 820 px): card per symbol; full-width primary button (≥ 44 px) + a 44 px "More actions" (⋯) button.
- Sort and filter on conviction and setup, server side, every value in the URL: Conviction ↓ / ↑ (no score always last), header buttons cycle with aria-sort; Conviction presets Any · ≥ 80 · ≥ 70 · ≥ 60 · < 60 · No score; Stance multi-select; Setup sort (most ready first) and stage filter incl. Blocked and Has / No catalyst; facet counts; "Clear filters" resets all.
- Board 18 Sectors: multi-horizon relative strength (1-day is context only; 20 / 60-day drive "Trend"), CIO posture column from the same source, exposure + leaders.

## What stays

- All colours, sizes and fonts from the house tokens (designTokens.ts / watchTokens.ts); no new hex, no new tokens.
- Existing Watch tabs stay.

## Removals, hides and moves

Machine-read by the removal guard: `- <remove|hide|move|rename>: <kind> "<label>" — <why>`.

- move: message "per-row conflict / Trade-AI / desk-disagreement messages" — collapsed into the one blocking callout; the rest in the side panel
