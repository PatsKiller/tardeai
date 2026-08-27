# Defense Desk redesign v1 — DD-S1 acceptance

**Date:** 2026-07-29 · **Spec:** `defense_desk_redesign_v1.html` md5 `388f0ad091ad886be631b5b56d34defb`
**Flag:** `DEFENSE_REDESIGN_V1`, **default OFF** · `SECTOR_LEADERS_V1` untouched and still ON
**Evidence:** `reference.png` · `build.png` · `side_by_side.png` (identical harness, 1760×1200 @2x)

Both captures use the harness from contract §7. One adaptation was required and is logged below
(`full_page` alone does not capture the CC v3 shell's inner scroll container).

---

## SECTION WALK

| # | Section | Verdict | Note |
|---|---|---|---|
| 1 | Command strip | **match** | title, freshness chips, `2 sectors stale >5d`, refresh control |
| 2 | Where to act | **match** | 4 tiles, live selection; Real Estate correctly the stalest at 16 days |
| 3 | Market state | **match** | 6 cells + tape line, all live |
| 4 | Transitions | **match** | 6 columns; all four Read strings reproduced deterministically |
| 5 | Sector leaders | **match** | chrome and card body both on redesign tokens; variant-scoped — see D-4 |
| 6 | Quadrant + lists | **preserved** | production `RotationBoards` untouched per contract §5 — see D-5 |
| 7 | Your book | **match** | 6 columns incl. Sector rank and ladder chips |
| 8 | Short side + hedges | **match** | both panels, 3 advisories + 4 hedge pairs |
| 9 | Oversight | **match** | strongest objection + counterpoint, both live |
| — | Preserved components | **added per §2b** | 5 live components below section 9 — see D-6 |

No section is missing. No column was added, removed, or reordered. No chip colour changed meaning.

---

## PRE-AUTHORIZED DEVIATIONS (logged, not re-asked)

### D-1 · Page background stays `BB.bg #0f172a`
The mockup grounds the page on `#0a0e1a`. Operator-authorized 2026-07-29: the design's intent is
the contrast *relationship* between page / panel / sunken, not the specific hex, and `BB.bg` is
shared with other pages so repainting it is not a defense-page decision. Panel `#111827` and sunken
`#0d121f` are exact, so the relationship holds.

### D-2 · Visual contract §6 superseded — dispersion has four states
§6 asserted production returned `buy names` on a negative excess. It did not, and could not:
`buy names` requires `spread >= 12` **and** `excess >= 4`. The cited numbers
(spread 38.1 / excess −9.14 / n=14) belong to **Oil & Gas Equipment & Services**, not Oil & Gas
Integrated — both have n=14. Operator confirmed the transposition and authorized the real
requirement hiding inside it: a fourth state so a wide-spread-but-trailing group is legible rather
than folded into `mixed`.

```
spread >= 12 and excess >= 4  -> buy names
spread >= 12 and excess <  0  -> leaders trail the ETF     <- new
spread <= 6                   -> buy the ETF
otherwise                     -> mixed
```

Presentation split only; no threshold moved. 5 tests added, 31 pass. Live effect: Oil & Gas
Integrated stays `buy names` (excess +8.67), Equipment & Services moves `mixed` → `leaders trail
the ETF`.

---

## DEVIATIONS NOT NEEDING SIGN-OFF (contract §8)

### D-3 · Two manifest tokens deliberately not defined
`--bg2 #161d2e` and `--purple #a855f7` are declared in the mockup's `:root` but referenced **zero
times** in its markup and CSS. Verified by grep. `--purple` is additionally a hex the page's own
design system deprecates in favour of `T.extIntel.hermes` (`#a78bfa`). Three tokens were added
(`DD.sunk`, `DD.line2`, `DD.t3`); ten map to existing BB/T values.

**The mapping was made by VALUE, not by name.** `--t2 #94a3b8` maps to **`BB.text3`**, not
`BB.text2` (which is `#cbd5e1` and appears nowhere in the mockup). A name-based mapping would have
been one shade off on every muted label — the same failure that derailed the previous attempt.

### D-4 · Sector Leaders card body — RESTYLED, variant-scoped (closed 2026-07-29)
The card is rendered by two surfaces: `SectorLeadersPanel` (live behind `SECTOR_LEADERS_V1`,
default ON) and the redesign (default OFF). A blind restyle would have changed the LIVE surface
while the redesign is meant to stay dark, so the divergent values are **parameterised** via a
`variant` prop rather than replaced — no duplicated component, no production repaint.

```
v1        cells BB.bgPanel · headers 12px sentence-case · title 16px   (live, unchanged)
redesign  cells S.bg1 / S.sunk · headers 10px uppercase on --t3 · title 14px
```

Everything the two share — columns, chips, dimming, the `<Val>` null contract — stays
single-sourced. Verified by capturing both variants side by side (`card_v1.png`,
`card_redesign.png`).

**Two changes are NOT variant-scoped and therefore also land on the live card**, because they are
VALUES rather than style (contract §1):

- the industry row now shows its **global rank**, e.g. `rank 8 of 144`, which the card never
  rendered and the mockup requires;
- the dispersion verdict gains the fourth state, so Oil & Gas Equipment & Services reads
  `leaders trail the ETF` instead of `mixed` on both surfaces.

Both are correctness improvements the operator authorized globally (D-2), so they are intended on
the live card. Flagged here so the live-surface change is not silent.

### D-5 · Section 6 is the production component, not the mockup's redraw
Contract §5 requires the quadrant and ranked lists be preserved. The production `RotationBoards`
carries controls the mockup's redraw omits (oversight pills, W/M/Q + Sectors/Industries toggles,
per-row bars). It is rendered unmodified inside the redesign flow. Its container styling already
matches the surrounding panels, so nothing was touched.

### D-6 · Five components render below section 9
Per contract §2b (operator amendment): `ExecutionPanel`, `OptionsLifecycleStrip`,
`RotationPlanPanel`, `ReviewConsole`, `DefenseDetails` are preserved unmodified under a labelled
divider. Nothing was deleted.

### D-7 · Screenshot harness adapted for the app shell
`full_page=True` alone captured only 2400px of a 4391px page — the CC v3 shell scrolls an inner
container, so the document height is the viewport height. The harness now measures real content
height and resizes the viewport before capturing. Same viewport width, same scale factor, same
600ms settle; the reference is captured with the unmodified harness.

### D-8 · Row counts and selections differ from the sample
Real data throughout: Your book shows 7 of 13 stances (mockup shows 7 of 13 too, different names);
Oversight selects `paid` + `chatgpt` where the mockup sampled `paid` + `paid_xai` — selection is
deterministic (freshest usable seat, then freshest other), and the specific pair is a VALUE per §1.

### D-9 · Fields rendered `unk` because no source exists
- **Your book · Sector rank** for multi-sector funds (SCHD, JEPI, ARKX, DIVI, BND) — operator
  decision: no invented `broad`/`thematic` label. Reason on hover, e.g. *"multi-sector holding
  (10 sectors) — no single sector rank"*. Single-sector holdings resolve correctly through the
  reverse alias: V → `#2 Financials`, XLI/XAR → `#7 Industrials`.
- **Transitions** for the style row — RS 5d, Breadth and Your exposure are `unknown` because a
  style spread has no constituents and no book exposure.

### D-10 · Transitions "Read" is rule-derived, empty when no rule fires
Per operator decision, four deterministic rules over existing fields. Verified against live data —
they reproduce all four mockup strings exactly, including `+6.1` and `33%`. An empty cell is
**not** rendered through `unk`: absence of commentary is not a missing value.

---

## FIXED DURING THE BUILD (found by rendering, not by reading)

| defect | cause |
|---|---|
| Page crashed, all 9 sections blank | `oversight.seats` is an **object** keyed by seat, not an array — `.find` threw |
| Net equity / Cash `unknown` | field is `net_exposure.equity_pct`, not `net_equity_pct` |
| Tape line `unknown` | field is `market.state_line`, not `market.line` |
| Duplicate Sector-leaders header + picker | passed the whole `SectorLeadersPanel` instead of the card |
| Communications shown as the stale tile | picked the *first* stale sector, not the **stalest** (6d vs 16d) |
| `industries never` chip | `captured_at` lives on the industries endpoint, not posture |
| PSQ appearing under Short side | inverse hedges share the `short_side` group — filter on `direction === 'short'` |
| Hedges panel empty | pairs are on `/defense/inverse-stoplights` `.candidates[]`, with a `lights{}` map |
| Ladder column all `—` | ladders are a separate array keyed by symbol+account, not a field on the stance |

---

## SAFETY

Read-only throughout. No POST/PUT/PATCH/DELETE added; the redesign issues three GETs
(`sector-leaders`, `inverse-stoplights`, plus the hub's existing calls). No `paper_trade_proposals`,
no broker adapter, nothing that places, stages or approves an order. `npm run build` green with
`[design-guard] pass (278 files)` — zero raw hex added, defense stays at its 0-violation baseline.
Production `:7777` was never touched; all capture ran on a scratch instance on `:7899`.
