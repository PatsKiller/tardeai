# Home v007 — SPEC (PROPOSED): context, clocks, tap-to-explain, phone

Design `DSN-20261031-market-risk-ui` · base **v006 (APPROVED 2026-11-01)** · operator request 2026-11-02
Source of the request: `persistent-state/handoffs/SPEC_HOME_MARKET_RISK_CARD_V7_20261102.md` (verbatim quotes there).
**Status: PROPOSED. Nothing is built from this document until the operator approves it in Approvals → Designs.**

## Why

The v006 card answers "how risky is the market" but not "and what does that mean for what I hold, right now". The
operator's words: *"it's not giving us the current price points. It's not telling us the current catalyst … Shouldn't
we get a little bit more information and context here?"* and, for this version, *"look at everything else on the card
that could be enhanced … Also implement tooling tips where appropriate and make sure this is all mobile responsive."*

Three failures make the card hard to trust rather than hard to read:

1. **Context is missing.** Rows say *what* is at risk, not *when it was measured*, *what it costs now*, *why it is
   listed* or *what would clear it*.
2. **Clocks are mixed and invisible.** The card mixes a 20:00 risk read, a "Mon close" rotation read, a 17:35 options
   read and a 19:45 extended-hours read under one as-of line. A reader cannot tell which number is how old.
3. **Terms are undefined.** The remaining jargon (carried, look-through, heat, R:R, wash sale, P/C OI ×median, RS pts,
   STRESS/WEAK/HOLDING/RESILIENT) is still un-explained on the card v006 left behind.

## What changes vs v006

| area | v006 | v007 |
|---|---|---|
| clocks | one "as of" line under the verdict | **each section states its own as-of**; a stale section is amber and says so |
| header | tier + score + categories that confirm | + **what changed today** (sparkline, ±points, which categories moved), **"what this means for you"**, next evaluation time |
| Protect / Hedge / Rotate | one flat block | three **collapsible** sections on phone, each with a one-line collapsed summary; desktop unchanged in structure |
| every row | label + amount | + **current price, day change, distance in % and $**, why listed, what clears it |
| glossary | 24 keys | + the remaining terms, one shared source (`config/market_risk_glossary.json`), no duplicated prose |
| stopped-out list | entry + reasons | current price + session + time, since-exit $/%, distance to invalidation and Stage-2 triggers, headlines, CIO stance with age, volume vs 20-day, since-exit sparkline |
| score | the categories that contribute | **all 9 categories** with OK / WARN / STRESS / not measured and their as-of |
| phone | stacked | each section collapsible with sticky header; tables become stacked rows under 600 px |

Nothing is removed. Every v006 element survives, some inside a collapsed section or behind an ⓘ.

## 0 · Global rules

- **G1 — One glossary, tap-to-explain.** Every term in the v7 request list gets an ⓘ that opens the same glossary
  panel pattern v006 introduced (keyboard focusable, `aria-expanded`, Escape closes, 44 px target). Texts come from
  `config/market_risk_glossary.json`; v007 **adds keys, never copies text**. A term with no key renders no ⓘ (it is
  a content bug caught by the glossary test, not an empty popover).
- **G2 — Every number shows its clock.** Each section header carries its own `as of <time> <zone> · <source>`. A
  section whose source time is older than its declared cadence renders an **amber "stale" chip with the age** and the
  header keeps the true time — stale is never hidden and never replaced by "now".
- **G3 — Advisory only.** The card never shows a size, an order, or a stop *level to place*. Distances are described
  ("1.8% above your stop"), never phrased as instructions. The existing advisory rail on the card is unchanged.
- **G4 — Phone first.** 412 and 390 are the acceptance widths; no horizontal page scroll; tap targets ≥ 44 px.
- **G5 — Nothing removed (rule 4).** Restructure happens behind collapsible sections; the v006 text remains reachable.

## 1 · Header (tier + score)

- **"What changed"**: a sparkline of today's score readings (e.g. 50 → 41 → 71 — real points only, no interpolation)
  with the delta since the previous evaluation in points, and the names of the categories that moved. When there is a
  single reading, show it as one point and say "first reading today" — never draw a line through one point.
- **"What this means for you"**: one plain-English sentence (exposure sitting in stressed groups, protection gaps).
  Data from the same projection; no new inference in the UI.
- **Acknowledge** keeps its v006 behaviour and gains a tooltip stating exactly what it does: silences repeats for this
  episode; it does not change the tier and does not clear anything.
- **Next evaluation** time (from the section's declared cadence), so the reader knows when this goes stale.

## 2 · Protect

Each row gains, in this order: **current price + day change** (with session label: regular / extended / prior close),
stop status **in plain words** ("stop resting at the broker, not yet active at the exchange" replaces *broker resting ·
pending activation*), **distance to the stop in % and $**, and **why it is listed** (one clause). Rows sort by dollars
at risk, as in v006.

**Account % denominators are named.** The percentage appears twice on Home with different bases today. v007 states the
basis on the row (`% of invested` / `% of account`) and uses one basis per section.

## 3 · Hedge

Show **progress toward each hedge trigger** as a small bar with the two numbers ("Technology 4.8% of invested — trigger
10%"; "1 of 4 sectors lagging"). Show today's move for the hedge instruments held (SH / PSQ / DOG / RWM) with the same
session label rule as §2. No progress value is inferred when the denominator is missing: the bar is replaced by the
sentence that names the missing input.

## 4 · Rotate + sectors

- Leaders and laggards show **what you hold in each** (names + weight), a trend arrow, and the existing *"not a buy
  list"* caveat as a tooltip on the section header, not as small print.
- Tapping a group expands its **members you hold** (and nothing you do not hold).
- Status chips (STRESS / WEAK / HOLDING / RESILIENT) get glossary keys; the table becomes stacked rows under 600 px.

## 5 · Since you were stopped out

**The bug ships first and separately** (it is not gated on this mockup): the row's "now" is **today's close after
16:00 ET, or the live/last price with its session label** — never Friday's close on a Monday. Acceptance test in
§Acceptance.

Enhancements on top of the fix: current price + session + its time; today's change; since-exit $ and %; distance to
invalidation and to each Stage-2 trigger in $ and %; the latest one or two **guarded** headlines with their own time;
next earnings or known event; CIO stance + conviction + a one-line reason **with its age**; today's volume vs its
20-day average; a **since-exit sparkline** with the exit price and the invalidation level marked on it. The long SEC
citation collapses into the row's ⓘ.

## 6 · Positions in stressed groups

Add **day change** and **stop distance** to each row, and name the source of a "trim review" (CIO record or curator)
with its age in a tooltip. Tapping a row opens the position detail.

## 7 · Budget breaches

One plain-English line per breach plus **what clears it** (sell down, reclassify, or an operator decision). Add the
operator path **"intentional — stop flagging until <date>"**, recorded as an operator decision with the date and the
reason, and shown on the row while it is in force. The card must never clear a breach on its own.

## 8 · Multi-segment issuer

A short summary stays visible ("two segments: hardware 78%, services 22%"); the citation (10-Q, accession, notes)
lives behind the row's ⓘ.

## 9 · Score breakdown and "De-escalates if"

- Show **all nine categories**, each with a status chip (OK / WARN / STRESS / **not measured**) and its own as-of —
  not only the four that contribute.
- Each category has a tooltip stating what it measures and its thresholds (glossary keys).
- Odd-but-correct readings get a plain-English note (e.g. *"QQQ −4.8% while VIX −0.1% — the index fell without the
  fear gauge rising; treat the calm reading with care"*), sourced from the projection, never computed in the UI.
- **"De-escalates if"** is rewritten as progress in words: *"Drops to YELLOW when the score is below 60 (now 71) AND
  fewer than 4 categories warn (now 4)."*

## Data the projection must add (Part A build checklist; no engine assessment change)

1. `review[].price` + `price_session` + `price_as_of` for Protect and the stopped-out rows.
2. `review[].distance_to_stop_pct` / `_usd`, and the stop's own as-of.
3. `score_history_today[]` (time + score), `delta_points`, `categories_moved[]`.
4. `next_evaluation_at`, per-section `as_of` + `cadence` (so the UI can mark stale without guessing).
5. `stopped_out[]`: since-exit $/%, distance to invalidation and each Stage-2 trigger, volume vs 20-day, guarded
   headlines with times, CIO stance/conviction/reason + age, next event.
6. `hedge.progress[]` with numerator, denominator and the missing-input reason when unavailable.
7. `categories[].status` + `as_of` for all nine, including `not_measured` with the reason.
8. `breaches[].clears_if[]` and any operator "intentional until" record.
9. `rotate.groups[].held_members[]`.

## Config keys (all new text in `config/market_risk_glossary.json`; thresholds in `config/market_risk_policy.yaml`)

`glossary.carried`, `glossary.repeat`, `glossary.acknowledge`, `glossary.stressed_group`, `glossary.look_through`,
`glossary.theme_overlap`, `glossary.unprotected_budget`, `glossary.heat`, `glossary.rr`, `glossary.stage_1`,
`glossary.stage_2`, `glossary.invalidates_below`, `glossary.wash_sale`, `glossary.pc_vol`, `glossary.pc_oi`,
`glossary.pc_median`, `glossary.rs_points`, `glossary.window_20d`, `glossary.window_10d`, `glossary.status_stress`,
`glossary.status_weak`, `glossary.status_holding`, `glossary.status_resilient`, `glossary.broker_resting`.
Nothing is hardcoded in the component; a missing key fails the glossary test rather than rendering a blank panel.

## States (every section: never blank)

`OK` · `STALE` (amber chip, true time kept) · `NOT_MEASURED` (names the missing input) · `UNAVAILABLE` (names the
failed source). v006's states are unchanged; v007 adds the per-section stale rule and the not-measured reason.

## Phone (412 / 390) and tap targets

Each section is a collapsible card; collapsed it shows a one-line summary (tier word, score, worst item) and its stale
chip. Sticky section header while scrolling inside a section. Tables become stacked rows under 600 px. No horizontal
page scroll at 412 or 390. Every ⓘ, chip, row and button ≥ 44 px.

## Tokens

All existing design tokens; no new colour. Amber is the existing warning tone; stale chips use it at the same contrast
props v006 shipped.

## Acceptance

- The operator approves this mockup in Approvals → Designs; only then does Part C build it.
- Phone screenshots at 412 and 390 with a tooltip open and a section collapsed.
- Every value shows a time and a source; no section renders blank.
- **Tests:** the stopped-out "now" bug (after 16:00 ET the row uses today's close; before it, the live/last price with
  its session label; a Monday morning never shows Friday's close); glossary keys resolve for every ⓘ; a stale section
  renders amber with its age and its true time; a category with `not_measured` shows its reason; "De-escalates if"
  renders both clauses with live numbers.
- Nothing removed (rule 4 list in `status.json`: `removals: []`).
