# Field-scoped instruction lint (2026-08-29)

> **SUPERSEDED IN PART (2026-08-29).** This document records that a
> `do not <verb>` rule was impossible without breaking the pinned
> ex-date case. Measuring the corpus disproved that: they separate on
> clause position and on a settlement qualifier. The rule now ships and
> the pin still passes. See
> [CIO_PROSE_PROHIBITION_GATE_2026-08-29.md](CIO_PROSE_PROHIBITION_GATE_2026-08-29.md).


Closes the half of the matcher gap that a global rule could not.

## The problem a shape-based rule cannot solve

The live Grok critique flagged two things in one artifact. The first —
"Maintain small tracking position" — was fixed by adding position-directive
verbs. The second was **"do not add until price action confirms"**, and a
global `do not <verb>` rule was written and then removed, because it breaks a
pinned legacy case:

    "do not sell shares before the ex-date"      <- ex-dividend CONTEXT, admitted
    "do not add until price action confirms"     <- an INSTRUCTION

They are **grammatically identical**. No pattern separates them by shape.

## Separate by location instead

`desk_implications.notes` and `recommendation` exist to tell the operator what
the desk thinks should happen. A summary does not. So the same phrase can be
strict in one place and admitted in another, without reading intent.

The corpus says this is safe. Across 471 stored artifacts:

    `do not <verb>` inside those fields          57  (56 "do not add", 1 "do not buy")
    of those, also mentioning ex-date/ex-dividend  0

The ambiguous case **does not occur where instructions live**. Real examples:

> "do not add, do not average down, and either exit or demand a verifiable…"
> "Do not add to position; treat as speculative lottery ticket or exit."
> "Maintain tight risk controls; do not add exposure at current levels."

## What was added

`execution_language.find_field_directive(artifact)` — returns
`{field, match, rule}` or None. It applies the ordinary matcher **and** the
`do not <verb>` rule, but only to the declared fields:

    INSTRUCTION_FIELDS = desk_implications.{notes,note}, recommendation

`describe_field_directive()` gives the receipt shape, so a rejection names the
field and the rule rather than just failing.

Free-prose entry points — `find_imperative`, `lint_execution_language` — are
**unchanged**. That is what keeps the pin passing.

Wired into `research_quality.critique()` behind the existing
`imperative_gate_applies()`, so the same grandfather boundary applies.

## Effect on the corpus

    471 scanned
      field-directive hits :  47
      actually GATED       :   0      <- every one grandfathered

The rule bites on new research only. Nothing is retro-detached, per Decision 1.

## Behaviour, verified end to end

| artifact | verdict |
|---|---|
| gated, `notes: "do not add exposure"` | **FAILED** — `forbidden_authority`, `instruction_in_desk_implications.notes` |
| same, dated before the boundary | VALID — grandfathered |
| gated, ordinary notes | VALID |
| gated, ex-dividend phrase **in the summary** | VALID — the pin holds |

## Tests

17, including: the same phrase strict in a field and admitted in prose; the
alternate `note` key one stored artifact uses; only the declared fields read
(`findings` is not); malformed and missing artifacts do not raise; and the
grandfather boundary honoured.

211 green across the matcher's consumers; acceptance green.

## Still not done

A prohibition in *free prose* remains admitted. That is deliberate — it is the
only way the ex-dividend pin survives — and it is now a much smaller hole,
because the fields where instructions actually appear are covered.
