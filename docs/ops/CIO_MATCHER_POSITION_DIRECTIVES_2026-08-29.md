# Imperative matcher — position directives (2026-08-29)

Found by the system critiquing itself. The one live Grok critique rejected an
artifact the shared matcher had passed as clean:

> *"Maintain small tracking position with hard invalidation; do not add until
> price action confirms forward-looking signals."*

`find_imperative()` returned **NO MATCH** on the whole artifact.

## Why it was missed

It failed on **both halves** of the clause pattern
`(?<!\w)(VERB)\s+(OBJECT)(?!\w)`:

- `maintain` was not in `_VERB` — the set was
  `buy|sell|trim|flatten|liquidate|submit|place|execute|exit|short|cover`
- `position` was not a bare `_OBJECT` — only
  `order|stop|trade|fill|shares|now` were, so an unarticled "…position" never
  paired

Telling the operator what *size to hold* is an instruction as surely as telling
them to sell.

## The fix, and why it is a separate pattern

`maintain | add (to) | keep` + `position | stake | holding | exposure | weight |
shares`, with up to three adjectives between — the live miss was "maintain
**small tracking** position", which an adjacent-only pattern skips.

Kept **separate** from `_VERB`/`_OBJECT` rather than widened into them. Adding
`position` as a bare object would also pair it with buy/sell/trim and balloon
the radius across the whole corpus. Scoped this way the addition is measurable
and small.

`keep` was included alongside the requested `maintain`/`add`: "keep the
position" is indistinguishable in kind from "maintain the position", and
omitting it would ship a guard with a hole the same shape as the one being
closed. It is one token in `_POSITION_VERB` if unwanted.

## Blast radius, measured before shipping

    471 stored artifacts scanned
      already caught by the old matcher :  1
      NEWLY caught                      : 24  (5.1%)

        maintain current position        7
        maintain position                5
        keep a small tracking position   4
        add exposure                     2
        keep the position                1
        maintain cash position           1

Every sampled hit is a genuine operator-directed instruction.

**Nothing is retro-detached.** `research_quality.IMPERATIVE_GATE_EFFECTIVE`
(2026-08-29 05:00Z) grandfathers **468 of those 471**, exactly as Decision 1
requires ("Do NOT retro-detach the 466"). Only 3 stored results are gated by the
new rule at all.

## What was deliberately NOT done

The critique also flagged **"do not add until price action confirms"**, and a
prohibition is arguably an order. A `do not <verb>` rule was written — and
removed again.

It breaks a pinned legacy case:

    "do not sell shares before the ex-date"

which `test_legacy_admitted` requires to pass, because it is ex-dividend context
rather than an instruction. The two are **grammatically identical** — `do not
<verb>` in both — so no rule separates them without reading intent.

Decision 1 governs: ban the instruction, never the word, and do not torch the
466. Between losing 38 "do not add" catches and breaking a pinned admitted case,
**the pin wins**. That trade is recorded here rather than buried, because the
38 are real misses and someone may later decide differently with a
field-scoped rule (e.g. lint `desk_implications.notes` more strictly than free
prose).

## Verification

The artifact that started this now returns `Maintain small tracking position`.

15 new tests: seven position-directive forms caught, nine ordinary-prose probes
still clean (`hold_with_thesis`, "the position is small", "we maintain a neutral
view", "maintained the position last quarter", "would add exposure if
confirmed", "decided to add shares in March", "a maintenance release"), existing
catches unaffected, and the `do not` trade pinned so it cannot be silently
reversed.

271 green across the matcher's consumers; acceptance green.
