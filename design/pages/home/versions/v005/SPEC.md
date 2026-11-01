# Home v005 — SPEC (PROPOSED 2026-11-01): actionable market-risk card

Builds on the approved home/v004 (YELLOW summary card) and home/v002 (ORANGE/RED banner). Mockup for the operator's
decision in Approvals → Designs; nothing here is built. The build PR cites `Design: home/v005` only after approval.

Mockups live in the private design store and are bound by sha256 in status.json (design/README.md rule 7). Market
figures are from the 2026-11-01 shadow evaluation. Book values, symbols and accounts are placeholders (`[ACCT-1]`,
`[$xx,xxx]`, `[ETF-A]`, `[EXIT-A]`). A local-only render with the operator's real numbers exists outside the repo for
his review; it is never committed.

## Why

The operator on the live v004 card, verbatim: "this is just yellow. It's not telling me what sectors are yellow, what
sectors are going better, what sectors are doing worse, which one of those sectors are in my holdings that I should be
concerned about. Then on the right, when you have some of my holdings, is this quantified by the quantity that I have?
... it doesn't give me any clear actionable indicators."

And, on the two most recent stop-outs (names withheld, rule 7): "Is it still down or is it recovering, ready for reentry? It needs to be clear,
concise information... it should have the look-throughs ... from any of my ETF or funds that I'm holding. And on
something like [a multi-segment issuer] that has multiple different verticals, it should have had the look-through on that also."

And, on the re-entry rule: "Do we really want it back above the 20-day level? Or we just want second green candle to
break... We want to catch the ride going back up."

v005 answers those in short lines with dollars. Every line is a fact, a status or a review prompt. **MBI_BEHAVIOR = 0:**
the card never shows a size, an order, a share count to buy or sell, or a stop level to set. "Review" links open the
existing Review page or stop review; there are no order or size controls.

## What changes vs v004 (one component: `MarketRiskSummary`, test id `home-market-risk-summary`)

Same slot (above the header, full width, never sticky). v005 replaces v004's body at YELLOW and, at ORANGE/RED,
**extends** the v002 banner with the same sections (the banner keeps its tone fill, solid pill and Acknowledge).

### Summary (always visible, collapsed or expanded)

| # | Element | Content | Source (engine → projection) |
|---|---|---|---|
| S1 | Pill, score, SHADOW label, "N of 9 confirm · <ET time>" | unchanged from v004 | `tier`, `score`, `mode`, `confirming`, `as_of` |
| S2 | **Verdict line** (15 px, bold) | `<shock label> — <stressed groups>. Not market-wide: <k> of <n> sectors holding.` For SYSTEMIC: `Market-wide selloff — <n_down> of <n> sectors down.` Other classes: `<class label> — <stressed groups>.` | `shock_type.class`, `shock_type.label`, `sectors.stressed[]`, `sectors.sectors_measured`, count of sector-kind groups not STRESS/WEAK |
| S3 | **Your exposure line** | `Your exposure: $X (Y% of book · Z% of invested) in stressed groups — mostly <largest contributor>'s <w>% <group>. Cash C%.` | new `book_exposure` block (below) |
| S4 | **Top review item** (one row, ≥44 px, links) | the first item of R (Review now) | `review[0]` |

Phone (≤820 px): collapsed by default and shows S1–S4 only. Desktop (≥1280 px): expanded by default. The open/closed
choice is remembered per viewer in browser storage (convenience only), as in v004.

### Expanded body (desktop: two columns; phone: one column in this order)

Left column (phone first): **1 Sectors**, **2 Since you were stopped out**. Right column: **3 Positions**,
**4 Review now**, **5 Budget breaches**, **6 Multi-segment issuer split** (only when a held or watched issuer has a
segment entry), **7 Why the score is N** (v004 contributors, not-measured line, De-escalates if, Open Risk / Review
stops links), then the YELLOW/ORANGE footer line ("YELLOW never pages…" / "ORANGE pages once per episode…") and the
shadow note.

#### 1 · Sectors vs SPY · your money in each (look-through)

One row per group in `heatmap[]` of kind `sector` or `theme` (macro and defensive rows stay on the Risk page).

| Column | Content | Source |
|---|---|---|
| Group | tier chip (`STRESS` = `--danger-*`, `WEAK` = `--elevated-*`, `HOLDING` = `--success-*`, `NOT MEAS.` = `--warning-*`) + label; themes marked "(theme)" | `heatmap[].state`, `.tier`, `.label`, `.kind` |
| 1d vs SPY | relative 1-day %, signed, red/green | `sectors.groups[].rs1` (**add to heatmap**) |
| 5d vs SPY | relative 5-day % | `heatmap[].rs5` |
| You ($) | dollars in the group, look-through | `book_exposure.groups[key].usd` (new) |
| % book (desktop) | share of the total book incl. cash | `book_exposure.groups[key].pct_book` (new) |

- **Sort:** STRESS/WEAK groups you hold (usd > 0) first, by usd desc; then UNKNOWN groups you hold, by usd desc; then the
  rest by usd desc. Groups with usd = 0 last.
- **UNKNOWN held groups:** the 1d/5d cells read "not measured — you hold $X" (phone: "not measured"; the $ column shows
  the amount). The UNKNOWN reason (`sectors.groups[].reason_unknown`) is the cell's title text.
- Footer (11 px, `--text-3`): "Funds counted by their holdings (look-through). Themes overlap sectors — never added
  together. No look-through: <symbols with $> (<total>). Cash $C (C%). Market data <ET date> close."

#### 2 · Since you were stopped out (re-entry)

Rows: every `reentry_watch` entry with `exit_date` inside `reentry_watch.card.recent_sessions` sessions (config;
proposed 5), newest first; a link "+N older exits on watch (<first> → <last>) — Risk → Re-entry" for the rest of the
`lookback_days` (30) window. One card per symbol, at most five lines:

```
<SYM>  exit $<exit_price> · <ET day> · <account label>[ (<other account> <date> at $<price>)]
now $<last> (<±%> vs exit) · <±%> vs 20-day · <trend arrow>          [VERDICT BADGE]
Stage 1 (early setup): k of 5 — waiting: <unmet conditions in plain words>
Invalidates below $<swing_low> (selloff low) · Stage 2 (confirmed): <unmet stage-2 conditions>
⚠ Wash sale: <account> loss sale <date>. A <account> re-buy before <ET date> defers that loss.     (only when set)
⚠ Earnings <date> (inside 5 sessions)                                                           (only when set)
look-through: <top 3 groups with %> · other <%>   |   segments (<status>): <segment> → <group> <w>% …
```

Condensed form used in the collapsed top item and in Telegram:
`<SYM> · exit $<p> · now $<p> (<±%>) · Stage 1: k of 5 — waiting: <a>, <b> · invalidates below $<z>`

**Verdicts** (badge; one per symbol, first rule that matches, all thresholds in config):

| Verdict | Rule | Badge tone |
|---|---|---|
| Invalidated | a Stage 1 setup existed and a close fell below its `invalidation_level` within `invalidation_sessions` (10) | `--danger-*` |
| Confirmed | Stage 2 met | `--success-*` |
| Early setup | Stage 1 all 5 met | `--success-*` (soft) |
| Basing | no close below the swing low for `basing_min_sessions` (3) and every close within `basing_band_pct` (3.0) of the swing low | `--warning-*` |
| Still falling | otherwise (a new swing low inside the last `basing_min_sessions`, or no session since exit) | `--danger-*` |

**Stage 1 — "Early re-entry setup" (catch the turn).** All five must hold; the card shows k of 5 and names the unmet:

| Key | Plain words on the card | Rule (config `reentry_watch.stage1`) |
|---|---|---|
| `follow_through` | "higher low + 2 green closes" | after the swing low (lowest low since exit), a later bar's low stays above it (higher low), then two consecutive green closes (close > open), the second closing above the first green bar's high |
| `volume` | "volume ≥1.0×" | the second green day's volume ≥ `volume_ratio_min` (1.0) × its 20-session average volume |
| `group_no_new_low` | "look-through groups still at relative lows" | the symbol's look-through-weighted group ratio vs SPY made no new low over the last `group_rs_sessions` (5). Weighted by the symbol's own look-through (fund factsheet, holdings snapshot or issuer segments), never by its single "main" sector |
| `hedging_easing` | "hedging easing" | index put/call OI vs median below its peak of the last `hedging_peak_sessions` (5) by at least `hedging_ease_pct` (10) |
| `tier_ok` | "market tier ORANGE+" | market tier not in `blocked_tiers` ([ORANGE, RED]) |

**Invalidation level** = the swing low. A close below it cancels the setup; the verdict shows Invalidated and a new swing
low starts a new count.

**Stage 2 — "Confirmed recovery" (the add point).** Any one of: a close above the 10-session average
(`confirm_ma_sessions: [10, 20]`), a close above the 20-session average, or a close above the exit price. The 20-day
test moves here, from the old entry gate to confirmation.

**Short history (recent IPOs):** when the symbol has fewer bars than the moving-average window, the MA tests use the
anchored VWAP from the swing low instead (`short_history_anchor: swing_low_vwap`), and the card says "anchored VWAP" in
place of "10-day".

**Always shown, never gating:** earnings inside `earnings_ahead_sessions` (5) as a warning line (when two sources
disagree on the date, the line says so); the wash-sale end date when `wash_sale_note` is set (taxable loss sale only,
from the latest taxable loss sale; IRA sales never).

The v004-era 5-condition rule (trend repaired above the 20-day and the pre-exit close; group out of stress for 2
sessions; earnings clear; tier ≤ YELLOW; hedging normal) is replaced by Stage 1 / Stage 2 above. Earnings moves from a
gate to a warning.

#### 3 · Your positions in stressed groups · by $ exposed

Top 5 holdings (per account row, not merged across accounts) ranked by `usd_exposed` desc, then "+N more" with their
total. A last line names the material holdings with 0% stressed exposure.

| Column | Content | Source |
|---|---|---|
| Symbol | ticker; phone shows the account under it | `positions[sym]` |
| Account | account display label | holdings store `account_summaries[acct].display_name` via the projection |
| Value | market value $ | holdings store `holdings[].market_value` |
| % acct (desktop) | value / account total | holdings store |
| Stressed | look-through share of the position in STRESS/WEAK groups | `positions[sym].exposure_to_stressed` (made per-account by the join) |
| $ exposed | value × stressed share | computed in the projection join |
| Stop | "<d>% below" or "no stop" (warning tone) | stop distance per account+symbol from the stop snapshot already used by `portfolio.drivers[].stop_distance_pct` |
| Stance (desktop) | Hold / Watch closely / Trim review / Exit review / Residual | `positions[sym].label`; residual lots (below `positions.materiality`) read "Residual" |

**Stressed share, never double-counted:** sectors partition a position; themes overlap sectors. Stressed share =
min(1, max(sum of stressed sector shares, largest stressed theme share)). A fund's 9% technology with 5% semis is 9%,
not 14%.

#### 4 · Review now · ranked by $ at risk

1–5 review prompts, highest $ first. Each row: number, "<SYM> · <account>" + the reason, the $ value, and
**Review →** (≥44 px) to the existing page: stop items → `/v3/risk?tab=exposure&symbol=<SYM>`; data-conflict and
no-look-through items → `/v3/review?symbol=<SYM>`.

Item kinds (config `market_risk_policy.yaml` `home_review:`; thresholds there):

| Kind | Text | $ at risk | Trigger |
|---|---|---|---|
| `stop_near` | "stop d% below last" | position value | stop distance ≤ `stop_near_pct` (5.0) |
| `no_stop` | "no stop" | position value | material position, no working stop in that account |
| `stressed_exposure` | "s% in stressed groups" | $ exposed | `usd_exposed` ≥ `stressed_min_usd` (1000) |
| `data_conflict` | "ledger says stopped out <date>, holdings still show the position — confirm with the broker" | position value | a trade-ledger close for the account+symbol after the holdings `positions_built_at` |
| `no_lookthrough` | "no look-through (sector unknown)" | position value | `look_through.basis` in (`stock_unknown`, `fund_unknown`) and value ≥ materiality |

Footer: "Advisory only. Each link opens the existing Review or stop review. No order, size or stop level is implied."

#### 5 · Budget breaches

One row per account, breaches of the same account merged: `<account label> · <budget> <actual>% ($<actual $>) vs
<limit>% limit · drivers: <SYM $> …` Drivers sorted by $ desc, first three with $, then "+N".

Source: `portfolio.budget_breaches[]` (`scope`, `budget`, `limit`, `actual`, `unit`, `drivers`), joined to the account
label and account total by the projection. **Defect found:** the engine truncates `drivers` alphabetically to five, so
the largest unprotected holding can be missing from the list. The build sorts drivers by $ before truncating.

#### 6 · Multi-segment issuer split

For a held or watched issuer with an entry in `config/issuer_segments.json`: a stacked bar and one line,
"<group> $X (w%) · …", with "weights from <source>, as of <date>". The look-through, the sector table and the re-entry
`group_no_new_low` condition all use these weights. Without an approved entry the issuer stays a single-sector stock and
the line reads "segments not set — counted as 100% <sector>".

#### 7 · Why the score is N (moved, unchanged content)

v004's contributor lines, the not-measured line, "De-escalates if" and the two links (Open Risk →, Review stops →),
moved under the actionable sections.

## Data the projection must start passing through (build PR checklist)

`scripts/lib/market_risk_projection.py` already passes `sectors`, `shock_type`, `heatmap`, `positions`,
`reentry_watch`. It **strips** these, which the build must pass (or add):

1. `book.budgets[]`: keep `scope` (opaque id), `limit`, `actual`, `unit`, `ratio`, `level`, `drivers`, `book_share`
   (today only `budget`, `scope` = "account", `breached` survive).
2. `book.positions[]` (`portfolio.drivers[]`): keep `reason` (today `note` is always `None`).
3. `heatmap[]`: add `rs1` and `reason_unknown` from `sectors.groups[]` (`sectors.heatmap()` drops both).
4. `reentry_watch[sym]`: the engine must add `exit_price`, `exit_account_type`, `last_close`, `last_date`, `swing_low`,
   `invalidation_level`, `sma10`, `sma20`, `anchored_vwap` (short history), `pct_vs_exit`, `pct_vs_sma20`,
   `trend` (up/flat/down over 5 sessions), `verdict`, `stage1 {met, of, conditions[]}`,
   `stage2 {met, conditions[]}`, `earnings_warning`, `wash_sale_until`, `look_through`. Today the card carries only
   `conditions`, `met`, `of`, `exit_date`, `wash_sale_note`; `breakdown_close` and the closes are computed and dropped.
   Exit price comes from `trade_closed.sell_price` (latest close per symbol, account recorded).
5. New **`book_exposure`** block, built **in the projection (API side) from the holdings store**, never in the engine
   assessment: `{total_usd, cash_usd, invested_usd, stressed_usd, stressed_pct_book, stressed_pct_invested,
   largest_contributor {symbol, account_label, group, share}, groups {key: {usd, pct_book}}, unmapped [{symbol, usd,
   reason}], rows [{symbol, account_label, value_usd, pct_account, stressed_share, usd_exposed, stop_distance_pct,
   stance}], as_of, stale}`. Inputs: `portfolio_positions.load_store()` `holdings[]` (one row per account+symbol, cash
   rows by `is_cash`, nothing nested summed twice), `account_summaries[].display_name`, and the engine's per-symbol
   `positions[sym].look_through.groups`. `total_usd` must equal the Home "All accounts" total (`portfolio_totals.
   total_value`); the build asserts this in a test and shows "book total does not reconcile" instead of numbers when it
   does not.
   *Why API side:* the assessment feeds the CIO and model curation; position dollars and account identity are not
   cleared for an external provider (AGENTS.md §2A). The engine keeps symbols and shares only.
6. New `review[]` (section 4) and `scope_labels` (opaque scope id → account label, API side only).
7. **Engine fix:** `lookthrough.book_group_exposure()` averages shares equally per position ("equal per position, no
   amounts"). `heatmap[].book_exposure_share` is therefore not a share of the book: one fractional-share residual counts
   as much as the largest holding. The card never shows it; it shows `book_exposure.groups` (dollar-weighted).
8. **Engine fix:** look-through for every position, residuals included (they count toward dollars), and for every
   watched or exited symbol (re-entry `group_no_new_low` uses the weighted look-through, not the single main sector).

## Look-through: sources and gaps (audit 2026-11-01, counts only; symbols in the private review copy)

Order of sources (unchanged): fund factsheet weights (`config/fund_lookthrough.json`), then the `etf_holdings_snapshot`
top holdings for the AI share, then `symbol_profiles` sector for a stock — plus, new, `config/issuer_segments.json` for
a multi-segment issuer.

| Gap | Count today | Fix (build task) |
|---|---|---|
| Position not given a look-through because it is a residual lot (below materiality) | 14 holding rows | compute look-through for every row; materiality only hides stance and playbook |
| `stock_unknown`: no sector profile (one mutual fund, one small ETF) | 2 | add the two to `fund_lookthrough.json` from their factsheets (agent proposes, operator approves) |
| `fund_unknown` by design (bond fund) | 1 | show under "No look-through" as bonds; not an equity sector |
| Funds with factsheet sectors but no holdings snapshot → AI-basket share unknown | every held fund | build the `etf_holdings_snapshot` writer run (it is not built; the engine note says so) |
| A recent IPO with a stale fund entry under its ticker, treated as 100% one sector | 1 | `config/issuer_segments.json` entry |
| Communications and Real estate measured UNKNOWN ("insufficient history") although the sector ETF has daily closes in `market_ohlcv_bars` | 2 groups | engine fix in `sectors.py`: find which window is short and backfill; until then the card says "not measured — you hold $X" |

## `config/issuer_segments.json` (new; operator-owned weights)

```json
{
  "_comment": "Revenue-weighted segment look-through for multi-segment issuers. Weights are operator-approved; an agent proposes.",
  "issuers": {
    "<TICKER>": {
      "name": "<issuer>",
      "status": "PROPOSED | APPROVED",
      "segments": [
        {"segment": "<launch / aerospace>", "group": "industrials", "weight": 0.0},
        {"segment": "<satellite broadband>", "group": "comm", "weight": 0.0},
        {"segment": "<AI>", "group": "ai_basket", "weight": 0.0}
      ],
      "source": "<filing, section, period>",
      "as_of": "YYYY-MM-DD",
      "proposed_by": "<agent session>", "approved_by": "<operator ledger ref | null>"
    }
  }
}
```

- `lookthrough.exposure_for()` checks this file **before** `symbol_profiles` (after `fund_lookthrough.json`); only
  `status: APPROVED` entries are used. Sector-kind weights must sum to 1.0 ± 0.01; theme weights (`ai_basket`, `semis`)
  are extra and overlap a sector, as for funds. `basis` reads `segments (<source>, <as_of>)`.
- A PROPOSED entry is shown on the card as "segments proposed, not approved — counted as 100% <sector>" and is never
  used in a number.
- Stale: `as_of` older than `issuer_segments.stale_after_days` (config, proposed 120) shows "segments stale" and still
  uses them, with the date.
- The file is domain policy under `config/` (AGENTS.md §1: trading policy belongs to the operator); a PR adding or
  changing weights carries the source and waits for the operator.

## Backtest (spec only; build task)

Extend `scripts/market_risk_backtest.py` with `--reentry` over `tests/fixtures/market_risk_scenarios` (and the symbol's
own history for the base rate). For every stop-out-like breakdown (close `breakdown_drawdown_pct` below the 20-session
high and below the 20-session average), evaluate **Stage 1 and Stage 2 separately**, with the thresholds from config:

| Measure | Definition |
|---|---|
| Rebound captured, vs the low | (20-session-forward high − entry close) / (20-session-forward high − swing low) |
| Rebound captured, vs the 20-session high | entry close vs the pre-breakdown 20-session high |
| False-start rate | share of setups invalidated (close below the swing low) within `invalidation_sessions` (10) |
| Days from the low | median sessions from the swing low to the signal |
| n | setups per scenario and pooled |

Output: `docs/audits/REENTRY_STAGES_BACKTEST_<date>.json` and a one-page Markdown table per threshold set (volume ratio
0.8/1.0/1.2; group RS window 3/5/10; hedging ease 5/10/20%). The operator chooses thresholds from it; nothing is tuned
automatically. MBI_BEHAVIOR = 0: the backtest measures signals, never sizes.

## All config keys (nothing hardcoded)

`config/market_risk_policy.yaml`:

```yaml
reentry_watch:
  lookback_days: 30            # existing
  wash_sale_days: 30           # existing
  earnings_ahead_sessions: 5   # existing, now a warning only
  card: {recent_sessions: 5, max_rows: 5}
  stage1:
    volume_ratio_min: 1.0
    volume_avg_sessions: 20
    group_rs_sessions: 5
    hedging_peak_sessions: 5
    hedging_ease_pct: 10
    blocked_tiers: [ORANGE, RED]
  stage2: {confirm_ma_sessions: [10, 20], confirm_above_exit: true}
  short_history_anchor: swing_low_vwap
  verdict: {basing_min_sessions: 3, basing_band_pct: 3.0, invalidation_sessions: 10, trend_sessions: 5}
home_review: {max_items: 5, stop_near_pct: 5.0, stressed_min_usd: 1000}
issuer_segments: {path: config/issuer_segments.json, stale_after_days: 120}
```

## States

| State | What shows |
|---|---|
| Not evaluated · GREEN · BLUE · load error | Unchanged (v004): no card. |
| YELLOW, live / shadow | Card as above; SHADOW label in shadow mode. Collapsed on phone, expanded on desktop. |
| ORANGE / RED | v002 banner (tone fill, solid pill, 20 px score, **Acknowledge**) with the same verdict, exposure, top review item and sections 1–7. Collapsed on phone shows S1–S4 and Acknowledge. |
| Stale assessment (`as_of` older than `stale_after`) | v004 stale summary; no verdict, no dollars. Expanded: the explanatory line and the two links. |
| Holdings stale (holdings `data_as_of` older than the book window) | Verdict shown; exposure line reads "holdings last priced N h ago — dollar columns hidden; percentages shown". |
| Book total does not reconcile to All accounts | Exposure line reads "book total does not reconcile — dollars hidden"; percentages shown. |
| No stressed exposure | "Your exposure: $0 in stressed groups." Section 3 hidden; Review now keeps stop items. |
| Shock type absent | Verdict falls back to "Stressed: <groups>" from `sectors.stressed`. |
| No recent exits | Section 2 hidden; the "+N on watch" link stays when older ones exist. |
| Re-entry verdicts | Still falling · Basing · Early setup · Confirmed · Invalidated (badge tones above). |
| Data conflict | Review item with a `DATA CONFLICT` badge (ledger vs holdings). |
| Segment entry PROPOSED / stale | "segments proposed, not approved" / "segments stale (<date>)". |

## Phone (412 / 390)

One column; the card first. Collapsed (default) is the summary plus the top review item: measured 308 px at 412 × 915
and 327 px at 390 × 844 in the mockup; the rest of Home starts in the first screen. Not sticky; fixed chrome ≤15% of the
viewport. No sideways scroll (scrollWidth = 412 / 390 in the mockup, expanded and collapsed). Tables drop the "% book",
"% acct", "Account" and "Stance" columns on phone; the account shows under the symbol. ET times only. Lines wrap; never
truncated to "…".

## Tap targets (≥44 px; smallest measured 44 px at 1440, 412 and 390)

| Target | Size |
|---|---|
| Summary row / Details–Less toggle | full card width × ≥44 px |
| Top review item | full width × ≥44 px |
| Each "Review →" | ≥44 px high |
| "+N older exits on watch" link | ≥44 px high |
| Open Risk → · Review stops → | ≥44 px high |
| Acknowledge (ORANGE/RED) | ≥44 px high |

## Tokens (all existing; no new token)

`--bg-0`, `--bg-1`, `--bg-2`, `--border-color`, `--text-0`…`--text-3`; tones `--warning-color/-bg/-border` (YELLOW card,
NOT MEAS. chip, warnings, Basing), `--danger-color/-bg` (STRESS chip, Still falling / Invalidated, negative %),
`--success-color/-bg` (HOLDING chip, Early setup / Confirmed, positive %), `--elevated-color/-bg` (ORANGE banner, WEAK
chip), `--info-color` (links); `--radius-lg`, `--radius-md`, `--radius-pill`; type scale `TYPE.sm/base/md`; numbers in the
tabular mono face already used by the card.

## Mockups (private store, sha256 in status.json)

- `HomeV005DesktopYellow.dc.html` — desktop 1440, YELLOW, expanded.
- `HomeV005PhoneYellowCollapsed.dc.html` — phone 412/390, collapsed default.
- `HomeV005PhoneYellowExpanded.dc.html` — phone 412/390, expanded.
- `HomeV005DesktopOrange.dc.html` — desktop 1440, ORANGE (example tier on the same book).
- `HomeV005PhoneOrange.dc.html` — phone 412/390, ORANGE collapsed with Acknowledge.
- `HomeV005States.dc.html` — stale, no exposure, holdings stale, data conflict, the five re-entry verdicts.
- `canvas.json` — board layout.

## Removals / hides / moves (rule 4 — complete list)

- **Moved:** v004's contributor lines, not-measured line and "De-escalates if" move from the top of the expanded card to
  section 7 ("Why the score is N"), below the actionable sections. Nothing is removed.
- **Replaced:** v004's "Your book" panel (vulnerability, budget names, symbols with stop distance) is replaced by
  sections 3–5, which carry the same facts with dollars and accounts.
- **Moved behind a tap (phone only, as in v004):** everything below S4 while collapsed.
- Nothing else is removed, renamed or hidden.
