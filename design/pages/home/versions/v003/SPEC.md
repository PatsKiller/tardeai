# Home v003 — SPEC (PROPOSED): the "Market advisory" section

Proposed 2026-10-31 (design DSN-20261031-home-advisory-section). Builds on Home v002 (market risk fact, banner, "Market in
one look"), which stays exactly as approved. Operator 2026-10-31, verbatim: "It should also be in a section on the
homepage, maybe not prominent up top, but somewhere". Mockups use synthetic data only (placeholder tickers STOCK-A, ETF-A;
bracketed values); they live in the private design store and are bound by sha256 in status.json.

## Placement (Default Home, `HomeDoNow.tsx`)

One new card, **Market advisory**, inserted **below "Market in one look" and above "System pulse"**. It is not at the top:
the header facts, Do now, Accounts, What moved your book, Best opportunities and Market in one look keep their order.

- Phone (390 / 412): collapsed by default to a one-line summary row, for example
  "Market advisory · SECTOR shock (AI / semis) · 2 groups leading · 3 re-entry watches". Tap expands in place; the
  expanded/collapsed choice is remembered per viewer (local preference only).
- Desktop (1440): expanded by default, in the same grid row position as the cards around it.

## Contents (three blocks, in this order)

### a. Shock type and heat-map strip
- Line: shock class (SYSTEMIC · SECTOR/THEME · FACTOR · RATES/MACRO · CREDIT · EVENT, or "no stress"), the groups hit and
  the groups holding, e.g. "SECTOR (AI / semis / tech) — not systemic: 8 of 11 sectors holding".
- Strip of small tiles: the 11 sector SPDRs plus Semis, AI basket and Defensives. Tile colour = group state
  (stressed · weak · neutral · resilient · unknown); tile text = short name and 5-day move. Tap a tile → Risk page heat map.
- Unknown groups render grey with "unknown", never as zero.

### b. Where leadership is moving
- Up to 4 groups, each labelled CONFIRMED · EMERGING · FADING (BOUNCE_ONLY groups are not listed).
- Under each confirmed or emerging group: up to 3 candidates (sector ETF and names from the watchlist / CIO opportunity
  store), each with the CIO stance word (ADD candidate, WATCH), a horizon tag (TACTICAL weeks / STRATEGIC months), the next
  catalyst, and "you already hold this exposure through …" when overlap exists.
- When the market-risk tier is ORANGE or RED, a line reads "New entries held while market risk is ORANGE/RED".
- Tap a group → full-screen sheet: evidence (relative strength 20/60/120 sessions, breadth, volume), backtest hit rate with
  n, and the candidates.

### c. Re-entry watch
- One row per symbol stopped out or sold in the last N days (policy), whether or not a residual is still held:
  symbol · "n of m conditions met" · next gating event (e.g. "earnings 11-03 pending — not evaluated until the reaction
  settles") · stance word (RE-ENTER IF / RE-ENTER).
- Tap a row → full-screen sheet: each condition with met / not met / unknown and its as_of; the historical base rate
  ("in past setups like this, re-entering on these conditions beat waiting k of n times"); wash-sale note for taxable
  accounts only; "Advisory" footer.

## Rules
- Every number carries an as_of; unknown is shown as unknown.
- Advisory wording only: CIO stance words and conditions. No size, share count, price to buy at, order, stop level or
  weight anywhere. Footer on the card and every sheet: "Advisory. No order, size or stop level is implied."
- Residual positions below the materiality floor are never listed.
- Tokens only; no literal colours, radii or spacing. Tap targets ≥ 44 px; no sideways scroll; list → detail is a
  full-screen sheet on phone.

## Data sources (all pending — build waits for them)
| Element | Source |
|---|---|
| Shock class, groups hit/holding, heat-map tiles | market-risk snapshot fields `shock_type`, `sectors`, `heatmap` (PR #2388) via `GET /api/v2/market-risk/latest` |
| Leadership groups, candidates, horizon | rotation advisor snapshot block (PR in flight, `market-risk-rotation-20261031`) |
| Re-entry watch rows and conditions | re-entry watch stances (precision follow-up, in flight) via the same snapshot / CIO facts |
| Entry hold line | existing market-risk tier and `market_risk_gate` |

## States
Loading · not yet evaluated (engine not live) · no stress (block a shows "no stress"; b and c may still have rows) ·
evaluated · stale (as_of past stale_after: "stale — last evaluation HH:MM ET") · load error ("Market advisory unavailable —
Risk page"). Each block degrades on its own: a missing source shows that block's "not available yet" line, the others render.

## Removals / hides / moves (rule 4 — complete list)
- None. One card is added; nothing is renamed, hidden, deleted or moved.
