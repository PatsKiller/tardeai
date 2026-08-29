# Prose prohibitions are instructions — closing the "do not add" misses

**Date:** 2026-08-29 · **Authority:** READ_ONLY_ADVISORY · **MBI:** 0
**Supersedes:** the "NOT IMPLEMENTED" decision in
`docs/ops/CIO_MATCHER_POSITION_DIRECTIVES_2026-08-29.md`
**Related:** `docs/ops/CIO_FIELD_SCOPED_LINT_2026-08-29.md`

## The gap

`execution_language.find_imperative` listed `not` / `never` in `_DISQUALIFIER`,
so a negated verb was read as narration:

```
#   not/never -> negation   ("do not sell")
```

That was the error worth naming. **A prohibition is an order.** "Do not add to
the position" tells the operator what to hold as surely as "trim the position"
does. Free prose carrying `do not <verb>` passed the gate everywhere.

The previous decision recorded this as unfixable:

> The two are grammatically identical — `do not <verb>` in both — so no rule
> separates them without reading intent. […] Between losing 38 "do not add"
> catches and breaking a pinned admitted case, the pin wins.

The pinned case is `"do not sell shares before the ex-date"`, asserted in three
test files as ex-dividend context.

## Why that was wrong

Measuring the 471 stored artifacts instead of reasoning about the grammar
showed the two are separable on axes that need no intent-reading.

**1. `do not sell` and `do not buy` never occur in prose at all.** The pinned
phrase is a synthetic fixture. What distinguishes it is therefore not its verb.

**2. Clause position.** Every real directive is a subject-less imperative;
every false positive is a declarative with an inanimate subject.

| class | verbs | n | shape |
|---|---|---:|---|
| directive | `initiate` 38, `add` 7, `average down` 3 | 48 | "hold in monitored state, **do not initiate** new put selling" |
| declarative | `support`, `meet`, `alter`, `change`, `confirm`, `constitute`, `trigger`, `upgrade` | 18 | "the evidence **does not support** …" |

**3. A settlement qualifier.** The pin is not portfolio authority, it is a
tax/settlement caution — what makes it context is the *ex-date*, not the verb.
No directive in the corpus shares a **sentence** with one, and the pin cannot
be written without one.

The qualifier scope is the sentence, not the field. Four artifacts pair a real
directive with an ex-date mentioned elsewhere in the same long field; a
field-wide carve-out would have wrongly exempted all four.

## The rule

In `scripts/lib/execution_language.py`, a third pattern in `find_imperative`:
`do not <position verb>` fires unless

- a subject precedes it (declarative, not imperative), **or**
- a slash/pipe precedes it (a compound stance label, not a clause), **or**
- a settlement qualifier shares its sentence (ex-date, ex-dividend, record
  date, wash sale, lock-up, blackout, settlement, T+n).

`not` / `never` stay in `_DISQUALIFIER` for the other two patterns; only the
prohibition pattern reads them as instruction.

## The stance-label carve-out was found by measuring, not by design

The first cut failed two live artifacts, AUUD and BJDX:

> "The advisory on AUUD remains **HOLD / DO NOT INITIATE**."

Here the phrase is a **name for an advisory state**, the same category as
`hold_with_thesis`, which this gate has always admitted. A slash separates
label parts; sentence punctuation separates clauses. Only the latter opens an
imperative. That carve-out removed 13 of 46 catches — every one a false
positive that would otherwise have shipped.

## Effect — measured against the #658 baseline, not against nothing

| measure | value |
|---|---:|
| stored artifacts | 471 |
| prose occurrences the rule now sees | 33 |
| artifacts flagged by the **#658 pipeline** | 59 |
| artifacts flagged by **this rule + #658** | 59 |
| **NEW artifacts flagged** | **0** |
| newly **FAILED** (not grandfathered) | **0** |

**This adds no artifact-level coverage on the current corpus, and the first
draft of this document wrongly implied it did.** All 33 prose catches also
carry the same directive in `recommendation` or `desk_implications.notes` —
the writer repeats itself — so the field-scoped lint had already failed every
one of them. Counting occurrences (45) made the gap look larger than the thing
that actually gates PASS/FAIL, which is the artifact.

The rule is therefore **defense in depth, not new coverage.** What it closes is
the case the field lint structurally cannot see, because that lint reads two
fields and prose is not one of them:

```
summary: "AUUD remains a speculative holding as of 2026-08.
          Do not add to the position until price action confirms."
(no recommendation, no desk_implications.notes)

  #658 field lint : None             <- passes
  this rule       : 'Do not add to'  -> FAILED / forbidden_authority
```

Zero of 471 stored artifacts have that shape. Nothing guarantees the next one
will not: a writer that puts the directive in `summary` alone defeats #658
entirely. That is the whole of the benefit, and it should be weighed as such.

Newly reachable fields: `answers[].detail`, `summary`, `answers[].summary`,
`what_did_not_change[]`, `reason_summary`, `findings[].text`.

Nothing is retro-detached: `IMPERATIVE_GATE_EFFECTIVE = 2026-08-29 05:00Z`
grandfathers all 33, per Decision 1 ("do not retro-detach the 466").

## Receipt fix

`research_quality.critique` short-circuited: when `find_imperative` fired it
never ran the field lint, so a failed artifact stopped naming **which** field
carried the instruction. Both now run — the matcher decides PASS/FAIL, the
field lint supplies `instruction_in_<field>` for the receipt.

Correspondingly `find_field_directive` checks the negation rule *before*
`find_imperative`, so the more specific `directive_negation` label survives.

## Tests

`tests/test_execution_language_shared_gate.py` — 6 directive shapes taken
verbatim from the corpus, 10 admitted cautions/declaratives, the
sentence-scope case, 3 stance labels, and the slash-vs-punctuation
discriminator. `test_legacy_admitted` is unchanged and passes.

`tests/test_cio_grok_critique_lane.py::test_do_not_add_stays_admitted_because_the_pin_wins`
is replaced by `test_a_prohibition_is_an_instruction_but_a_settlement_caution_is_not`,
which asserts both halves hold at once.

524 tests green across the 23 suites touching the gate; `ai_local_acceptance.sh
cio` green on all six flags.
