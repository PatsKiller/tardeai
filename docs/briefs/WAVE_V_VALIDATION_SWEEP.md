<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Validation sweep V0-V5

**Status:** recovered verbatim
**Source:** session transcript, operator message 026

---

Claude Code Execution Prompt — VALIDATION SWEEP: what of this can actually be reproduced?
This supersedes P11.1–P11.8. Do not continue the Phase 11 packages until this is done.
A production census script has been unable to compile — NO_CONSUMER_REASON inserted above
from __future__ import annotations — and two scoreboard metrics derived from it were
presented as current state while the script could not run. The parse sweep that should have
caught it used ast.parse, which does not enforce __future__ placement.
The operator's assessment is that the programme's maturity claims are not supported. Treat
that as the working hypothesis, not as something to argue with.
[VERIFIED] / [CODE] / [DOC-CLAIM] tagging applies to every line. In this sweep,
[VERIFIED] means you regenerated the number today from a script that ran to exit 0.
Nothing else qualifies.
V0 — Fix the two compile failures, then trace the cause
Fix both files. One-line each.
Establish which change inserted NO_CONSUMER_REASON at line 1 — git log -S on that
file. If it came from the dark-contract gate work in this programme, say so plainly. "Pre-
existing, not mine" is a claim that needs a commit behind it.
How long has the census been unrunnable? Every scoreboard, gap register, and diligence
document published in that window quoted numbers it could not have produced.
V1 — Every gate that inspects source must use compile(), not ast.parse
Replace ast.parse with compile() in every gate, sweep, or check that asks "does this
file parse."
Re-run the repo-wide sweep with compile() and report the full failure list, not a sample.
Mutation-test the dark-contract gate against this specific failure: a file whose
declaration was inserted in a position that breaks compilation must fail the gate. If it
passes, the gate is unsound and says so in its own output until fixed.
Any gate that modifies source must verify the file still compiles, and where feasible
still imports, before reporting success. A guard that edits a file and doesn't check its
own edit is the defect this programme exists to close.
V2 — Regenerate every published number
For every metric appearing on the diligence scoreboard, in the gap register, and in the
NOW block — including but not limited to lineage completion, both event-lifecycle
percentages, the catalyst family rate, identity resolvable percentage, arc counts, and first-
open-stage counts:
Produce a table with one row per metric:
metric
published value
regenerated today
producing script
exit code
verdict
Verdicts: VERIFIED_FRESH · STALE (script runs, value has moved) · UNRUNNABLE (script
cannot execute) · NO_PRODUCER (nothing generates it).
Any metric that is not VERIFIED_FRESH is struck from the scoreboard, replaced by its
verdict. A number nobody can regenerate is not a measurement.
V3 — Re-verify the DONE column
Nine diligence packages are marked DONE. For each, the claim is that a proof artifact exists.
For each package:
Does its proof script or test regenerate its stated evidence today, from the served
release, exit code checked for the specific expected value?
Does the evidence still support the conclusion recorded, or has the underlying state moved?
P5 recorded an honest FAIL at the check level while the package reads DONE. Establish
whether any other package is DONE over a failing check.
A package whose evidence cannot be reproduced is not DONE. Change the status. Do not
re-run a check hoping for a better number.
V4 — The board and the gates
Re-run the preconditions board and report each check with the artifact type it actually
verified, not just green/red. One false green has already been produced by a check whose
name promised more than its code verified.
For every CI gate in the pipeline: when did it last actually execute, and does its most
recent run reflect current main? A gate that has not run is indistinguishable from a gate
that passed.
Confirm the six-plus cron and systemd jobs installed during this programme have each left
durable evidence on their natural schedule — not a hand-run, and checked against both
schedulers.
V5 — State the honest maturity position
One page, no hedging, written for the operator:
What is verified to work at runtime today, with the command that proves each item.
What is built and unwired.
What is claimed and unverifiable.
The count of agent-originated fields reaching any operator surface.
Whether any scheduled process reads the InstrumentRecord spine before acting.
If the conclusion is that the programme has produced a mature audit apparatus attached to an
immature agent, write that. An honest low score is worth more than a defended high one, and
the operator has already reached this conclusion independently — a report that disagrees with
it needs evidence, not phrasing.
Explicitly not in this sweep
No new capability. No new gates beyond fixing the unsound one. No new phase packages. No
edits to the gap register's status column until V3 establishes what is actually DONE.
Standing constraints
Check exit codes for the specific expected value. Exit 2 for an absent script reads as
a pass. $? after a pipe is the pipe's status, not the command's.
Verify from the served release, independently of PROMOTE OK.
Route edits through safe_text_edit; line-ending gate clean before pushing.
Follow symbols to real write calls; filename greps have misled this work repeatedly.
Read tracebacks whole.
One PR per finding, validation output quoted in the body.
Pushing and merging require explicit authorization per AI_WORK_POLICY.md §3.
