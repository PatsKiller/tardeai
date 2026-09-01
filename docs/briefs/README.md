# Wave briefs

Status:      ACTIVE
as_of:       2026-08-30T22:01:17-04:00
Measured at: efcc51365 / not measured

A **brief** is the instruction that starts a wave of work: what the wave is for,
what it must not do, and what would count as having finished. It is written by
the operator and it is the authority for that wave. These files exist so a
session can start from a path instead of a paste, and so a later reader can see
what was actually asked rather than what the work turned out to be.

**Naming:** `WAVE_<n>_<slug>.md`, where `<n>` is the wave's own identifier as the
operator used it — `2`, `3A`, `3D`, `12`, `V` — not a running count. A wave that
is a continuation keeps its number and gains a slug (`WAVE_12_CONTINUED_...`).

## The one rule about content

**A brief states questions and thresholds. It never states current measured
values.**

Not "lineage completion is 55.9%, raise it" but "measure lineage completion and
report it; the threshold for concern is any drop against the previous as-of."
Numbers embedded in a brief have been refuted every single time one was
embedded, because the measurement moves between the writing and the reading —
sometimes within the same session. A brief that carries a number instructs the
next reader to defend it, and the pressure runs toward making the number true
rather than finding out what is.

Thresholds are fine. Questions are fine. Readings are not.

## Verbatim, or a stub

Every file here is either the operator's text exactly as sent, or a stub saying
the text was not preserved. Nothing in between.

Where a brief was not recovered, the stub says so and stops. It would be easy to
rebuild one from a later summary, and the result would read as authoritative and
would never have been sent — the manufactured-evidence pattern the standing
rules forbid, aimed at the instructions themselves. An honest gap is worth more
than a plausible reconstruction, because a reader can act on a gap.

The provenance header at the top of a recovered brief is the only text in it
that is not the operator's.

## Standing constraints

Briefs do not restate the authority rails, the evidence vocabulary, the
multi-agent protocol, the deploy protocol, the maturity proofs, or the
operator-only list. Those live in `/AGENTS.md` and load automatically. A brief
references them; when a brief and `AGENTS.md` disagree, the safer instruction
wins and the disagreement is itself a finding worth reporting.
