# WAVE <n> — <short name>

**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · MBI_COGNITION=1.
Standing rules are in `/AGENTS.md` and are not restated here.

## Objective

One paragraph. What this wave is for, in terms of a capability that will exist
afterwards and does not exist now. Not a list of tasks.

## Packages

One per unit of work. Each states what it does and what it must not do.

### <P1 · name>

What to establish or build. Phrase measurements as a **question and a
threshold**, never as a value:

> Measure X from source with an `as_of`. Report it whatever it is. The threshold
> for concern is <condition>.

If a package has a default the operator will accept, state it, so the work does
not park waiting for an answer that was already given.

## Ordering

State what is serial and why the order is load-bearing. State what may run in
parallel, with declared file sets and store sets — overlaps are serialized.
Registration before filtering, fixes before the gate that enforces them.

## Acceptance — an observable runtime event

What must be **observed**, from the served release, with the command quoted. Not
a test suite, not a CI pass, not a percentage. Name the event:

> A scheduled wake loads record R, honours a disposition set N days earlier, and
> field F changes. Show the diff.

`NOT OBSERVED` is an acceptable result and should be stated as acceptable here,
so a truthful negative is not something the wave has to overcome.

## Out of scope

What this wave must not touch, especially anything adjacent that would look like
a natural extension.

## Operator-only

Decisions to propose and stop on, beyond the standing list in `AGENTS.md`. If
this section is longer at the end of the wave than at the start, that is a
finding about how the wave was run.
