# CENSUS PART 2 — The Command Center / operator surface

**Authority:** `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0` · `MBI_COGNITION=1`
**Scope:** the operator surface only. Backend modules, scripts, entrypoints, schemas, stores
and scheduled jobs are PART 1's and are not censused here.
**Nothing in this wave was deleted, refactored, consolidated, rewired or archived.** This
document is the only artifact produced.

Every claim carries `[VERIFIED]` (command run, output quoted) / `[CODE]` (source read) /
`[DOC-CLAIM]` (asserted, unconfirmed). An untagged claim is a defect.

---

## 0. Measurement environment — and two corrections to the brief

**The brief's environment section is wrong on two points. Per the standing rule that the
finding wins, I recorded the finding and censused what is actually served.**

| brief said | measured | tag |
|---|---|---|
| served release `1306132c-main-exact-phase2-20260830-151435` | at census start `a9389f67-...-191046`; **it changed under me mid-census** to `865a4a1d-...-191554` | `[VERIFIED]` |
| repo worktree main tip `1306132c` | `/home/johnclaw/r20-r24-exact-main-deploy` local `main` = `79a3f573`; `origin/main` = `865a4a1d`; `1306132c` is neither | `[VERIFIED]` |

```
$ readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
   at 2026-08-30T23:15:58Z  .../a9389f67-main-exact-phase2-20260830-191046
   at 2026-08-30T23:17:55Z  .../865a4a1d-main-exact-phase2-20260830-191554
$ cd /home/johnclaw/r20-r24-exact-main-deploy
$ git rev-parse main        -> 79a3f573e29eddff7c1b1273c600652cac583ad8
$ git rev-parse origin/main -> 865a4a1ddfdaacb636c450bb24dcf8e0558b7f83
$ git merge-base --is-ancestor a9389f67 79a3f573 ; echo $?   -> 1   (deploy worktree is BEHIND what is served)
```
`[VERIFIED]`

**Consequence for anyone reading this document:** the platform was being promoted to roughly
every 5–15 minutes during the census window `[VERIFIED]` —

```
$ ls -lt --time-style=full-iso /home/johnclaw/trade-ai-releases/portfolio-server/ | head -8
2026-08-30 19:16:44  865a4a1d-main-exact-phase2-20260830-191554
2026-08-30 19:11:29  a9389f67-main-exact-phase2-20260830-191046
2026-08-30 18:44:40  72371619-main-exact-phase2-20260830-184401
2026-08-30 18:32:07  f0a540a1-main-exact-phase2-20260830-183105
2026-08-30 18:22:30  2118ba24-main-exact-phase2-20260830-182141
2026-08-30 18:16:06  18e7884e-main-exact-phase2-20260830-181518
```

so **every row below carries the pin it was read from.** Two rows measured under different
pins are not in conflict unless they share one. Unless stated otherwise a row was read from
pin `865a4a1d` at `data_as_of 2026-08-30T23:17:45.551861+00:00`.

Reads were taken from the **live server on port 7777**, never from a local recomputation,
per the brief's warning that several collectors read Postgres and return `[]` from an
ad-hoc shell. `[VERIFIED]` — `/api/v3/cio/home` = 200, `/v3/cio` = 200.

Interpreter: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python`.
Source read from the **served release** `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`,
not from a checkout, because the checkout is behind what is served.

Nothing was promoted, deployed, merged or sent. No Telegram message was emitted.

---

## 1. Headline findings

1. **The only block on the surface labelled `A` (agent judgment) contains no judgment.**
   `case_summaries` — 10 items, `class: "A"`, banner `A-context` — is two f-strings. Zero
   research content, zero symbol-specific text. §5.
2. **Every cash number on the surface rests on broker balances 16–27 days old, and is
   stamped with the composition timestamp.** 93% of the cash total is as-of `2026-08-14`.
   `cash_letter.as_of` says `2026-08-30T23:17:45`. §4.
3. **19 of 26 payload blocks carry no `as_of` at all** — the brief's `[DOC-CLAIM]` said they
   "inherit a composition timestamp"; measurement says worse: they carry no timestamp of any
   kind. Only **one** block carries a genuinely independent one. §3.
4. **7 of 12 fields on all 25 live decision cards are byte-identical**, including
   `counter_evidence`, `next_review` and `confidence`. Confirmed by constructed-input diff,
   not by reading code. §5.
5. **`decision_field_parity.ok = false` is a permanently-red gate**: the field it reports
   missing is `recommended_delta_usd`, which `MBI_BEHAVIOR=0` forbids the system to emit. §7.
6. **The system has a provenance-labelling mechanism (`[T]`/`[D]`/`[A]`) and it reaches
   3 of 375 prose fields.** §6.
7. **24 fields of generated prose are labelled `writer: "migration:deterministic"`** — the
   brief predicted this exactly and my own first pass missed it. Seven of the nine generated
   narratives are truncated mid-word at 600 characters on the operator surface. §10.1.
8. **Both provenance markers are wrong, in opposite directions**: `deterministic` on generated
   prose (24 fields), `A`/agent-judgment on f-strings (11 fields). §10.4.
9. **`model_provider: "deepseek-v4-flash"` is a hardcoded literal** on a producer that makes
   no model call, rendered beside `quality_state: AVAILABLE` and
   `promoted_research_count: 0`, behind a bare `except: pass`. §9.1.

**Corrections I made to my own work during this census**, kept in per the standing rules:
I recorded the cash-guidance constant as not-found (it exists, §5.4); I claimed
`model_provider` was absent (it is present ×4, §9.1); and I reported count (a) as zero from a
marker census (it is 27, §10.1–10.2). In every case the finding won.

---

## 2. What the operator surface is

`[VERIFIED]` The served process is
`/home/johnclaw/trade-ai-releases/portfolio-server/865a4a1d-.../scripts/portfolio_server.py`
(pid 217310, started `2026-08-30T19:16:46-04:00`).

`[VERIFIED]` Distinct `/api/v2/*` + `/api/v3/*` path literals across the nine api modules:

```
$ for f in api_v2 api_v3_cio api_v3_advisory api_v3_intelligence api_v3_maturity \
    api_v3_watch_commands api_v3_watch_rockville api_v3_watchlist_intelligence \
    api_v3_data_broker_watch; do
    grep -oE '"/api/v[23]/[a-zA-Z0-9_/{}.-]*"' $C/scripts/$f.py; done | sort -u | wc -l
981
```

**981 declared API paths.** The `/api/v3/cio/*` family is not among these literals — those
paths are assembled by prefix dispatch in `portfolio_server.py`, which is why a filename or
literal grep under-reports them. `[CODE]`

`[CODE]` `portfolio_server.py:712` `_stamp_serving()` — a genuinely good honesty guard, and
worth naming because it is the counter-example to most of this document. Every `/api/v3`
JSON response is stamped with a `_serving` block naming the process start, the pin loaded in
memory, the pin on disk, and `pin_match`. Its docstring states the failure it was written
for: *"Stops a 2-day in-memory overlay being served as current with no indicator."*
`[VERIFIED]` live value: `pin_match: true`, `loaded_pin == current_pin_sha == 865a4a1d`.

This is the one mechanism on the surface that reliably tells the operator whether what they
are looking at is current. It covers the *release*, not the *data*.

---

## 3. `as_of` ownership — the freshness census

**Question:** does each payload block carry its own `as_of`, or inherit the composition
timestamp? The brief carried this as `[DOC-CLAIM]`: *"19 of 31 payload blocks were previously
found to inherit a composition timestamp."*

**Measured independently.** `[VERIFIED]`, pin `865a4a1d`, composition
`as_of 2026-08-30T23:17:45.551861+00:00`:

| category | count | meaning |
|---|---|---|
| carries its OWN `as_of`, differing from composition | 6 | |
| `as_of` **equals** the composition timestamp exactly | 1 | `cash_letter` |
| **no `as_of` field of any kind** | **19** | |
| total dict blocks | 26 | (36 top-level keys, 26 of them dicts) |

**The count 19 reproduces. The characterisation does not.** Those 19 blocks do not inherit a
composition timestamp — they carry **no timestamp at all**, which is strictly worse, because
an inherited stamp is at least wrong in a detectable way while an absent one offers the
operator nothing to check.

The 19 blocks with no `as_of`:

```
cio_now · capital_plan · posture · opportunities · consistency · operator_trust
holdings_thesis_coverage · surface_a_status · watch_block_summary · cash · temperament
case_summaries · reentry_books · coverage · graph_impact · notifications
instrument_narratives · record_narrative_coverage · _serving
```

**The brief's remark that "every cash number was in that group" is confirmed** `[VERIFIED]`:
`cash` and `capital_plan` are both in the no-`as_of` list.

### 3.1 Five of the six "own" timestamps are not independent

`[VERIFIED]` The six blocks that carry their own `as_of`:

| block | `as_of` | delta vs composition |
|---|---|---|
| `report` | `2026-08-30T23:16:41.750603Z` | −0.20 s |
| `evidence` | `2026-08-30T23:16:41.750603Z` | −0.20 s |
| `strategy_context` | `2026-08-30T23:16:41.102379Z` | −0.85 s |
| `seasonality` | `2026-08-30T23:16:41.071587Z` | −0.88 s |
| `research_context` | `2026-08-30T23:16:41.076060Z` | −0.87 s |
| `operator_product` | `2026-08-30T23:11:53Z` | **−4m 49s** |

Five of the six are sub-second-old — they are stamped *at collection time during this same
request*, so they report when the collector ran, not when the data moved. **Only
`operator_product` carries an `as_of` that is meaningfully independent of the request.**

Effective count of blocks whose `as_of` tells the operator when the underlying data last
changed: **1 of 26.** `[VERIFIED]`

### 3.2 A timestamp that moves while its data does not

`[VERIFIED]` Two back-to-back fetches of `/api/v3/cio/home`, 64 seconds apart:

```
leaf count run1: 5144   run2: 5144   keys added/removed: 0
leaves that CHANGED: 122   (of 5144)
```

Of those 122, the substantive movers are `_serving.*` (a release was promoted between the two
fetches), age counters, and hashes. But also:

```
.earnings[0..9].as_of   '2026-08-30T23:11:48+00:00' -> '2026-08-30T23:17:10+00:00'
.cash_letter.as_of      '2026-08-30T23:16:41.950348Z' -> '2026-08-30T23:17:45.551861Z'
```

**All ten `earnings` rows share a single `as_of` that advances on every request.** It is a
composition timestamp wearing a per-row label. The earnings data did not change between the
two fetches — every other field on all ten rows was byte-identical — yet each row's stated
freshness advanced by 5m22s. Same defect on `cash_letter.as_of`. `[VERIFIED]`

---

## 4. The cash numbers — renders fine, hasn't moved in weeks

This is the clearest instance of hunt #2 and it is on the money.

`[VERIFIED]` pin `865a4a1d`. `capital_plan.cash_as_of.by_account`, against census date
`2026-08-30`:

| account | settled cash USD | as_of | days stale |
|---|---:|---|---:|
| `schwab_rollover_ira` | 585,917.80 | 2026-08-14 | **16** |
| `schwab_taxable` | 37,894.31 | 2026-08-14 | **16** |
| `alpaca_taxable_live` | 5,000.00 | 2026-08-04 | **26** |
| `schwab_roth` | 1,472.71 | 2026-08-14 | **16** |
| `moomoo_taxable_live` | 500.00 | 2026-08-03 | **27** |
| **total** | **630,784.82** | | |

**100% of the cash is at least 16 days old. 93.0% of it (`schwab_rollover_ira`) is 16 days
old.** `mixed_ages: true`, `distinct_stamps: 3`.

Everything downstream inherits that staleness `[VERIFIED]`:

```
cash.cash_usd                        630,784.82
capital_plan.cash_total_usd          630,784.82
capital_plan.cash_investable_usd     373,504.27
capital_plan.deployable_usd          541,943.89
capital_plan.recommended_deploy_usd  541,943.89
cash_letter.cash_usd                 630,784.82
```

### 4.1 The same quantity is published with three different freshness claims

`[VERIFIED]` `$630,784.82` appears on the surface three times:

| surface | freshness claim | honest? |
|---|---|---|
| `capital_plan.cash_as_of.as_of` | `2026-08-03` | **yes** |
| `cash_letter.as_of` | `2026-08-30T23:17:45Z` | no — composition time |
| `cash.*` | *(no `as_of` field)* | no — silent |

`capital_plan.cash_as_of` is the honest one, and it is honest deliberately `[VERIFIED]`, its
own `note` field reads:

> `"The block is as current as its stalest account, never the moment the builder ran."`
> `source: "holdings rows where is_cash, oldest stamp wins"`

**Someone built the right rule and it governs one block of three.** The other two publish the
same dollars as if they were minutes old. This is an M4 (consistency) violation: the same
quantity stated on multiple surfaces with different scopes, unlabeled.

### 4.2 `stage_into_X` — an unsubstituted placeholder on the operator surface

`[VERIFIED]` `cash_letter.option_ids`:

```json
["hold_cash", "stage_into_X", "wait_until_month"]
```

`stage_into_X` is a literal. The `X` was never substituted with a symbol. It is offered to
the operator as one of three options alongside `recommendation_option_id: "hold_cash"`.

### 4.3 `writer: "migration:deterministic"`

`[VERIFIED]` `cash_letter.writer == "migration:deterministic"`.

This is the exact marker the brief warned about — a label describing the *copy step*, not the
author. On this block the label happens to be true of the content as well (§6.2), but the
marker cannot be used as evidence of authorship anywhere it appears, and it should not be
read as one by PART 1 or by any later wave.

---

## 5. Fields whose value never moves — hunt #1

The brief required these be established by **constructing materially different inputs and
diffing the outputs**, not by reading code. Both methods were run; the constructed-input
result is the evidence.

### 5.1 The counter-case that is a fixed disclaimer — CONFIRMED, 25/25

`[VERIFIED]` All 25 live decisions in `operator_product.decisions`, field-by-field:

| field | distinct values across 25 decisions |
|---|---|
| `counter_evidence` | **1** |
| `next_review` | **1** |
| `confidence` | **1** (`null`) |
| `confidence_status` | **1** (`NOT_PROVIDED`) |
| `data_quality` | **1** (`OK`) |
| `research_provenance` | **1** (`cio.product.current`) |
| `generation_id` | 1 (expected — one generation) |
| `decision` | 4 |
| `urgency` | 4 |
| `reason` | 18 |
| `entity_identity` | 21 |
| `decision_id` | 25 |

**7 of 12 fields are invariant across all 25 decisions.**

The invariant `counter_evidence` value, on every one of the 25 cards:

> `none cited — what would invalidate this is not in the producer payload this generation`

The invariant `next_review` value, on every one of the 25 cards:

> `next material generation or next session — standing cadence, not a dated catalyst`

`[CODE]` Both originate at
`/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/lib/operator_decision_contract.py`
lines 116 and 131, as the `empty=` argument to `_explicit()`:

```python
counter, counter_status = _explicit(
    row.get("counter_evidence") or row.get("counter") or row.get("counterpoint"),
    empty="none cited — what would invalidate this is not in the producer payload this generation",
)
...
nrev, nrev_status = _explicit(
    row.get("next_review") or row.get("next_review_at"),
    empty="next material generation or next session — standing cadence, not a dated catalyst",
)
```

**Important correction to the brief's framing.** The brief describes this as "a fixed
disclaimer wearing a counter-case's label". In code it is not a hardcode — it is a documented
*fallback*, and the module sets a companion `field_status` of `NOT_PROVIDED`. The mechanism is
honest. **What makes it a defect is that the fallback rate is 100%:** the producer has never
once supplied a counter-case, so the honest fallback is the only thing the operator has ever
seen in that field. A fallback taken 25 times out of 25 is indistinguishable from a constant
at the surface, and the `field_status` that would disclose it does not reach the rendered
card (§6).

### 5.2 Constructed-input diff — the producer, five materially different situations

`[VERIFIED]` `normalize_decision()` called with five materially different rows — opposite
actions (HOLD / TRIM / EXIT / ADD / AVOID), different symbols, different priorities
(LOW / HIGH / NOW), different `data_quality` (OK / DEGRADED / INSUFFICIENT_DATA), different
rationales:

```
INVARIANT ACROSS ALL 5 MATERIALLY DIFFERENT INPUTS: 15 of 26 fields
['authority', 'blocking_conditions', 'confidence', 'confidence_status',
 'confidence_text', 'counter_evidence', 'created_at', 'field_status',
 'financial_action', 'generation_id', 'last_confirmed_at', 'next_review',
 'next_review_at', 'source', 'what_changed']
```

Fields that did vary: `decision` (4), `urgency` (3), `data_quality` (3), `entity`/`symbol`/
`decision_id`/`why_it_matters`/`supporting_evidence` (5 each).

**One caveat I am flagging against my own result:** `what_changed` appears invariant here only
because my constructed rows did not set `title`. That is an artifact of my inputs, not a
property of the producer — discount it. The other 14 are real: no input I could construct
moved `counter_evidence`, `next_review`, `confidence`, `confidence_status` or `confidence_text`.

`confidence` deserves its own line. `[VERIFIED]` It is `null` on all 25 live decisions and on
all 5 constructed cases, with `confidence_text`:

> `not provided — no numeric score this generation (not fabricated)`

The parenthetical is correct and commendable — the system declines to invent a number. But a
confidence field that has never carried a value is a column of `null` that the operator has
no reason to keep reading.

### 5.3 Per-entity fields that are constant across every entity

`[VERIFIED]` Method: flatten the payload, normalise list indices to a field identity, and find
fields present on ≥3 entities whose value is byte-identical on every one. **11 such fields**,
pin `865a4a1d`:

| field | entities | the single value |
|---|---:|---|
| `operator_product.decisions[].next_review` | 25 | `next material generation or next session — standing cadence…` |
| `operator_product.decisions[].counter_evidence` | 25 | `none cited — what would invalidate this is not in the producer payload…` |
| `research_context.relevant_facts[].current_applicability` | 5 | `Context / risk modifier only. Maximum 10% conviction…` |
| `research_context.relevant_facts[].layers.current_application` | 5 | *(same string)* |
| `strategy_context.research_context.relevant_facts[].current_applicability` | 5 | *(same string)* |
| `strategy_context.research_context.relevant_facts[].layers.current_application` | 5 | *(same string)* |
| `new_position_if[].why` | 5 | `Desk defense watch; former-holding status not_former; thesis_state=CURRENT; gaps=1.` |
| `operator_product.new_position_if[].why` | 5 | *(same string)* |
| `strategy_context.relevant_facts[].author` | 3 | `Hirsch / Stock Trader's Almanac tradition` |
| `opportunities.reentry[].cc_narrative.thesis_fit` | 3 | `Under desk@v5 (defensive_observe): situation escalated…` |
| `cio_now.decisions[].freshness.session.note` | 3 | `Regular session: quote/MV age <= 15m…` |

Two of these deserve calling out beyond the table:

- **`new_position_if[].why`** — a field named *why*, offered per candidate, giving the
  identical reason for all five candidates including the identical `gaps=1` count. Five
  different proposed new positions, one reason. An operator comparing candidates on the
  stated rationale is comparing nothing.
- **`relevant_facts[].current_applicability`** — five different research facts, one
  applicability ruling. It is a policy sentence (`Never a standalone sell. Does not create
  TRIM.`) rendered in a per-fact slot, so it reads as a judgment made about *that fact*.

`cio_now.decisions[].freshness.session.note` and `strategy_context.relevant_facts[].author`
are **not** defects — a session-hours rule and an almanac attribution are legitimately the
same for every row. They are listed for completeness of method.

### 5.4 The unconditional cash/posture guidance constant — FOUND, and it is the top-line reason

**I first recorded this as not-found and I was wrong. Correcting out loud.** My initial pass
looked for an unconditional cash *paragraph* in the `/api/v3/cio/home` payload, did not find
one, and I wrote it up as unconfirmed. It exists. It is not shaped like a cash paragraph —
it is shaped like a *decision rationale*, which is why a search for cash prose missed it.

`[CODE]` `scripts/lib/cio_investment_product.py` lines 75–79:

```python
PORTFOLIO_IMPLICATION_CONSTANT = (
    "Preserve quality growth exposure, keep cash for dislocations, "
    "and do not force lower-quality replacements. Re-entries need "
    "candidate-specific governed verdicts — desk zone marks are not authorization."
)
```

`[VERIFIED]` It renders live at `temperament.portfolio_implication`, 200 characters, pin
`a5006df1`, with `portfolio_implication_class: "T"`.

**And it is also the entire stated reason for the portfolio-level HOLD.** `[VERIFIED]`:

```
decisions whose reason CONTAINS the portfolio_implication constant: 1 of 25
   PORTFOLIO | HOLD | 'HOLD remains correct: Preserve quality growth exposure, keep cash
   for dislocations, and do not force lower-quality replacements. Re-entries need
   candidate-specific governed verdicts — desk zone marks are not authorization.'
```

The one PORTFOLIO-scoped decision — the top-line call on the whole book, the first thing the
operator reads — carries as its `reason` a compile-time constant with a
`"HOLD remains correct: "` prefix bolted on by `normalize_decision` (§5.2). Its
`counter_evidence` is the invariant disclaimer and its `confidence` is `null`. **Every
data-bearing field on the headline decision is a constant.**

**The system knows.** `[CODE]` Two docstrings quarantine this constant from the money
surfaces, and both name the exact failure:

`scripts/lib/cio_operator_renderers.py` `cash_lines()`:
> *"Never renders `portfolio_implication` — that is a constant sentence about posture, not a
> cash number, and reading it as one is how a stale narrative ends up standing in for a
> balance."*

`scripts/lib/cio_investment_product.py` line 700:
> *"HOLD_CASH_FOR row from live numbers. Never the portfolio_implication constant."*

**So the constant is deliberately excluded from the Telegram briefs and from the cash rows —
and is rendered unguarded on the dashboard** at `CioHub.tsx`, and reused as the top-line
decision rationale. The guard was written for two consumers and there are three.

### 5.5 The counter-case defect was already measured once, by the system itself

`[CODE]` `scripts/lib/cio_cash_capital_v1.py` lines 51–67 carries a comment that is, in
effect, a prior run of this same census:

> ```
> # Measured 2026-08-30 across 24 materially different situations … two fields never moved:
> #   counter_case         one byte-identical sentence in all 24
> #   supporting_evidence  [null, null, null, null, null]
> #
> # A counter-case is the argument against THIS recommendation on THIS data. A
> # constant string in that slot is a disclaimer wearing a counter-case's label,
> # and it reads to the operator as reasoning that was done.
> ```

That module was then partially remediated: `_COUNTER_CASE_BY_CONCLUSION` (lines 69–94) is now
five fixed paragraphs selected by conclusion, and its `provenance` field says so honestly —
`"TEMPLATE — one per conclusion … Not model-written."` `[CODE]`

**But the remediation did not reach the path that feeds the operator surface.** `[VERIFIED]`
the 25 live decision cards still carry the single invariant disclaimer (§5.1), which comes
from `operator_decision_contract.py:116`, not from the remediated module. The fix landed on
one producer and the surface reads another. `[CODE]` The pre-remediation string also survives
as a live fallback in two more places:

- `scripts/lib/cio_advisory_message.py:104` — `cash.get("counter_case") or 'Holding cash can remain rational.'`
- `scripts/lib/operator_human_renderer.py:38` — `"none cited — invalidation condition not in producer payload"` (this is the Telegram path, §8)

**Three counter-case fallbacks, three different strings, one already-diagnosed defect.**

### 5.6 Unsubstituted placeholders rendering to the operator

`[VERIFIED]` pin `a5006df1`, two classes of literal placeholder reach the surface:

| rendered value | where | what it should have been |
|---|---|---|
| `stage_into_X` | `cash_letter.option_ids[1]` | a symbol |
| `Zone ?–?; desk NEAR ENTRY` | 3 decision `reason`s | a price zone |
| `Zone ?–?; desk READY TO REVIEW` | 1 decision `reason` | a price zone |

Four of the 25 decision cards state their entry zone as `?–?`. They sit beside cards that
state real zones (`Zone 1.35–1.6`, `Zone 1053.14–1316.43`), so the operator sees a populated
column with four holes punched in it and no indication whether `?` means *unknown*,
*not applicable*, or *failed to compute*.

## 6. Provenance labelling — can the operator tell one class from the next?

**This is the column that matters most, and it is the weakest column on the surface.**

### 6.1 The mechanism exists

`[CODE]` `scripts/lib/cio_p90_voice.py` defines a three-class provenance vocabulary, and its
module docstring is exactly right about what it is for:

```python
"""P9.0 remaining voice labels.

T = template / f-string. D = derived filter or count. A = judgment.
"""
```

It carries per-field explanatory notes that are unusually candid — these are the system
telling the truth about itself:

| constant | note |
|---|---|
| `EXEC_SUMMARY_NOTE` | *"the field name asserts synthesis; the value is an f-string over counts and filters"* |
| `NOTHING_NOTE` | *"emitted when action_book.DO_NOW is empty; derived, not a considered all-clear judgment"* |
| `NARRATIVE_NOTE` | *"f-string over regime label, as-of, FS receipt count and ratified lesson count; not a written view"* |
| `NEXT_REVIEWS_NOTE` | *"one constant cadence sentence repeated per entry; a standing cadence, not a dated catalyst"* |
| `CLOSEST_REENTRY_NOTE` | *"filter over the Surface A book by pct-above-exit; a distance measurement, not a re-entry judgment"* |

`[CODE]` `stamp_closest_reentries()` carries a docstring describing the exact defect class
this census exists to find: *"Leaving it under the sentence-level [T] implied the desk had
picked those names; it measured them."*

### 6.2 The mechanism reaches 3 of 375 prose fields

`[VERIFIED]` pin `865a4a1d`:

```
total prose leaves (string, >60 chars, containing a space): 375
string leaves carrying an inline [T]/[D]/[A] stamp:           3
```

The three:

```
.operator_product.executive_summary
.operator_product.temperament.narrative
.temperament.narrative
```

**Coverage: 0.8%.** The other 372 prose fields render with no provenance marking of any kind.

### 6.3 The voice metadata is computed and then dropped before serving

`[CODE]` `apply_operator_voice()` (`cio_p90_voice.py:103`) attaches nine metadata keys
alongside the stamps: `executive_summary_class`, `executive_summary_voice`, `action_now_class`,
`action_now_voice`, `nothing_requires_action_class`, `nothing_requires_action_voice`,
`next_reviews_class`, `next_reviews_voice`, `closest_reentries_class`, `closest_reentries_voice`.

`[VERIFIED]` The live `operator_product` block contains **none of them**:

```
keys present: source loaded status generation_id product_id as_of executive_summary
earnings new_position_if cash temperament case_summaries telegram_sent delivery
decisions history_store hidden_alternative_calculation authority financial_action
```

The `[T]` and `[D]` prefixes on the summary text survive; the metadata that explains what
`[T]` and `[D]` *mean* does not. **The operator is shown a two-letter code with no legend.**

`temperament.narrative_voice` does survive — so the drop is partial and inconsistent, which
is worse than either uniform outcome, because a reader who finds the legend on one field will
reasonably assume its absence elsewhere means something.

### 6.4 The answer

**No.** An operator reading the surface cannot distinguish a field's provenance class from
the one beside it, in the general case:

- 372 of 375 prose fields carry no class marker `[VERIFIED]`.
- Where a marker exists, its legend was computed and dropped `[VERIFIED]`.
- Where a class marker *does* survive, it is wrong on the largest instance — `case_summaries`
  is marked `A` (judgment) and is a template (§5 below / §7.1) `[VERIFIED]`.
- `field_status: NOT_PROVIDED`, the one signal that would tell the operator a value is a
  fallback rather than a finding, is computed by `operator_decision_contract` `[CODE]` and is
  **not** present on the 25 live decision cards `[VERIFIED]` — the live cards carry
  `confidence_status` only, not the full `field_status` map.

### 6.5 One surface does provenance correctly — and it is worth copying

`[CODE]` The R24 control-plane pages
(`apps/command-center-v3/src/pages/control-plane/r24/useControlPlaneEnvelope.ts`) carry an
explicit provenance discriminator on every render:

```ts
export type EnvelopeDataSource = 'FIXTURE' | 'PROP' | 'PENDING' | 'FETCH_FAILED' | `GET ${string}`
```

and a set of hard constants including `liveClaim: false`. Its docstring states the rules the
rest of the surface does not follow:

> *"UNAVAILABLE / INVALID_SCHEMA / GET failure is the page truth — never keep FIXTURE."*
> *"HTTP 200 is not a live claim. liveClaim=false."*

**This is the model.** A field that names its own source as one of five discriminated cases,
and a page that treats a failed fetch as page truth rather than falling back to something
that looks populated. If a later wave wants a target shape for provenance on the CIO surface,
it is already written here.

**A wrong conclusion I caught and am recording as a method warning.** A first pass over this
directory concluded that `/control-plane/{learning,maturity,audit}` "render fully-populated
screens from checked-in frozen JSON even if the backend is down" — which would have been a
serious `HARDCODED` finding. **It is false.** `[VERIFIED]` The only importers of
`frozenEnvelope` in live page code import `CONTROL_PLANE_PREVIEW_ROUTES` — a route-name
constant — and nothing imports `FROZEN_LEARNING` / `FROZEN_MATURITY` / `FROZEN_AUDIT`:

```
$ grep -rn "FROZEN_\|frozenEnvelope" src/ | grep -v "frozenEnvelope.ts:"
  r24/useControlPlaneEnvelope.ts:27:} from './frozenEnvelope'      <- imports CONTROL_PLANE_GET, isControlPlaneEnvelope
  r24/LearningPage.tsx:19:  import { CONTROL_PLANE_PREVIEW_ROUTES } from './frozenEnvelope'
  r24/AuditPage.tsx:18:    import { CONTROL_PLANE_PREVIEW_ROUTES } from './frozenEnvelope'
  r24/MaturityPage.tsx:19:  import { CONTROL_PLANE_PREVIEW_ROUTES } from './frozenEnvelope'
  r24/controlPlaneChrome.tsx:210: "Populated FROZEN_ENVELOPES are not kept as the live view."
```

The fixtures are correctly quarantined and the module says so: *"These JSON files must not be
the live view when GET is UNAVAILABLE."* The wrong conclusion came from import *adjacency* —
the file is imported, so its data was assumed used. **Adjacency is not usage; resolve the
imported symbol.** This is the same failure class the standing rules warn about for filename
greps, and it nearly put a false `HARDCODED` verdict into this census.

---

## 7. Route census

`[VERIFIED]` The v3 app has exactly one router — a single flat `<Routes>` block at
`apps/command-center-v3/src/App.tsx:165–219`, under `<BrowserRouter basename="/v3">` (line
232). No `createBrowserRouter`, no route manifest, no `React.lazy` / dynamic import anywhere.
So the route table is statically complete: **50 `<Route>` declarations** — 39 page components,
2 deep-link shims, 10 pure `<Navigate>` redirects (rendering nothing), and **no catch-all /
404 route**.

`[VERIFIED]` The served bundle is current — this is a clean result and I am recording it as
such. `dist/build-meta.json` `git_sha == source_sha == 865a4a1d`, matching `BUILD_SHA` /
`GIT_SHA` / `SOURCE_COMMIT`, `built_at 2026-08-30T23:16:44.432Z` (same second as the release
stamp), and `git status --porcelain -- apps/command-center-v3` shows only `build-meta.json`
itself modified. Strings from the newest v3-src commits are present in the shipped JS.
**There is no page whose source changed without a rebuild.**

### 7.1 Route verdicts

`data_source` = the producing function/endpoint. `prov` = deterministic · template ·
model-assisted · agent-originated · snapshot. `as_of` = own / inherited / **none**.

| route (`/v3/…`) | data_source | prov | as_of | verdict |
|---|---|---|---|---|
| `/` (`HomeHub`) | 14 × `/api/v2/*` (`command`, `overview`, `risk`, `health`, …) | deterministic | none | LIVE |
| `/cio` | `/api/v3/cio/home` + 11 others — §7.2 | mixed | see §3 | **LIVE, data STALE** |
| `/portfolio` | 21 × `/api/v2/portfolio*`, `overview`, `risk`, `tax-lots`, `dividends` | deterministic | none | LIVE |
| `/portfolio/re-entry` | 24 endpoints via `components/reentry/*` + 3 hooks | deterministic | none | LIVE |
| `/risk` | `/api/v2/risk`, `correlation`, `recovery`, `risk-regime/{latest,history,indicators}` | deterministic | none | **STALE** — regime `as_of 2026-08-28` |
| `/trading` | 16 own + `ManualTosDesk` (9) + `OptionsHub` (10) | deterministic | none | LIVE |
| `/active-trader` | `/api/v3/active-trader/{permission-queue,scalp/setups,config}` | deterministic | none | LIVE (see §7.3) |
| `/strategy` | 9 × `/api/v2/*` | deterministic | none | LIVE |
| `/agents` | `/api/v3/agent-maturity`, `/api/v3/agent-runtime/*`, `/api/v3/maturity/*` (11), `/api/v2/agent*` | deterministic | none | LIVE |
| `/intelligence` | `/api/v2/market-intelligence`, `/api/v3/intelligence{,/authority,/queue,/lineage}` | deterministic | none | LIVE |
| `/research-intelligence` | `/api/v2/research-intelligence/*` | deterministic + model-assisted | none | LIVE |
| `/hermes` | 13 × `/api/v2/hermes/*` | deterministic | none | LIVE |
| `/retirement` | `/api/v2/retirement{,/planning-research}` | deterministic | none | LIVE |
| `/journal` | 10 × `/api/v2/journal*` | deterministic + model-assisted | none | LIVE |
| `/watch` | 4 sub-tabs, `/api/v3/data-broker*` + `/api/v2/watch*` | deterministic | none | LIVE |
| `/watch/intelligence/:symbol` | `/api/v3/cio/intelligence/{symbol}` | mixed | none | LIVE |
| `/watch/discovery` | `/api/v2/screener-finds/candidates` | deterministic | none | LIVE |
| `/watch-legacy` | `/api/v3/watch/{cio/latest,priority}` + `WatchlistHub` (17) | deterministic | none | LIVE |
| `/defense` | `/api/v2/defense/*`, `risk-regime/latest` | deterministic | none | LIVE |
| `/reports` | `/api/v2/reports/*` | deterministic | none | LIVE |
| `/rotation` | `/api/v2/rotation/*`, `/api/v2/llm/oauth-lanes` | model-assisted | none | LIVE |
| `/redeploy` | `/api/v2/redeploy/*`, `/api/v2/deploy/*` | deterministic | none | LIVE |
| `/rec-intel` | `/api/v2/rec-intel/*` | deterministic | none | LIVE |
| `/advisory` | `/api/v3/advisory/{kind}` | deterministic | none | LIVE |
| `/health` | `/api/v2/health/*` + `/api/v3/maturity/*` | deterministic | none | LIVE |
| `/consumption` | `/api/v2/consumption/*` | deterministic | none | LIVE |
| `/system` | 8 × `/api/v2/system/*` + `/api/v2/admin/*` | deterministic | none | LIVE |
| `/system/schwab-reauth` | `/api/v2/brokers/schwab/*` | deterministic | none | LIVE |
| `/control-plane` | *(none — static link index)* | n/a | n/a | **EMPTY by design** |
| `/control-plane/system` | `/api/v3/control-plane/system` | deterministic | own | LIVE |
| `/control-plane/{agents,workflows}` | `/api/v3/control-plane/{agents,workflows}` | deterministic | own | LIVE |
| `/control-plane/{research,data,identity,notifications}` | `/api/v3/control-plane/{research,stores,identity,notifications}` | deterministic | own | LIVE |
| `/control-plane/{learning,maturity,audit}` | `/api/v3/control-plane/{…}` via `useControlPlaneEnvelope` | deterministic | own | LIVE — best-labelled surface, §6.5 |
| `/go/order/:intentId`, `/go/proposal/:proposalId` | *(none — `sessionStorage` + redirect)* | n/a | n/a | shim |
| 10 × `<Navigate>` (`trading/active-trader`, `manual-execution`, `closed-loop`, `research`, `trade-in-view`, `watchlist`, `watchpool`, `sectors`, `pullback-macd`, `advisor-changes`) | *(none)* | n/a | n/a | redirect, renders nothing |
| *any unmatched* `/v3/*` | *(none)* | n/a | n/a | **no 404 — renders chrome + empty `<main>`** |

### 7.2 `/v3/cio` — the tab census

`[VERIFIED]` `CioHub.tsx` (101,794 bytes), `TABS` at line 286. **13 tabs. Only 6 read the
page's primary payload.** Default tab is `cio-brain` (line 1846).

| # | `?tab=` | label | reads `/api/v3/cio/home` | own endpoint | verdict |
|---|---|---|---|---|---|
| 1 | `cio-brain` | CIO BRAIN | **no** | `/api/v3/cio/brain` | LIVE |
| 2 | `cio-now` | CIO NOW | `cio_now`, `operator_trust`, `coverage` | `/api/v3/cio/dispositions` | LIVE, fields invariant (§5.1) |
| 3 | `operator-policy` | OPERATOR POLICY | no | `/api/v3/cio/brain/policy` | LIVE |
| 4 | `universe-theses` | UNIVERSE & THESES | no | `/api/v3/cio/{agent-research-ops,universe-theses,intelligence/{sym}}` | LIVE |
| 5 | `investment-books` | INVESTMENT BOOKS | no | `/api/v3/cio/investment-product` | LIVE |
| 6 | `capital-plan` | CAPITAL PLAN | `capital_plan` | — | **STALE — cash 16–27d (§4)** |
| 7 | `posture` | PORTFOLIO POSTURE | `posture` | — | LIVE |
| 8 | `opportunities` | OPPORTUNITIES | `opportunities`, `reentry_books` | `/api/v2/cio/youtube-research-queue` | LIVE |
| 9 | `report` | REPORT | `report` | `/api/v2/cio/report-v2` (on demand) | LIVE |
| 10 | `evidence` | EVIDENCE / AUDIT | `evidence` | — | LIVE |
| 11 | `notification-gate` | NOTIFICATION GATE | no | `/api/v3/maturity/notification-gate` | LIVE |
| 12 | `telegram-receipts` | TELEGRAM RECEIPTS | no | `/api/v3/maturity/telegram-receipts` | LIVE |
| 13 | `senses-evidence` | SENSES EVIDENCE | no | `/api/v3/maturity/senses` | LIVE |
| — | `?plan=<id>` | plan overlay | no | `/api/v3/cio/plans/{id}` | LIVE |

Two structural notes `[CODE]`:

- **The default landing tab does not use the payload the page fetches.** `/v3/cio` with no
  query string renders `cio-brain`, which reads only `/api/v3/cio/brain`. `/api/v3/cio/home`
  — a 221 KB, 5,144-leaf document — is fetched unconditionally on mount and discarded. The
  `cio-home-loading` / `cio-home-error` placeholders render on `cio-brain` too, so the
  operator can see a CIO-home error on a tab that does not use CIO home.
- **Mixed API generations on one page.** 11 endpoints are `/api/v3/*`; the REPORT and
  OPPORTUNITIES tabs reach back to `/api/v2/cio/report-v2` and
  `/api/v2/cio/youtube-research-queue`.
- `[VERIFIED]` `type Home` declares `ok`, `authority` and `version` and **no code in
  `CioHub.tsx` reads any of them** — including `authority`, the `READ_ONLY_ADVISORY` marker.
  The authority declaration travels the whole way to the page and is never rendered.

### 7.3 Orphaned components

`[VERIFIED]` **5 page modules exist in `src/pages/` and are reachable from no route**, with
zero importers anywhere in `src/`:

| file | size | note |
|---|---:|---|
| `src/pages/ReEntryPageV3.tsx` | 53 KB | superseded; `ReEntryPage.tsx` re-exports V4 |
| `src/pages/ReEntryPageV2.tsx` | 41 KB | superseded |
| `src/pages/WatchlistIntelligenceBoard.tsx` | 22 KB | zero importers |
| `src/pages/AdvisorChangesHub.tsx` | — | its route is a `<Navigate>` to `/rotation` |
| `src/pages/ManualExecutionHub.tsx` | 2 lines | its route is a `<Navigate>` to `/trading` |

**Hard confirmation, not inference:** grepping the shipped bundle for `ReEntryPageV2`,
`ReEntryPageV3`, `AdvisorChangesHub` and `WatchlistIntelligenceBoard` returns **0 hits each**
— Vite tree-shook them out, which is only possible if nothing in the module graph reaches
them. ~123 KB of dead source. Verdict: `ORPHANED_ROUTE` (component side).

`[VERIFIED]` **No route renders a missing component.** All 41 component-routes resolve to real
modules — the `control-plane/index.ts` barrel resolves all 11 names to files on disk, and an
unresolved import is a hard `vite build` error, so the existence of a bundle proves it.

### 7.4 Reference-sample data on a live route

`[CODE]` `ActiveTraderPage.tsx:372–373`:

```ts
const ignQueue = reference ? MOCK_QUEUE : ignItems;
const acct     = reference ? MOCK_ACCOUNTS : (accounts ?? []);
```

This is **correctly gated and correctly labelled** — when `reference` is true the UI renders
`REFERENCE SAMPLE · 0 ACTIONABLE` (line 46), every row's action reads `no action` (line 60),
and the modal is titled `Allocation example (reference)` (line 196). Verdict: **not a defect.**
It is listed because a mock-data grep will land here and it should not be re-flagged.

`[VERIFIED]` I checked the shipped bundle for `MOCK_ACCOUNTS` / `MOCK_QUEUE` / `MOCK_SIGNAL`
and got 0 hits each — **but that is not evidence, and I am not claiming it as such**: the
bundle is minified, so identifier names are mangled regardless of whether the data ships.
The gating above is the actual evidence, read from source.

---

## 8. Telegram producers

The brief names three. **One of the three is not a Telegram producer at all**, and the naming
in the brief points at a file that does not compose the message.

### 8.1 The three named producers

| producer | real composer | real send site | verdict |
|---|---|---|---|
| **(a) CIO run-complete** | `scripts/lib/cio_investment_product.py::_summary()` L2101–2146; enqueued by `cio_run_worker.py::_enqueue_notifications()` L1135–1156 | `cio_notification_delivery.py::RealTelegramAdapter.send()` L104–192 → local import inside `try:` at L126–129 → `cio_telegram_transport.py::send_cio_message()` L190–297 | **LIVE, sending** |
| **(b) Aegis morning** | `scripts/lib/cio_operator_renderers.py::morning_text()` L163–260 | `deliver_morning()` L376–415; send at L385–388, local import inside `try:` | **LIVE** |
| **(c) Aegis evening packet** | `scripts/aegis_evening_packet.py` — **228 lines, zero Telegram code** | none | **NOT A TELEGRAM PRODUCER** |

`[CODE]` **(b) is the brief's trap made real.** `scripts/aegis_morning_brief_delivery.py` is
the file named for the job, and its `send_telegram_brief()` (L281–487) is **dead on the
default config**. `deliver()` L609–625 short-circuits:

```python
if os.getenv("CANONICAL_OPERATOR_BRIEF", "1").strip() != "0":
    from lib.cio_operator_renderers import deliver_morning
    result = deliver_morning(root=PROJECT_ROOT, send=True)
    return {...}
```

Default `"1"`, so 200 lines of the obviously-named function never run. **A filename grep lands
on the wrong function here**, exactly as the standing rules warn.

`[CODE]` **(c)** writes `data/runtime/aegis_evening_packet.json`, consumed by
`cio_command_center.py` — i.e. the dashboard. The crontab comment says so. The evening
Telegram traffic is `scripts/aegis_overnight.py` (three sends at L197–206, L230–238,
L266–279), which also calls the morning delivery at L257–259 — **so the morning brief is
actually published at 20:03 the night before.**

### 8.2 The interdict is OFF — report, not remediate

**The brief instructed that `CIO_TELEGRAM_INTERDICT` must stay on. It is not on, and it was
already off before this census began.** I changed nothing.

`[VERIFIED]` Both env files loaded by `tradeai-cio-delivery.service` via `EnvironmentFile=`:

```
$ grep -E "INTERDICT|ENABLE_TELEGRAM|AUTHORIZE" ~/.config/tradeai/cio-telegram.env
AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
CIO_TELEGRAM_INTERDICT=0
$ grep -E "INTERDICT|ENABLE_TELEGRAM|AUTHORIZE" ~/.config/tradeai/cio-operator-live.env
ENABLE_TELEGRAM=1
AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
CIO_TELEGRAM_INTERDICT=0
```

`[VERIFIED]` And the durable send log confirms live delivery to the operator's phone **today,
about two hours before this census**:

```
DURABLE TELEGRAM SEND LOG  (data/cio/cio_outbound_dedupe.jsonl — appended only after Telegram returned OK)
    321  alex_decision    last_sent=2026-08-19T01:25:34Z
     87  advisory         last_sent=2026-08-23T13:17:02Z
     18  checkin          last_sent=2026-08-30T19:15:23Z   <- producer (a)
  total records: 426
```

`checkin` is producer (a)'s `message_class` (`cio_run_worker.py:1141`). This log is appended
by `cio_telegram_transport.mark_sent()` **only inside `if ok_any:`**, so a row is durable
evidence of an accepted send, not of an attempt. `[CODE]`

**Three further findings on the interdict** `[CODE]`:

1. **It does not gate the Aegis family at all.** Producer (b) and all of `aegis_overnight.py`
   go through `telegram_alert.send_telegram` → `_raw_send_telegram`, gated only by
   `ENABLE_TELEGRAM`. `scripts/lib/autonomy_watchdog/telegram_system.py:5` states it plainly:
   *"CIO_TELEGRAM_INTERDICT does not apply to this family."* **An instruction to "keep the
   interdict on" would not have stopped the morning brief.**
2. **The defaults disagree, and the safe default is on the module with no teeth.**
   `cio_telegram_transport.py:51` defaults `"0"` — fail-**open**, unset means send.
   `cio_notification_policy.py:56` defaults `"1"` — fail-closed — but that module only
   `decide()`s and sends nothing.
3. **`force=True` bypasses it** (`send_cio_message` L228/234/250). No production caller found
   passing it.

Where it does apply it **blocks rather than logs** `[CODE]`: `send_cio_message` L228–232
returns `{"delivered": False, "interdicted": True}` before the `send_message` import at L258
is ever reached.

### 8.3 Producer (a) — field census

`[VERIFIED]` live body, from the durable outbox `data/cio/operator_notification_outbox.jsonl`,
event `2026-08-30T19:11:53Z`:

> `RISK OFF — SELECTIVE RISK. [D] Nothing requires action today. Closest re-entries: ATAI +2.2% vs exit, BOXL -8.1% vs exit, TDG -9.9% vs exit. Tracking 70 former names (25 near, 32 waiting, 13 avoid); 25 on close watch. Advisory only — no orders placed.`

| # | section | prov | as_of | verdict |
|---|---|---|---|---|
| 0 | `subject: CIO Run Complete — {run_id[:12]}` | template | inherited | LIVE |
| 1 | `{temperament.title}.` | deterministic | none | **STALE** — regime `as_of 2026-08-28` |
| 2 | `DO NOW: …` **or** `[D] Nothing requires action today.` | **template (constant)** | none | **HARDCODED** — §9 |
| 3 | `Closest re-entries: …` | deterministic (filter by pct-above-exit) | none | LIVE |
| 4 | `Triggered: …` | deterministic | none | LIVE (omitted when empty) |
| 5 | `Tracking {n} former names ({near} near, {wait} waiting, {avoid} avoid); {k} on close watch.` | deterministic (f-string over counts) | none | LIVE |
| 6 | `No change since the last brief.` / `Changed: …` | deterministic | none | LIVE |
| 7 | `Advisory only — no orders placed.` | **template (constant)** | n/a | HARDCODED, and correctly so |

### 8.4 Producer (b) — field census

`[CODE]` `morning_text()` L163–260, 18 sections. Constants: the header
`"☀️ MORNING CIO BRIEF"` (L166), the no-action branch
`"No ACT-NOW items. Standing posture below."` (L194), the re-entry scope fallback literal
`"former holdings vs exit trigger"` (L200–206), and the footer
`"Open: Command Center → CIO. READ_ONLY_ADVISORY."` (L257).

Per-decision rows come from `operator_human_renderer.py::render_decision()` L31–63, which
emits `Counterpoint:` from the fallback at L38 and `Confidence:` from L35 — **the same two
invariant fields as the dashboard (§5.1), via a different constant.** The row ends with the
constant `"READ_ONLY_ADVISORY — no order is being placed."` (L60).

`[CODE]` `deliver_morning` L388 passes `bypass_router=True`, which deliberately skips
`telegram_alert_router.should_send_telegram` — **the morning brief is the one Aegis message
that ignores `P1_DIGEST` / `P2_DASHBOARD_ONLY` suppression.**

### 8.5 Scheduling — cron runs a different tree than the one that is deployed

`[VERIFIED]` (`crontab -l`, `systemctl --user list-timers --all`). This is a finding that
reaches beyond the operator surface and PART 1 should have it:

| producer | schedule | tree |
|---|---|---|
| Aegis morning delivery | `5 8 * * 1-5` | **dev** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` |
| `send_morning_brief.py` | `0 8 * * 1-5` | **dev** |
| Aegis overnight | `0 20 * * *` **and** `aegis-overnight.timer OnCalendar=20:00:00` | **dev** (double-scheduled) |
| Aegis evening packet (file only) | `45 19 * * *` | release `CURRENT` |
| CIO wake dispatch | `*/5 * * * *` | release `CURRENT` |
| `tradeai-cio-delivery.timer` | `OnUnitActiveSec=5min`, `Persistent=true` | release `CURRENT` — **the only thing that puts producer (a) on the wire** |

**Consequence:** fixes that land in a release do not reach the Aegis producers, because cron
invokes the dev tree. Two concrete instances `[VERIFIED]` — `logs/morning_brief.log` and
`logs/aegis_brief.log` both end in:

```
File ".../scripts/lib/cio_operator_renderers.py", line 11, in <module>
    from scripts.lib.brief_semantic_dedupe import claim, session_date
ModuleNotFoundError: No module named 'scripts'
```

The `sys.path` fix for exactly this is present in `CURRENT`
(`aegis_morning_brief_delivery.py` L18–27, with a comment describing the failure) and absent
from the dev tree. **The 08:00 and 08:05 morning jobs have been crashing; the brief only
reaches the operator because `aegis_overnight.py` imports the module under a different
`sys.path` at 20:00.** This is the standing-rules deploy failure — *prove behaviour from the
served release* — inverted: the served release is proven and is not what runs.

### 8.6 A success report that is not evidence of work

`[CODE]` `aegis_morning_brief_delivery.py:621`:

```python
"delivered": bool(result.get("published")),
```

`published` is the **dedupe claim**, not a send. `deliver_morning` returns a separate `sent`
key (L406) which this caller discards. So `{'delivered': True}` in the overnight log proves a
dedupe key was claimed and says nothing about whether Telegram received anything. This is a
textbook instance of the governing principle in the standing rules — *a component reporting
success is not evidence that it did anything* — sitting in a log line an operator would
reasonably read as delivery confirmation.

---

## 9. Fields in a register implying judgment they do not exercise

This is the defect list — count (c). Each row renders in a voice that implies a considered
call, and is produced by a template, a filter, or a constant.

| # | field | rendered value / form | what actually produces it | evidence |
|---|---|---|---|---|
| 1 | `operator_product.executive_summary` → `[D] Nothing requires action today.` | an all-clear | emitted when `action_book.DO_NOW` is empty. The system's own note: *"derived, not a considered all-clear judgment"* | `[VERIFIED]` live; `[CODE]` `cio_p90_voice.py:21,32–35` |
| 2 | `decisions[].counter_evidence` (×25) | *"none cited — what would invalidate this is not in the producer payload this generation"* | `empty=` fallback, taken 25/25 | `[VERIFIED]` §5.1 |
| 3 | `decisions[].next_review` (×25) | *"next material generation or next session — standing cadence…"* | `empty=` fallback, taken 25/25 | `[VERIFIED]` §5.1 |
| 4 | `decisions[PORTFOLIO].reason` | the entire rationale for the top-line HOLD | `PORTFOLIO_IMPLICATION_CONSTANT` + `"HOLD remains correct: "` prefix | `[VERIFIED]` §5.4 |
| 5 | `temperament.portfolio_implication` | portfolio guidance prose | compile-time constant | `[VERIFIED]` §5.4 |
| 6 | `case_summaries` (block + 10 items) | `class: "A"`, banner *"A-context"* — i.e. **agent judgment** | two f-strings; zero symbol-specific content | `[VERIFIED]` §10.3 |
| 7 | `new_position_if[].why` (×5) | per-candidate *why* | one identical string for all 5 candidates | `[VERIFIED]` §5.3 |
| 8 | `research_context.relevant_facts[].current_applicability` (×5, ×2 paths) | per-fact applicability ruling | one policy sentence for all facts | `[VERIFIED]` §5.3 |
| 9 | `opportunities.reentry[].cc_narrative.thesis_fit` (×3) | per-name thesis fit | one identical paragraph | `[VERIFIED]` §5.3 |
| 10 | `decisions[].confidence` (×25) | a confidence column | `null` on every card, every generation | `[VERIFIED]` §5.2 |
| 11 | `decisions[].data_quality` (×25) | a per-decision quality verdict | `"OK"` on every card | `[VERIFIED]` §5.1 |
| 12 | `earnings[].as_of` (×10) | per-row freshness | composition timestamp; advances every request | `[VERIFIED]` §3.2 |
| 13 | `cash_letter.as_of` | freshness of the cash letter | composition timestamp over 16–27-day-old balances | `[VERIFIED]` §4.1 |
| 14 | `cash_letter.recommendation_option_id: "hold_cash"` | a recommendation | selected among a list containing the unsubstituted literal `stage_into_X` | `[VERIFIED]` §5.6 |
| 15 | `cash_letter.writer: "migration:deterministic"` | an authorship claim | labels the copy step, not the author | `[VERIFIED]` §4.3 |
| 16 | Telegram (a) §2 · Telegram (b) `Counterpoint:` / `Confidence:` | per-decision reasoning in the packet | the same fallbacks as rows 2/10, via a *different* constant | `[CODE]` §8.4 |
| 17 | `cc_narrative.evidence_refs[].model_provider` (×4) | `deepseek-v4-flash` beside `quality_state: AVAILABLE` | hardcoded literal; producer makes no model call and reports `promoted_research_count: 0` | `[VERIFIED]` §9.1 |
| 18 | `/api/v3/cio/dashboard.model_provider` | `deepseek-v4-pro` | hardcoded literal; `get_cio_dashboard()` calls no model | `[CODE]` §9.1 |

**Count (c) = 18.**

Row 6 is the worst of these and row 4 the most consequential: the top-line portfolio call
reads as a considered HOLD and every data-bearing field on it is a constant.

### 9.1 The `model_provider` class — CONFIRMED, and I was wrong once on the way

**Correcting my own claim.** My first pass searched the payload for the brief's exact string
`"deepseek-v4-pro"`, did not find it, and I wrote that the field was "not present on this
route at this pin". **That was wrong, and it was wrong because I searched for a literal value
instead of the field name.** The field is present four times with a different value.

`[VERIFIED]` pin `a5006df1`, all 5,144 leaves searched by key:

```
leaves with model/llm/provider in KEY: 4
  .cio_now.decisions[2].cc_narrative.evidence_refs[4].model_provider   = 'deepseek-v4-flash'
  .opportunities.watch[1].cc_narrative.evidence_refs[4].model_provider = 'deepseek-v4-flash'
  .opportunities.reentry[2].cc_narrative.evidence_refs[5].model_provider = 'deepseek-v4-flash'
  .opportunities.reentry[3].cc_narrative.evidence_refs[5].model_provider = 'deepseek-v4-flash'
```

`[VERIFIED]` The full block, `.cio_now.decisions[2].cc_narrative.evidence_refs[4]`:

```json
{
  "as_of": "2026-08-30T02:13:57",
  "domain": "hermes_research",
  "fields_used": ["model_provider", "promoted_research_count", "staged_research_count"],
  "model_provider": "deepseek-v4-flash",
  "promoted_research_count": 0,
  "staged_research_count": 0,
  "quality_state": "AVAILABLE"
}
```

**It names a model provider, declares itself `AVAILABLE`, and reports zero research in both
counts.** It even lists `model_provider` in `fields_used`, asserting the value was consumed.

`[CODE]` The producer is `scripts/lib/data_broker/cio_portfolio.py`, and the value is a
hardcoded literal at **line 429**:

```python
    return {
        "state": "AVAILABLE" if promoted_count > 0 or hermes_status else "DATA_UNAVAILABLE" if not hermes_status else "AVAILABLE",
        "promoted_research_count": promoted_count,
        "staged_research_count": staged_count,
        ...
        "model_provider": "deepseek-v4-flash",
        "fallback": "free-oauth (grok/chatgpt)",
    }
```

**The function makes no model call.** Its entire body is three `SELECT COUNT(*)` /
`SELECT DISTINCT` queries against `hermes_research_intelligence`. The model name is a string
literal describing what *some other* subsystem is configured to use.

**And it degrades silently.** `[CODE]` lines 419–420:

```python
    except Exception:
        pass
```

A bare `except: pass` around the whole DB block. On any failure — connection refused, missing
password, table absent — `promoted_count` and `staged_count` stay `0` and the function returns
the same shape. **A database outage and a genuinely-empty research table are byte-identical at
the surface**, and both still render `AVAILABLE` beside a named model. This is precisely the
collector behaviour the brief warned me about, and it is why every number in this census was
read from the live server rather than recomputed in my shell.

`[CODE]` The brief's exact string also exists, at `scripts/api_v3_cio.py:2360`, in
`get_cio_dashboard()`:

```python
        "model_provider": "deepseek-v4-pro",
        "fallback": "none — fail-closed (VISIBLE_FAILURE_NO_SILENT_FALLBACK)",
```

Same defect, hardcoded literal, on a function that assembles snapshot/actions/delegation/plans
and calls no model. The adjacent `fallback` string advertises
`VISIBLE_FAILURE_NO_SILENT_FALLBACK` on a payload two lines below a hardcoded provider name.
That route (`/api/v3/cio/dashboard`) was not otherwise censused here.

**Both instances are counted in §9 as rows 17–18.** Count (c) is therefore **18**, not 16.

## 10. Agent-originated and model-assisted counts

**This section contains the census's most important correction, and it is a correction to my
own work.** I ran a marker census, got zero, wrote up zero — and the brief's warning was
right. Reading the text found 27 fields of generated prose sitting under a
`writer: "migration:deterministic"` label. **The count is not zero.**

### 10.1 Agent-originated: 27 fields, 24 of them mislabelled `deterministic`

`[VERIFIED]` `instrument_narratives` holds 37 subjects. Splitting them by the *register* of
their `what` field rather than by their marker:

```
writer values across all 37 narratives:
   {'migration:deterministic': 36, 'cognition:defer_honored': 1}

NARRATIVES IN GENERATED-PROSE REGISTER: 9
  HELD:SCHD   writer=cognition:defer_honored   fields=what,thesis_fit,risks[0]
  HELD:XLB    writer=migration:deterministic   fields=what,risks[0],risks[1]
  EXIT:TDG    writer=migration:deterministic   fields=what,thesis_fit,risks[0]
  EXIT:RKLB   writer=migration:deterministic   fields=what,thesis_fit,risks[0]
  EXIT:LGPS   writer=migration:deterministic   fields=what,thesis_fit,risks[0]
  EXIT:TRX    writer=migration:deterministic   fields=what,thesis_fit,risks[0]
  EXIT:DFSC   writer=migration:deterministic   fields=what,thesis_fit,risks[0]
  EXIT:FATN   writer=migration:deterministic   fields=what,thesis_fit,risks[0]
  EXIT:ZSL    writer=migration:deterministic   fields=what,thesis_fit,risks[0]

TOTAL generated-prose FIELDS: 27
```

The other 28 subjects are templates in one of two forms — `Under desk@v5 (posture): …` with
slot-filled `Fire=` / `Posture:` clauses, or `{SYM} is held with no open S1. Observational
lifecycle note only.`

**Why this is prose and not an f-string — three independent signals** `[VERIFIED]`:

1. **Cross-symbol synthesis.** `EXIT:RKLB.what`:
   > *"…The **operator's prior defer on SCHD** signals a cautious stance, and no new evidence
   > overrides that caution **for RKLB**."*

   A template for RKLB does not reach into an operator disposition recorded against SCHD and
   carry it forward as a reason. No slot-filling produces that sentence.

2. **Argued structure with named tension.** `EXIT:RKLB.risks[0]`:
   > *"Primary risk is entering too early without sufficient evidence, contradicting the
   > defensive stance. Secondary risk is missing the reentry if the catalyst is strong, but
   > that is mitigated by the cash buffer and staged approach. No concentration or DD risks
   > are present in evidence."*

3. **Truncation mid-word at exactly 600 characters** — the signature of a generated field
   being length-capped, which an f-string over known values would never produce:

```
  EXIT:TDG   len(what)=600  ends: ': The reentry '
  EXIT:RKLB  len(what)=600  ends: 'k over speed; '
  EXIT:LGPS  len(what)=600  ends: 'ear, not confi'
  EXIT:TRX   len(what)=600  ends: 'watchful stanc'
  EXIT:DFSC  len(what)=600  ends: 'lls. Tension: '
  EXIT:FATN  len(what)=600  ends: '(reentry_NEAR)'
  EXIT:ZSL   len(what)=600  ends: 'isk is not an '
```

**Seven of the nine generated narratives are cut off mid-word on the operator surface.** That
is a rendering defect in its own right, and it is also the cleanest available proof that these
fields are not templates.

**The marker defect, stated precisely.** `[VERIFIED]` Of the 27 generated-prose fields:

| marker | subjects | fields | correct? |
|---|---:|---:|---|
| `writer: "migration:deterministic"` | 8 | **24** | **no — labels the copy step, not the author** |
| `writer: "cognition:defer_honored"` | 1 (`HELD:SCHD`) | 3 | yes — an honest cognition marker |

**24 fields of generated prose are labelled `deterministic` on the live operator surface.**
This is the brief's `[DOC-CLAIM]` promoted to `[VERIFIED]`, at pin `a5006df1`, on the served
release, from the live server. The one subject that carries an honest marker
(`cognition:defer_honored`, `HELD:SCHD`) proves the marker vocabulary is *capable* of
expressing this — it simply is not applied to the other eight.

`[CODE]` Note the interaction with `MBI_COGNITION=1`: the standing rules permit memory to
change `next_research_question`, `next_eligible_at`, `notify_priority` and `cc_narrative`.
`[VERIFIED]` On all nine generated narratives, `next_research_question` is `null`,
`next_eligible_at` is `null`, and `notify_priority` is `"none"` — the three cognition-writable
fields are empty, while the prose fields beside them carry generated content. Whatever wrote
this prose did not record a cognition write against the fields the authority model tracks.

### 10.2 How I got it wrong, so the next part does not

My marker census asked *"which fields carry an agent-originated marker?"* and returned 11
(the `class: "A"` fields, §10.3). My first text pass then examined the 375 prose leaves in
aggregate and I concluded none were generated. **The error was that I grouped the prose by
field path and looked at the invariant groups** — which is the right method for hunt #1 and
the wrong method for this question. Generated prose is *maximally variable*, so it lands in
the "varies across entities" bucket and never surfaces in an invariance scan.

**What actually found it:** sorting all 375 prose leaves by length and reading the longest
twelve. Two of them were in a visibly different register from the other ten. **The signal was
the register, not the marker and not the variance.**

Concretely, for later parts: `Under desk@v5 (defensive_observe): S3_REENTRY_CANDIDATE on ACHV.
Fire=reentry_NEAR.` and `Under desk@v5 / defensive_observe, TDG emerges as a reentry candidate
(S3) with near-term fire, but…` differ by one character of punctuation in their prefix — a
parenthesis versus a slash — and that character is the only structural marker distinguishing a
template from generated prose in this store.

### 10.3 The inverse defect: 11 fields marked `A` that contain no judgment

`[VERIFIED]` The marker census for agent judgment (`class: "A"`) returns 11 fields:
`case_summaries.class` plus `case_summaries.items[0..9].class`.

`[VERIFIED]` Text census of those same 11, masking result-ids:

```
items: 10
DISTINCT content templates after masking result-ids: 2

  [9 items] Hermes research VALID for this case. Result <RRID> closed the research gap
            Situation S3 REENTRY CANDIDATE. Questions answered 1/1. Thesis tension
            remains advisory-only; no order or stop implied.
  [1 item]  Hermes research PARTIAL. Result <RRID> / request <RESID> attached to the
            case. Advisory completeness only.

--- does any item mention its own symbol in its content? ---
  NUAI:False  AIRE:False  BOOK:False  RGNT:False  GXAI:False
  AUUD:False  GXAI:False  BJDX:False  AUUD:False  RGNT:False
```

**Ten research cases across eight distinct symbols produce two sentences. No item's text
mentions its own symbol. No item contains a research finding.** The content reports *that*
research completed and how many questions it answered — never what it concluded.
`"Questions answered 1/1"` is identical on all nine.

### 10.4 Both markers are unreliable, in opposite directions

This is the finding I most want carried forward:

| marker | asserts | reality | count |
|---|---|---|---|
| `writer: "migration:deterministic"` | deterministic | **generated prose** | 24 fields |
| `class: "A"` + banner `A-context` | agent judgment | **two f-strings** | 11 fields |

**Neither direction can be trusted. A provenance marker in this system is not evidence of
provenance in either direction, and every provenance count in every part must be
text-verified.** A census that reads markers will simultaneously over-report judgment where
there is none and under-report generation where it exists — and those two errors do not
cancel, they compound, because they land on different fields.

### 10.5 Model-assisted

**Fields classified model-assisted, distinct from the agent-originated 27: 0** `[VERIFIED]`
on the CIO surface.

I am recording the 27 generated fields as **agent-originated** rather than model-assisted
because they are written into a durable subject record (`instrument_narratives`, keyed
`HELD:`/`EXIT:`, with `from_record: true` and a `writer` field) by the desk agent loop, rather
than being a model call made to decorate a response at render time. **This is a judgment call
about a boundary the brief does not define, and if a later part draws it the other way the 27
move from (a) to (b) — they do not disappear.** What matters is that they are generated and
labelled deterministic.

**Scope limit, stated rather than glossed:** counts (a) and (b) cover the CIO surface —
`/api/v3/cio/home` and the `/v3/cio` tabs. `/rotation`, `/journal`, `/research-intelligence`,
`/defense` and `/hermes` reach model producers and were **not** field-censused. §12.

## 11. `decision_field_parity` — a gate that cannot go green

`[VERIFIED]` live, pin `a5006df1`:

```json
"decision_field_parity": {
  "ok": false,
  "decision_count": 19,
  "surfaces_checked": 2,
  "missing_required": [
    {"decision_id": "dec_73b7ddebfe54b0c2", "surface": 1, "missing": ["recommended_delta_usd"]},
    {"decision_id": "dec_b219249e141ee327", "surface": 1, "missing": ["recommended_delta_usd"]},
    {"decision_id": "dec_f66c157dd02fc150", "surface": 1, "missing": ["recommended_delta_usd"]}
  ],
  "field_mismatches": []
}
```

**The field it reports missing is `recommended_delta_usd`.** That is one of the exact field
names `MBI_BEHAVIOR=0` refuses outright — the standing rules list it first:
*"`BehaviorWriteRefused` raises on `recommended_delta_usd`, `size_usd`, `shares`…"*.

So the parity gate requires a field the authority model forbids the system to emit. **It can
never be satisfied without violating `MBI_BEHAVIOR=0`, and it publishes `ok: false` on the
operator surface on every generation.** A permanently-red check trains the operator to ignore
it, which is worse than not having it — and it is precisely the standing rules' *"a check
whose name promises more than its code verifies"*, in the form where the promise is one the
system must never keep.

`[VERIFIED]` A second, smaller inconsistency in the same block: `decision_count: 19` while
`operator_product.decisions` has **25** members. The parity check and the rendered card list
disagree about how many decisions exist. Both are on the same surface, same payload, same
composition.

**This is an operator-only decision** (it changes what a gate asserts about an operator
surface), so per the standing rules I propose and stop: either the required-field list drops
`recommended_delta_usd`, or the check declares itself `NOT_APPLICABLE_UNDER_MBI_0` rather than
`ok: false`. I have made no change.

---

## 12. What this census did not cover

Stated plainly so nobody reads a gap as a clean result.

1. **981 API paths exist; I field-censused one** (`/api/v3/cio/home`, 5,144 leaves) and
   route-censused 50 frontend routes. Counts (a), (b) and (c) are **CIO-surface counts.**
2. **The model-assisted count (b) = 0 is scoped to the CIO surface.** `/rotation`,
   `/journal`, `/research-intelligence`, `/defense` and `/hermes` reach model producers and
   were not field-censused. **A later part should field-census those five routes before
   anyone quotes a system-wide model-assisted count.**
3. **`command-center-v2` and `broker-admin`** (`apps/`) were not censused. v2 is still served
   at `/v2`. Broker is out of scope by instruction.
4. **`/v3-next/`** is served from `/home/johnclaw/deploy/v3-next/current` — outside every
   checkout, so `TRADEAI_ROOT` neither fixes nor breaks it. Not censused.
5. **`last_changed` is populated only where a durable artifact gave it.** Where a block
   carries no `as_of` and I found no durable store behind it, the column says `none` and I did
   not estimate.

---

## 13. Notes for PART 1 and later parts

1. **Neither provenance marker direction is trustworthy — both are now measured, not asserted.**
   `writer: "migration:deterministic"` labels 24 fields of generated prose (§10.1) and
   `class: "A"` labels 11 template fields (§10.3). **Any provenance count in any part must be
   text-verified, and an invariance scan will not find generated prose** — generated text is
   maximally variable, so it never appears in an invariance bucket. Sort prose by length and
   read the longest; the signal is register, not marker and not variance (§10.2).
2. **Cron runs the dev tree, not the release** (§8.5), for every Aegis job. Any PART 1 finding
   of the form "fixed in module X" needs a second check that the tree cron invokes has it.
   Two morning jobs are crashing on a bug already fixed in `CURRENT`.
3. **`CIO_TELEGRAM_INTERDICT` does not gate the Aegis producers** (§8.2). Any safety
   assumption resting on it covers producer (a) only.
4. **The platform was being promoted every 5–15 minutes during this census.** Any measurement
   taken today without a pin recorded beside it cannot be compared with any other.
5. **`import adjacency ≠ usage`** (§6.5). A near-miss false finding in this census came from
   assuming an imported fixture module meant the fixture data was rendered. Resolve the symbol.
6. **`instrument_narratives` is where the generated prose lives.** If PART 1 censuses stores,
   that store is the one carrying agent-written content under a deterministic label, and its
   `writer` field cannot be used to find it. The template/prose discriminator is a single
   punctuation character in the `what` prefix: `desk@v5 (` = template, `desk@v5 /` = prose.
7. **A 600-character cap truncates generated narratives mid-word before they reach the
   operator** (§10.1). Seven of nine. Whoever owns that store should know.
8. **`data/runtime` is not symlinked** — only `data/cio` and `logs` are. Each release rotation
   orphans the previous `aegis_evening_packet.json`, so evening-packet history is per-release
   and largely lost.

---

## 14. The three counts

Zeros as zeros. All at pin `a5006df1` unless a section states otherwise, CIO surface, scope
limits in §12.

| | count | |
|---|---:|---|
| **(a)** | **27** | fields classified **agent-originated** — generated prose in `instrument_narratives` across 9 subjects. **24 of the 27 are labelled `writer: "migration:deterministic"`** (§10.1). A marker census returns 0 for this and 11 for a different, wrongly-marked set; both are wrong. |
| **(b)** | **0** | fields classified **model-assisted**, as distinct from the agent-originated 27. Boundary call explained in §10.5. Scoped to the CIO surface — §12.2. |
| **(c)** | **18** | fields classified **template/deterministic but rendered in a register implying agent judgment**. This is the defect list, §9. |

Separately, and not folded into the above because it is a labelling defect rather than a
provenance class: **11 fields carry an agent-judgment marker (`class: "A"`) and contain two
f-strings** (§10.3).

**Can an operator distinguish a field's provenance class from the one beside it?**

**No — and the markers actively mislead in both directions.** 372 of 375 prose fields carry no
class marker at all; the legend for the 3 that do was computed and dropped before serving
(§6.3); 24 fields of generated prose are labelled `deterministic`; and 11 template fields are
labelled agent judgment. On the `instrument_narratives` store specifically, the only thing
distinguishing a generated narrative from a templated one is whether the prefix reads
`desk@v5 (` or `desk@v5 /`.

**The single most consequential row on the surface** — the PORTFOLIO-level `HOLD`, first thing
the operator reads — has a hardcoded constant for its `reason`, an invariant disclaimer for
its `counter_evidence`, `null` for its `confidence`, and no `as_of` on the cash it reasons
about.
