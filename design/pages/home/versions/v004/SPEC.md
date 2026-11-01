# Home v004 — SPEC (PROPOSED): YELLOW market-risk summary card

Proposed 2026-11-01. Builds on the approved home/v002 (DSN-20261031-market-risk-ui). Independent of home/v003 (the
"Market advisory" section, PR #2394, still PROPOSED): v004 changes only the banner slot above the header and touches no
card v003 adds. Numbered v004 because v003 is taken by #2394.

Mockups live in the private design store and are bound by sha256 in status.json (design/README.md rule 7). Market
figures are from the live shadow evaluation of 2026-11-01. Book values, symbols and accounts are placeholders
(`[ST-A]`, `[ETF-A]`, `[ACCT-1]`, `[xx]%`).

**Mockup only. No UI code until the operator approves home/v004.**

## What changes vs v002

v002 §2 says the banner is "hidden entirely at Yellow and below". At YELLOW only the header fact and the compact block
in "Market in one look" appear. The operator asked to see the contributor lines and "Your book" at YELLOW too, without
the alarm styling. v004 adds one component for YELLOW only:

**YELLOW summary card** (`MarketRiskSummary`, test id `home-market-risk-summary`), in the v002 banner slot: above the
header, full width, never sticky.

- Shown only when the tier is evaluated YELLOW (live or shadow). At ORANGE or RED the v002 banner takes the same slot,
  unchanged. At GREEN, BLUE or not evaluated nothing is shown, as in v002.
- **Calm warning tone, not the alarm tone.** Card background is the ordinary card surface (`--bg-1`) with a 1 px
  `--border-color` border and a 4 px left rule in `--warning-color`. The ORANGE/RED banner uses a full tone fill
  (`--elevated-bg` / `--danger-bg`), a solid tier pill and a 24 px title. The YELLOW pill is soft (`chipStyle('warning',
  'soft')`), the title is 14 px "Market risk 60/100", and the contributor points use `--text-1`, not the tone colour.
- **Collapsible.** The summary row is a disclosure (`<details>/<summary>` or a button with `aria-expanded` and
  `aria-controls`), at least 44 px high, labelled "Details ▾" / "Less ▴".
  - Phone (≤820 px): **collapsed by default.** Collapsed it shows the pill, "Market risk 60/100", the SHADOW label, and
    one line: the top contributors with points, "2 of 9 confirm", "evaluated Sun 09:07 ET". Measured in the mockup at
    412 × 915 and 390 × 844: the collapsed card is 130 px, "Do now" starts at 375 px and its first row ends at 463 px,
    inside the first screen.
  - Desktop (≥1280 px): **expanded by default**, in the banner's two-column layout (contributors and "De-escalates if" on
    the left; "Your book" and the links on the right).
  - The open/closed choice is remembered per viewer in browser storage (a convenience only; it falls back to the default).
- **Expanded content:**
  1. "evaluated <ET time> · N of 9 categories confirm" (phone; on desktop "N of 9" is in the summary row). YELLOW has no
     episode, so there is no "since …" or repeat count.
  2. Contributor lines: every category with points above 0, at most five, each "name · the number behind it · as_of ET"
     and its points (one decimal). Points sum to the score, as in v002; the same uplift line when vulnerability raised the
     tier. Live example: Options flow +34.4 (QQQ put/call OI 3.97, 3.85× median; SPY 2.20), Technical +25.3 (AI basket 0%
     above 20-day, relative strength −15.3 pts).
  3. One muted line naming categories that are not measured (e.g. extended hours) and that the rest add 0.
  4. **Your book** panel (`--bg-0`): vulnerability /100, budget breaches as "budget actual% vs limit%", positions near a
     stop as symbol + distance only, unprotected symbols (first three, then "+N more"). "Advisory only. No order, size or
     stop level is implied." Never a size, dollar amount or instruction.
  5. **De-escalates if** — the engine's sentence.
  6. "YELLOW never pages and has nothing to acknowledge." Plus, in shadow mode, "no alert was sent for this tier".
  7. Two **links** (text links, `--info-color`, ≥44 px high): **Open Risk →** (`/v3/risk?tab=market-risk`) and **Review
     stops →** (`/v3/risk?tab=exposure`).
- **No Acknowledge button** at YELLOW: YELLOW never pages and has no episode.
- **SHADOW label** (the existing `ShadowTag`, "SHADOW · not alerting") beside the pill whenever `mode` is shadow; nothing
  when live.

Unchanged from v002: the header fact (MarketRiskFact), the compact block in "Market in one look" (MarketRiskCompact), the
ORANGE/RED banner with Acknowledge, the classic hero tile.

## States

| State | What shows |
|---|---|
| Not evaluated | Unchanged (v002): no card, no banner; header fact "NOT EVALUATED"; the reason in "Market in one look". |
| GREEN · BLUE | Unchanged (v002): nothing in the banner slot. |
| YELLOW, live | Card as above, without the SHADOW label. |
| YELLOW, shadow | Card as above, with "SHADOW · not alerting". |
| YELLOW, stale (`as_of` older than `stale_after`) | Card stays, collapsed by default on every width. The summary shows pill, "Market risk", SHADOW label (if shadow), and "stale — last evaluation HH:MM ET. Numbers hidden until the engine runs again." No score, contributors, book or de-escalation rule. Expanded: one explanatory line and the two links. |
| YELLOW, contributors empty | Summary line reads "no category above 0 points"; the expanded list shows only the not-measured line. |
| ORANGE · RED | Unchanged (v002) banner in the same slot; the YELLOW card is not rendered. |
| Load error | Unchanged (v002): "market risk unavailable — Risk page" in the compact block; no card. |

## Phone (412 / 390)

One column; the card is first, then the header facts, then "Do now". Not sticky; fixed chrome stays ≤15% of the viewport.
No sideways scroll (scrollWidth equals viewport width at 412 and 390 in the mockup). ET times only. Contributor lines wrap;
never truncated to "…".

## Tap targets (≥44 px)

| Target | Size |
|---|---|
| Summary row / Details–Less toggle (whole row) | full card width × ≥44 px |
| Open Risk → | ≥44 px high, ≥ text width + 4 px |
| Review stops → | ≥44 px high, ≥ text width + 4 px |
| Header fact (unchanged) | ≥44 px |

The mockup measures the smallest summary/link target at 44 px at 412 and 390.

## Tokens (all existing; no new token)

`--bg-0`, `--bg-1`, `--border-color`, `--border-subtle`, `--text-0`…`--text-3`, `--warning-color`, `--warning-bg`,
`--warning-border` (pill and SHADOW label), `--info-color` (links), `--radius-lg`, `--radius-md`, `--radius-pill`; type scale
`TYPE.sm/base/md`. Not used by the card: `--elevated-*`, `--danger-*` (they stay with the ORANGE/RED banner).

## Mockups (private store, sha256 in status.json)

- `HomeDesktopYellow.dc.html` — desktop 1440, card expanded.
- `HomePhoneYellowCollapsed.dc.html` — phone 412/390, collapsed default with "Do now" on the first screen.
- `HomePhoneYellowExpanded.dc.html` — phone 412/390, expanded.
- `HomeStates.dc.html` — stale, not evaluated (unchanged), ORANGE and RED (unchanged v002 banner), GREEN/BLUE.
- `canvas.json` — board layout.

## Removals / hides / moves (rule 4 — complete list)

- None. Nothing is removed, renamed or hidden. The new card adds content; nothing that was visible moves behind a tap.
