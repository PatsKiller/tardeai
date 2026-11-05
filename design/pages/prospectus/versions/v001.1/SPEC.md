# Prospectus v001.1 — polish note on the approved v001 (no redesign)

Requested by the operator 2026-10-26, verbatim: "what are these F with the numbers all over the pages? … internal
pointers. Do those really need to be shown? Is there any way we can polish this any more?" — and, on a fund's
ownership block: "ETF shouldn't have this. They should have something else that's relative to ETF."

The v001 structure (list, report order, tiles, blocks, phone sheet, downloads) is kept. This note lists every visible
change so the removal guard (§28.13 item 4) can check it. It is a polish of v001; the ledger decision for it is the
operator's (Approvals → Designs).

## Changes

1. **Citations.** Internal fact ids ("[F7, F8]", "F42") never show. Each report renumbers them 1..n in reading
   order (verdict line, My history, sections, then block texts) and shows small superscript numbers; a run of three
   or more compresses ("4–8"). Tap or hover opens a popover: source label, value, source, as-of. The fact id stays in
   `data-fact-id` and in the JSON. PDF / Word: superscript numbers and numbered endnotes.
2. **Header name.** Recorded company name, else the name the profile description starts with, else the fund
   universe name, else the symbol shown once (never "SYM SYM"). The list row uses the same fallback.
3. **Fund-aware layout.** For a fund, a **Fund structure & holdings** block takes the Ownership slot: identity
   (index, issuer, inception, expense ratio, AUM, category · peers), holdings (count, top 10 with weights, top-10
   concentration, largest sector, sector / country weights), distribution (yield · TTM, last + cadence, 3-year
   growth), liquidity (volume, bid-ask, premium / discount to NAV), tracking (1Y vs index, vs category peers), and
   overlap with your book. Fields the house does not hold are named once: "Not in our data: …".
4. **One gap line per block.** A field that does not apply is hidden; a field the house lacks is named once per block
   ("Not in our data: X, Y"), never a dash per row. "not available yet" reads "not in our data".
5. **Source coverage.** Collapsed, with counts (used / stale / failed / missing); internal plumbing and
   not-applicable domains are kept in the JSON and counted, not listed (config/prospectus_presentation.json).
6. **Charts.** Line series merge on one sorted date axis; ticks are evenly spaced month starts ("Jan 26"); one legend
   style everywhere; an empty series is neither drawn nor listed. Returns-table columns no row fills are dropped.
7. **Tiles.** Stop: "$33.59 · resting" with a small "house $32.83" line; other accounts move to the stop-plan block.
   Yield · Expense reads the fund profile (the same fields the fund block shows); stocks show "Dividend yield".
8. **Prose.** Empty bullets, doubled spaces and space-before-punctuation are cleaned at render; "not reliable (…)"
   phrases are muted notes.

## Removed, hidden or moved (all listed)

- hide: raw fact ids in prose, tables and tiles (numbers instead; ids in data attributes).
- move: per-section citation pills → a collapsed "Sources (n)" disclosure under each section.
- add: one numbered "Sources" appendix at the end (open on desktop, collapsed on phone).
- remove (files): the PDF / Word / HTML "Sources and facts" table of every fact (the numbered Sources appendix
  replaces it; every fact stays in the JSON).
- hide (funds only): Ownership and flows, Estimates and earnings surprises, Earnings call, the dividend row of
  Options; the separate Fund profile panel is merged into Fund structure & holdings.
- hide (stocks): the "Fund flows 30d (ETFs)" ownership row.
- move: source-coverage chips behind a tap (counts stay visible); not-applicable and internal domains not listed.
- move: "other accounts" from the Stop tile into the stop-plan block.
- hide: relative-performance mini tiles and returns columns with no value (named once in the gap line).

Fixture-only evidence: apps/command-center-v3/e2e/prospectus-polish.spec.ts (1440 / 412 / 390). Real-data before /
after captures stay private (persistent-state handoffs/prospectus-20261026/shots/polish/).
