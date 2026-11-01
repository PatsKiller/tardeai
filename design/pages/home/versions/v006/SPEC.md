# Home v006 — SPEC (APPROVED 2026-11-01): Protect / Hedge / Rotate, tap-to-explain

Builds on the approved home/v005 (live component `MarketRiskActionable.tsx`, test id `home-market-risk-summary`).
Same slot, same states, same sections; v006 adds an action block under the verdict, an (i) explanation on every term,
and four fixes. **APPROVED by the operator on 2026-11-01: "I approve version 6."** Recorded from the message under
AGENTS.md §20, as for v002, v004 and v005. The build cites `Design: home/v006`.

The operator approved making this version ("Yes, version 0.0.6", 2026-11-01). That is approval to design it, not of
the design.

Mockups live in the private design store and are bound by sha256 in status.json (design/README.md rule 7). Market
figures are from the 2026-11-01 evaluation (Fri 10-30 close). Book values, symbols and accounts are placeholders
(`[ACCT-1]`, `[$xx,xxx]`, `[ST-D]`, `[ETF-A]`, `[EXIT-B]`). A local-only render with the operator's real numbers exists
outside the repo for his review. It is never committed.

## Why

The operator on the live v005 card, verbatim: "Can you use any improvement any tooltips? Does it show what's actionable?
I don't see it showing what I should be getting into. To hedge against these risks."

v005 shows what is hit and what you hold. It does not answer three questions in one place:

1. What do I protect?
2. Do I need a hedge?
3. Where is money going?

It also uses terms (STRESS, look-through, P/C OI, Stage 1…) with no explanation. v006 answers the three questions in
three short blocks and explains every term with one tap.

**MBI_BEHAVIOR = 0.** The card never shows any of these:

- a size, weight or share count;
- an order, or a stop level to set;
- a hedge size band;
- "buy X".

Protect links open the existing stop review. Hedge links open the Defense desk. Rotate links open the Rotation desk and
Best opportunities. The Defense desk's own hedge card carries a `size_band`; Home never shows it.

## What changes vs v005

| # | Change | Where |
|---|---|---|
| A | **Protect / Hedge / Rotate block** (`mr-actions`) directly under the verdict and exposure lines | expanded card, desktop and phone |
| B | **Collapsed digest** (`mr-actions-digest`): three one-line rows, Protect / Hedge / Rotate, replace v005's single "top review item" (S4) | collapsed card (phone default) |
| C | **Tap-to-explain (i)** on every term in the list below, with texts from one config file | everywhere on the card |
| D | **Folded stressed and not-measured groups** where you hold under a config amount: one line under the sector table | section 1 |
| E | Chip **HOLDING split** into **RESILIENT** (engine state RESILIENT) and **HOLDING** (NEUTRAL) | section 1 |
| F | **Multi-segment issuer label**: "segment weights pending approval — counted as Industrials" until an APPROVED entry exists | section 6 and the re-entry look-through line |
| G | v005 section 4 **Review now moves into Protect**; same items, same links, each with a consideration | see Moves |

Everything else in v005 is unchanged. That includes "Since you were stopped out", positions, budget breaches, "Why
the score is N", the states and the ORANGE/RED banner. The ORANGE/RED banner carries the same block A and digest B.

### A · Protect / Hedge / Rotate (`mr-actions`)

Desktop (≥1280 px): three columns, widths 1.25 : 1 : 1. Phone (≤820 px): stacked in the order Protect, Hedge, Rotate.
Each block has a title with an (i), a body, and links (≥44 px).

#### Protect (`mr-protect`): your largest review items, with a reason

Source: v005 `review[]`, ranked by $ at risk, unchanged. The first `home_actions.protect.shown` (3) items are shown,
then a "+N more: <sym> · <acct> (<short reason>) …" line listing the rest of the `max_items` (5).

Each item has two lines:

```
<SYM> · <account label>  <$ value>  (<pct_account>% of account)
<consideration>                                              Review stop →   (stop items)  /  Review →  (others)
```

The **consideration** is up to `home_actions.protect.max_clauses` (3) clauses, joined by "; ". The clauses are built
deterministically from facts the projection already has, in this order:

| Clause key | Text | Fact (source) |
|---|---|---|
| `stop_near` | "stop d% below last" | v005 review kind `stop_near` |
| `no_stop` | "no stop" | v005 review kind `no_stop` |
| `overnight` | "trades overnight now" | a print for the symbol in `market_quotes_extended` with `session = overnight`, newer than `market_risk_policy.yaml` `overnight` max age (the session is trading now). Shown only while the overnight session is open. |
| `concentration` | "one stock is P% of the account, far above the L% sector budget" | `budgets_detail[]` for this account, budget `single_sector_pct` or `growth_style_pct`, where this symbol is ≥ `concentration_min_share` (0.8) of `actual_usd` |
| `unprotected` | "P% of the account unprotected vs the L% budget" | `budgets_detail[]` budget `unprotected_pct`, when this symbol is the largest driver |
| `same_issuer` | "with the <acct> position, $X in <SYM> across N accounts" | two or more review rows with the same symbol; the sum of their values |
| `stressed` | "s% in stressed groups" | v005 kind `stressed_exposure` |
| `rebuy` | "re-bought <date> (wash sale occurred)" | `reentry_detail[sym].wash_sale.state = occurred` for this account |
| `no_lookthrough` / `data_conflict` | v005 text | v005 kinds |

- `pct_account` is added to each `review[]` row. The API join already computes it for `book_exposure.rows`.
- The clause texts are templates in config (`home_actions.protect.templates`), never in UI code.
- The texts are advisory facts. None names a stop level, a price to set, or an action verb such as "sell", "trim" or
  "tighten". The existing `brief_guard` action-verb rule runs on every built consideration in a test.

Footer: "Advisory only — each link opens the existing stop review; no order, size or stop level."

#### Hedge (`mr-hedge`): is a hedge needed for your book?

**One verdict chip, one plain line, one lane line, one link.** The verdict comes from the Defense desk's own
inverse-hedge stoplight. Home never re-derives a competing hedge thesis, the same rule `defense_inverse_stoplights.py`
follows.

| Verdict | Rule (first match) | Chip tone |
|---|---|---|
| UNKNOWN | the stoplight snapshot is missing, has a `config_error`, or is older than `inverse_stoplights.stale_calendar_days` (config, 4) | `--warning-*` |
| CONSIDER | any actionable-lane candidate (SH / PSQ / DOG / RWM) has THESIS GREEN | `--elevated-*` |
| WATCH | any candidate has THESIS AMBER (deteriorating, below materiality) | `--warning-*` |
| NOT NOW | every candidate has THESIS RED | `--success-*` |

The plain line always shows the book facts against the thresholds. **Every threshold is read from the existing config;
nothing new is introduced.**

- NOT NOW: "$X (Y% of book · Z% of invested) is in stressed groups. The Defense desk considers a hedge when one
  weakening sector is ≥ T% of invested, or N+ sectors lag. Now: <largest weakening sector> W%, k sectors lagging."
  - T = `config/defense_recommendations.json` `inverse_etf.trigger_book_pct` (10.0).
  - N = `inverse_etf.index_trigger_lagging_sectors` (4).
- CONSIDER: "<sector> is W% of invested and weakening — above the T% the Defense desk uses. <inverse>: thesis green ·
  entry <ENTRY label in plain words>."
  - The bounce-day rule is `inverse_stoplights.bounce_day_pct` (0.75).
- WATCH: "A trigger is active but your mapped exposure is below the M% materiality the stoplight uses."
  - M = `inverse_stoplights.materiality_exposure_pct` (8.0).

Lane line (12 px, `--text-2`): "Inverse lane SH · PSQ · DOG · RWM: <THESIS state in words> since <ET date of the last
THESIS transition>". The transition comes from `inverse_stoplight_transitions`. The line adds "(<inst> was <state>
<date>)" when a candidate changed within the last 5 sessions.

Link: **Defense desk →** `/v3/defense`.

**Data sources (found, read-only):**

| What | Where |
|---|---|
| Lights per candidate (THESIS / ENTRY / MANAGE / EXIT, label, reason) | `data/runtime/inverse_stoplights_latest.json`, written by `scripts/defense_inverse_stoplights.py`; served at `GET /api/v2/defense/inverse-stoplights` |
| Transition history (for "since <date>") | DB table `inverse_stoplight_transitions` (instrument, light, new_state, created_at); `book_precision._hedge_state` already reads it |
| Trigger (one weakening/lagging sector ≥ `trigger_book_pct` of invested, or ≥ N lagging) | `scripts/defense_recommendations.py` `inverse_etf()`; sector states and `book_pct` from `data/runtime/sector_momentum_latest.json` (served in `GET /api/v2/defense/posture` `momentum.rows`) |
| Thresholds | `config/defense_recommendations.json` `inverse_etf` and `inverse_stoplights` |

**Defect found: the Defense posture's `hedge_state` line is stale and contradicts the stoplight.**

- `GET /api/v2/defense/posture` `hedge_state` builds its line in `_defense_posture`, `scripts/api_v2.py` ~L16580–16627.
  It reads one `watch_alerts` row (`created_by='defense_hedge'`, note LIKE '%bounce%').
  - It has no `active`, thesis or date filter.
  - It does not check the stoplight.
  - Today it says "HEDGE: waiting for a bounce day (QQQ ≥ $720.48)".
- That alert level was set by the nightly playbook while the hedge card was live (PSQ ENTRY green 10-26/10-27). The
  alert last fired 10-26 and is still `active`.
- The stoplight turned THESIS RED on Fri 10-30 ("NO BEARISH THESIS") for SH, PSQ, DOG and RWM. The Defense
  recommendations snapshot from the same evening has no HEDGE card.
- `defense_recommendations.inverse_etf()` only refreshes the alert levels when a card is built. Nothing deactivates
  them when the trigger ends.
- Home v006 reads the stoplight, not `hedge_state`. The build PR adds two engine fixes to its checklist:
  1. `hedge_state` returns the stoplight THESIS when it is not GREEN.
  2. The `defense_hedge` bounce and take-profit alerts are deactivated when no HEDGE card is built.

  The second fix touches `watch_alerts` writes, so it is a separate reviewed PR. Alerts are notifications only, never
  orders.

#### Rotate (`mr-rotate`): where money is moving

The top `home_actions.rotate.max_groups` (3) groups that are leading SPY now, each on one row:

```
<Group>   +a% 1d  +b% 5d   · desk <Defense-desk momentum state> · you hold $X
```

- **Eligible:** `sectors.groups[]` of kind in `home_actions.rotate.kinds` ([sector, theme]) with state in
  `eligible_states` ([RESILIENT]), and both `rs1 > 0` and `rs5 > 0` (`require_positive: [rs1, rs5]`): beating SPY on
  both horizons.
  - When `leadership.groups[key].class` is measured, LEADERSHIP_CONFIRMED and LEADERSHIP_EMERGING are also eligible.
  - Every group with class LEADERSHIP_FADING or BOUNCE_ONLY is dropped.
- **Ranked by** `rank_weights` · (rs1, rs5): mean of the two, config `{rs1: 0.5, rs5: 0.5}`. Ties are broken by rs5.
- **Desk state:** the matching row of the Defense desk's sector momentum (`sector_momentum_latest.json`
  `rows[].state`: LEADING / IMPROVING / WEAKENING / LAGGING). It is a corroborating label from a second engine and is
  never used to rank.
- **You hold:** `book_exposure.groups[key].usd` (look-through dollars, v005).
- Footer: "Relative strength vs SPY, <ET date> close. Groups beating SPY on both 1 and 5 sessions — not a buy list."
- Links: **Rotation desk →** `/v3/rotation`, **Best opportunities →** `/v3/watch?tab=opportunities&preset=top5` (the
  Home "Best opportunities" target).
- **Nothing qualifies** (for example, a systemic selloff): "No group is beating SPY on both 1 and 5 sessions today."
  The links stay.

**Data sources (found, read-only):**

| What | Where |
|---|---|
| 1d / 5d relative strength and state per group | the engine's `sectors.groups[]`, already in the projection's `heatmap[]` (`rs1`, `rs5`, `state`) since v005 |
| Leadership class | `leadership.groups[]` (`scripts/lib/market_risk/leadership.py`), already passed through by `market_risk_projection.py`. Today every group is UNKNOWN "not enough history", the same cause as the Communications defect below. Rotate therefore ranks on rs1/rs5 alone until the history is backfilled. |
| Desk state | `data/runtime/sector_momentum_latest.json` (`scripts/sector_momentum_engine.py`); served in `/api/v2/defense/posture` `momentum.rows` |
| Rotation stances (ADD / WATCH / AVOID) | `scripts/lib/market_risk/rotation_advice.py` exists. Home does **not** show its ADD stance ("never buy X"); the Rotation desk does. |

At the evaluation the mockup uses, all three top groups were RESILIENT on both horizons and LEADING on the Defense
desk.

### B · Collapsed digest (`mr-actions-digest`)

Collapsed (phone default) shows S1–S3 as in v005, then three rows, each ≥44 px and each a link:

```
PROTECT  <SYM> · <acct> ($X) — <first clause>                 →   (first Protect item)
HEDGE    <VERDICT> — Y% of book in stressed groups            →   /v3/defense
ROTATE   <G1> +a%/+b% · <G2> … · <G3> … (1d/5d vs SPY)        →   /v3/rotation
```

Measured in the mockup: the collapsed card is 375 px at 412 × 915 and 395 px at 390 × 844. v005's was 308 / 327 px.
The rest of Home still starts in the first screen. The card is not sticky.

### C · Tap-to-explain

- A small (i) button follows each term: a 16 px glyph with a 44 × 44 px hit area. It is a `<button>` with
  `aria-label="What is <term>?"`.
- Phone: tapping opens a **bottom sheet** (`role=dialog`, `aria-modal`) with the term, one or two sentences and a
  full-width **Close** (≥44 px).
- Desktop: the same content opens as a centred dialog.
- Esc, Close or tapping the scrim closes it. Focus returns to the (i).
- It is not hover-only; there is no `title`-only explanation.
- A definition is not a list item. The full-screen-sheet rule for list → detail does not apply.

Terms (every one gets an (i) wherever it appears on the card):

STRESS · WEAK · RESILIENT · HOLDING · NOT MEAS. · look-through · % book · Stressed % · $ exposed · P/C OI · CARRIED · SHADOW ·
Stage 1 · Stage 2 · Invalidates below · budget breach · vulnerability · Hedge needed? · vs SPY (Rotate) · Protect.

**One glossary config, editable without code:** `config/market_risk_glossary.json` (new, build task).

```json
{"terms": {"<key>": {"label": "<as shown on the card>", "text": "<one or two plain sentences; {config_key} placeholders filled from config>"}}}
```

Proposed texts (operator may edit):

| Key | Text |
|---|---|
| stress | This group fell much more than it usually does and lagged SPY, over the last 5 sessions or in one day. "Usually" is measured against the group's own past year, not a fixed percentage. |
| weak | Falling more than usual and lagging SPY, but not as far as STRESS. |
| resilient | Beating SPY by more than usual for this group, or rising while SPY falls. It says where money is going now, not that it will keep going there. |
| holding | Moving in line with the market: neither stressed nor clearly beating SPY. |
| not_measured | The engine does not have enough daily closes for this group yet, so it shows no state instead of guessing. The dollars you hold are still shown. |
| look_through | A fund is counted by what it holds, not by its name: a dividend ETF that is 9% technology puts 9% of its value in Technology. A stock is counted by its sector, or by its business segments once you approve them. |
| pct_book | Share of everything you own across all accounts, cash included. |
| stressed_pct | How much of this position sits in groups marked STRESS or WEAK, after look-through. Themes overlap sectors, so they are never added on top. |
| usd_exposed | Position value times its stressed share: the dollars that are in the groups being hit. |
| pc_oi | Put/call open interest: open put contracts divided by open call contracts on the index. Far above its usual level means traders are paying for protection. |
| carried | The market is closed and this reading rests on Friday's data. It is shown so you can see it, but it does not page you. |
| shadow | The engine is evaluated but not allowed to send alerts yet. What you see is what it would have said. |
| stage1 | An early sign the drop may be over: a higher low, then two green closes on normal volume, with its groups no longer making new lows. Early and more likely to fail than Stage 2. |
| stage2 | Confirmation: a close back above the 10-day or 20-day average, or above the price you were stopped out at. |
| invalidates_below | The lowest close since you exited. A close under it cancels the early setup and the count starts again. |
| budget_breach | An account is over one of your risk budgets, for example more than {single_sector_pct}% in one sector. It is a prompt to review, not an instruction. |
| vulnerability | A 0–100 score of how exposed the book is right now: concentration, stops close to price, positions with no stop and upcoming earnings. Higher means more exposed. |
| hedge_verdict | Read from the Defense desk. It considers an inverse-ETF hedge only when one weakening sector is at least {trigger_book_pct}% of your invested money, or {index_trigger_lagging_sectors} or more sectors are lagging. |
| rotate_rs | The group's return minus SPY's over the same 1 or 5 sessions. +2% means it beat SPY by 2 points. It shows where money is moving, not what to buy. |
| protect | Your largest positions with something to review: a stop close to the price, no stop, or an account over a budget. Each one opens the existing review page. Nothing is placed or changed from here. |

**A test checks the glossary:**

- every (i) key on the card exists in the file;
- every text is ≤ 2 sentences and ≤ 320 characters;
- every `{placeholder}` resolves from config;
- no text contains an action verb (the `brief_guard` rule).

### D · Folded groups

In section 1, STRESS or WEAK groups, and NOT MEAS. groups, where you hold less than
`home_actions.sectors.fold_below_usd` (100) are removed from the table. They are named in one line under it:

"Also stressed, you hold under $100: <group> ($x). Not measured, under $100: <group> ($x)."

The sort and every other row are unchanged from v005. On the evaluation, the AI basket theme and Real estate fold.

### E · Chip split

`heatmap[].state` RESILIENT shows **RESILIENT** (`--success-*`), and NEUTRAL shows **HOLDING** (`--text-2` on
`--bg-2`). v005 showed HOLDING for both, which hid which groups were actually beating SPY.

### F · Multi-segment issuer label

v005 section 6 and the re-entry look-through line say, for an issuer with no APPROVED entry in
`config/issuer_segments.json` (missing or PROPOSED): **"segment weights pending approval — counted as <sector>"**. The
sector is the stock's `symbol_profiles` sector; today that is Industrials. With an APPROVED entry, the stacked bar and
"<segment> → <group> $X (w%)" line from v005 are shown, with source and as-of. The file ships empty today, so the label
shows.

## Engine fix: Communications (and Real estate) marked UNKNOWN "insufficient history" while XLC has data

**Found (read-only, 2026-11-01):**

- `sectors.measure()` (`scripts/lib/market_risk/sectors.py` ~L126) marks a group UNKNOWN when its index has fewer than
  60 closes.
- Closes come from `reader.daily_bars()` (`scripts/lib/market_risk/reader.py` L202). It reads `market_ohlcv_bars`
  (timeframe `daily`) and fills gaps from `market_quotes` (source `alpaca`, close = the next day's `prev_close`).
- **`market_ohlcv_bars` has no daily rows at all for XLC, XLRE or XLK**, and SPY's and XLP's daily rows stop at
  2026-10-09. The daily-bars writer (`scripts/market_data_snapshot_loader.py`) does not cover the sector group symbols
  and has stopped.
- The engine therefore runs on Alpaca quote closes alone. Those start 2026-08-03/04 for most sector ETFs (64–65
  sessions, just over the minimum) but **2026-08-06 for XLC and XLRE (59 sessions)**. Their usable closes fall under
  60, so they are UNKNOWN.
- Meanwhile the Defense desk's sector momentum reads its own price history and measures XLC: rs5 −4.82%, rs20 −7.62%
  vs SPY at the same close.
- **Communications is probably a hidden WEAK or STRESS group** in which the book holds dollars. The leadership
  detector is UNKNOWN for every group for the same reason: it needs 120+ sessions.

Fix (build checklist; engine PR, no UI):

1. Backfill `market_ohlcv_bars` daily for every symbol in `market_risk_policy.yaml` `sectors.groups[].symbols`,
   `factor_symbols`, the benchmark and `leadership` groups, for `z_window_sessions + 30` (282) sessions. Use the existing
   daily-bars broker (`lib.data_broker.daily_bars`); no new fetch path (AGENTS.md: CC data broker only).
2. Restore the daily writer so those symbols stay current. Name the lane in the lane registry.
3. A test: a group symbol with quote-only history below the minimum but daily bars available is measured, not UNKNOWN.
4. Until fixed, the card keeps "not measured" with the reason, now "not measured — engine fix pending". The (i) text
   explains it.

Note: XLC crosses 60 quote sessions on its own within a few sessions. That masks the defect without fixing it, because
the z-scores still use about 60 sessions instead of a year.

## Data the projection must add (build checklist; API side, no engine assessment change)

1. `review[]`: add `pct_account`, and `clauses[]` (key + filled text) built from the table under Protect.
2. New `hedge` block, built API-side from the stoplight snapshot, the transitions table and the two config files:
   `{verdict, line, lane_line, since, as_of, stale, thresholds {trigger_book_pct, index_trigger_lagging_sectors,
   materiality_exposure_pct}, largest_weakening {label, pct_invested}, lagging_count}`. The block never includes
   `size_band`, `levels`, `playbook` or `dollars_by_account`. A test asserts their absence.
3. New `rotate` block: `{groups [{key, label, rs1, rs5, state, leadership_class, desk_state, usd}], as_of, none_reason}`.
4. `glossary`: the resolved texts (or the UI reads `GET /api/v2/market-risk/glossary`; one source either way).
5. `heatmap[].chip`: RESILIENT vs HOLDING, from `state`.
6. Folded groups: `sectors_folded [{key, label, state, usd}]`, chosen by `fold_below_usd`.
7. Issuer segment status per symbol: `segments {status: approved | pending | none, sector_fallback}`.

## Config keys (all new keys in `config/market_risk_policy.yaml`; nothing hardcoded)

```yaml
home_actions:
  protect:
    shown: 3                       # items shown in the block; the rest (to home_review.max_items) in "+N more"
    max_clauses: 3
    concentration_min_share: 0.8   # symbol share of a budget's actual $ before "one stock is P% of the account"
    templates:
      stop_near: "stop {d}% below last"
      no_stop: "no stop"
      overnight: "trades overnight now"
      concentration: "one stock is {p}% of the account, far above the {limit}% sector budget"
      unprotected: "{p}% of the account unprotected vs the {limit}% budget"
      same_issuer: "with the {other_acct} position, {usd} in {sym} across {n} accounts"
      stressed: "{s}% in stressed groups"
      rebuy: "re-bought {date} (wash sale occurred)"
  hedge:
    source: defense_inverse_stoplights   # thresholds stay in config/defense_recommendations.json; none duplicated here
    lane_change_sessions: 5
  rotate:
    max_groups: 3
    kinds: [sector, theme]
    eligible_states: [RESILIENT]
    eligible_leadership: [LEADERSHIP_CONFIRMED, LEADERSHIP_EMERGING]
    exclude_leadership: [LEADERSHIP_FADING, BOUNCE_ONLY]
    require_positive: [rs1, rs5]
    rank_weights: {rs1: 0.5, rs5: 0.5}
  sectors:
    fold_below_usd: 100
glossary: {path: config/market_risk_glossary.json, max_chars: 320}
```

## States (additions to v005; every v005 state is unchanged)

| State | What shows |
|---|---|
| Hedge NOT NOW / WATCH / CONSIDER / UNKNOWN | verdict chip and line as above (States board) |
| Stoplight stale or missing | UNKNOWN chip: "Defense stoplight last ran <ET>; no verdict until it runs again." The link stays. |
| Rotate: nothing qualifies | "No group is beating SPY on both 1 and 5 sessions today." The links stay. |
| Rotate: leadership measured | the row adds "leadership confirmed / emerging" |
| Holdings stale / book does not reconcile (v005) | Protect shows percentages and clauses without dollars; Hedge shows percentages only; Rotate shows "you hold" as "—" |
| Communications measured (after the engine fix) | a normal row with its state; the fold rule applies like any other group |
| Issuer segments APPROVED | stacked bar and split line, source and as-of |
| Glossary sheet open | bottom sheet (phone) or dialog (desktop) |

## Phone (412 / 390)

- One column. The action blocks are stacked.
- Sector table headers read "1d" and "5d" on phone. The "% book", "% acct", "Account" and "Stance" columns are hidden as
  in v005. The "not measured" cell wraps.
- No sideways scroll. Measured scrollWidth = 412 / 390 in the mockup, collapsed, expanded and with the sheet open.
- ET times only. Lines wrap, never "…".

## Tap targets (≥44 px; smallest measured 44 px at 1440, 412 and 390)

| Target | Size |
|---|---|
| Each (i) | 44 × 44 hit area (16 px glyph) |
| Digest rows (Protect / Hedge / Rotate) | full width × ≥44 px |
| Review stop → / Review → | ≥44 px high |
| Defense desk → · Rotation desk → · Best opportunities → | ≥44 px high |
| Sheet Close | full width × 44 px |
| v005 targets | unchanged |

## Tokens (all existing; no new token)

As v005. The verdict chips use `--success-*` (NOT NOW), `--warning-*` (WATCH, UNKNOWN) and `--elevated-*` (CONSIDER).
The sheet uses `--bg-2`, `--border-color` and `--radius-lg`.

## Mockups (private store, sha256 in status.json)

- `HomeV006DesktopYellow.dc.html`: desktop 1440, YELLOW, expanded.
- `HomeV006PhoneCollapsed.dc.html`: phone 412/390, collapsed with the digest.
- `HomeV006PhoneExpanded.dc.html`: phone 412/390, expanded.
- `HomeV006PhoneGlossary.dc.html`: phone, the (i) sheet open on STRESS.
- `HomeV006States.dc.html`: Hedge CONSIDER / WATCH / UNKNOWN, Rotate nothing-qualifies, Communications measured,
  issuer segments APPROVED.
- `canvas.json`: board layout.

## Removals / hides / moves (rule 4: complete list)

- **Moved:** v005 section 4 "Review now" moves into the Protect block. The items, ranking, links and footer are the
  same. Three are shown, and the rest of `max_items` is on a "+N more" line naming each.
- **Replaced (collapsed only):** v005's single top review item (S4) is replaced by the three-row digest. Its first row
  is the same item.
- **Hidden behind a line:** stressed / not-measured groups where you hold under `fold_below_usd` leave the sector
  table and are named in one line under it.
- **Renamed:** the chip HOLDING becomes RESILIENT for groups whose state is RESILIENT. NEUTRAL keeps HOLDING.
- Nothing else is removed, renamed or hidden. "Since you were stopped out" is unchanged.
