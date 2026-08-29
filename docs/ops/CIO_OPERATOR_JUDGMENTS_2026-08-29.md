# CIO — operator judgments of 2026-08-29, implemented

Authority: **READ_ONLY_ADVISORY** · MBI **0** · INTERDICT **0** (left as found)
CURRENT pin at dry: `e0fd5d2e` · all five endpoints 200

Only the authorised items. No cap raised, no live Hermes, Wave 3 not started.

---

## Decision 1 — ban the instruction, not the words

The root cause named in the judgment was correct: *two gates with disjoint
vocabularies is why `execute the buy` slipped.* Widening two substring lists
would have kept that shape and eventually cost the 466.

**`scripts/lib/execution_language.py` is now the single definition**, used by
both `hermes_research_schema.lint_execution_language` (ingest) and
`research_quality.critique` (attach).

The rule is **grammatical, not lexical**: a base-form verb from
`{buy, sell, trim, flatten, liquidate, submit, place, execute, exit, short,
cover}` followed by a size-or-object, **disqualified** when the verb is preceded
by a determiner (noun), a modal (conditional), an infinitive `to` (narration) or
a negation.

| rejected | admitted |
|---|---|
| trim the position | a trim would reduce concentration |
| sell half | sold half in 2021 |
| execute the buy | after the 2018 trim |
| place an order | management will execute its buyback plan |
| buy now · flatten · liquidate the position | the order book was thin |
| sell 50% · exit the position | no trim of the position occurred |

`trim` / `sell` / `half` are never banned as vocabulary. `option_id` values
(`trim_if`, `hold_with_thesis`, …) are explicitly **not** this gate — running
research rules over the operator's own vocabulary would reject it.

### The 466 is intact

Measured before wiring anything: exactly **one** stored artifact would have
newly failed — an SRNE result reading *"exit the position"*, whose plan is
already cancelled. Grandfathered anyway, because the rule is a rule.

```
completed results          468
attachable before          466
attachable after           466   ← unchanged
```

`IMPERATIVE_GATE_EFFECTIVE = 2026-08-29T05:00Z`. Artifacts completed before it
keep the verdict they were admitted under; an **undated** artifact is treated as
pre-existing. The legacy floor (`ignore all rules`, `place an order`) still
applies to every result, new or grandfathered — nothing is loosened.

Tests are named as instructed: `legacy_admitted` pins what is admitted today,
`new_rejected` covers the tighter phrasings.

### A regression this caught

Rewriting the matcher initially dropped bare `execute trade` / `place order` —
forms the old pattern *did* catch. The suite caught it; bare objects are
restored and asserted.

---

## Decision 2 — name the gap, pick nothing

```
cash_rows      630784.82   source=position_rows
cash_totals    578107.50   source=portfolio_totals
cash_gap        52677.32   status=UNRECONCILED
cash_for_S5    DATA_UNAVAILABLE_UNTIL_RECONCILED
```

No average, no winner in the renderer. `cash_total_sources()` carries
`cash_status`, `cash_gap`, `cash_for_s5`, both sources labelled with their role,
and `writer_identified: false` with the next slice named on the payload itself.
The brief prints all four lines and **leads with neither figure** — it
previously led with `temperament.cash`, which is the flip the judgment refers to.

`cash_for_s5` only becomes a number when the two writers agree.

### A crash this caught

`temperament.cash` is not always numeric — a real payload carries
`"hold reserve"`. `float()` on that raised inside the renderer and took the
morning brief down. That was introduced when `cash_lines` was first added to the
brief and was **not** caught by acceptance or CI; it surfaced only when the wider
suite was run. Every read now goes through a numeric guard, and a present but
unusable value is *named* rather than dropped.

---

## Also authorised — applied, dry first, backed up

| action | dry | applied | notes |
|---|---:|---:|---|
| DIVI observational S1 | 19 | **19** | `not_held`; **`DIV` untouched** (1 open, held) |
| duplicate S1, revisit-overdue only | 85 | **85** | ARKX 24 · SCHD 20 · XLI 21 · SPCX 13 · NOC 7 |
| accepted S0 carrying `TEST` | 1 | **1** | `plan_a18173fb8235` |
| item 118 cost-basis `as_of` | — | done | on the coverage card |

**Newest per symbol was always kept**, and a duplicate whose `revisit_at` is
still in the future was left alone — redundant is not stale. On the live book
that left 0 such plans, but the rule is enforced and tested rather than assumed.

```
open S1        120 → 16        duplicates  NONE
DIVI 0 · DIV 1 (held, untouched)
held non-dust coverage 15/15   TEST plans open: NONE
cio_plans.jsonl 5,104 → 5,314 lines — append-only, nothing deleted
```

### Item 118 found something

The three dates are genuinely far apart:

```
cost_basis_as_of   2026-08-14      sources: broker_api, csv_lot
positions_as_of    2026-08-26
priced_as_of       2026-08-28
```

Two weeks between basis and price. A reader assuming "now" was wrong on all
three counts, which is exactly why the item was worth doing.

### Not done, as instructed

The **148 CASH-bound and 50 dust-bound historical checkpoints** were left
untouched. New binds already skip CASH and dust; the jsonl is not rewritten.

---

## Rails

| Rail | State |
|---|---|
| The 466 | **intact** — measured, not assumed |
| Retroactive detachment | none — grandfathered by completion date |
| Word bans on trim/sell/half | **none** — the rule is grammatical |
| `option_id` surface | out of this gate, asserted |
| Cash | both printed, never averaged, S5 refuses a number |
| History | append-only, 5,104 → 5,314 |
| Caps / live Hermes / Wave 3 | untouched, not run, not started |
| MBI / INTERDICT | 0 / 0 |

## Tests

**403 passing run together.** New: `test_execution_language_shared_gate.py`
(50 — `legacy_admitted`, `new_rejected`, one-matcher, grandfathering,
`option_id`), `test_cash_unreconciled_law.py` (19, including the non-numeric
crash), `test_cio_duplicate_s1_hygiene.py` (7), and
`test_cio_item118_cost_basis_as_of.py` (4).

Four earlier tests encoded behaviour these judgments deliberately reversed and
were updated rather than worked around, each with a note saying what superseded
it.

## Known pre-existing failure, not from this work

`tests/test_research_skip_gate.py::test_run_apply_skip_gate_blocks_metered`
fails on unmodified `origin/main` as well — verified by stashing. Not
investigated further; flagged so it is not mistaken for fallout.
