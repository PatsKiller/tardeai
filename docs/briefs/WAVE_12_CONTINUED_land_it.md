<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 12 continued — land it, then build

**Status:** recovered verbatim
**Source:** session transcript, operator message 033

---

Claude Code Execution Prompt — WAVE 12 CONTINUED: land it, then build
Authority: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · MBI_COGNITION=1. Nothing here changes
execution authority. No order, no size, no broker write, at any point, for any reason.
Wave A is in. Two branches are stranded behind a permission block, M4 is confirmed FALSE, and
7 of 22 published metrics survive regeneration. This prompt lands the finished work first and
then continues.
Nothing in Waves B–F begins until Wave A-CLOSE is live and verified. The programme has
produced far more measurement than shipped capability, and stacking further branches behind
stuck ones makes that worse.
WAVE A-CLOSE — Get the finished work into production (serial, first, no exceptions)
Two artifacts are complete, verified, acceptance-green, and unpublished:
branch
commit
state
fix/v1-v5-sweep
fb5a95a5
local only — no push, no PR
fix/wire-the-compile-guard
18d3ef47
pushed, no PR
Do not route around the permission block. Stopping at it and saying so was the correct
behaviour and it stays correct. If publishing is still denied, stop again and report — do not
find another path, do not use an alternate remote, do not shell out to a different tool.
Once the operator has granted the rule or pushed by hand:
One PR per branch. Quote the validation output in each body.
Merge in dependency order — the compile guard first, since the sweep's findings are read
through it.
Deploy: detach onto the merged commit, prepare, promote, then verify the live
directory independently. PROMOTE OK has re-pinned a stale release before.
From the served release, prove three things and quote each:
the compile guard fails on an uncompilable file and passes on a fixed one, exit codes read
directly, not through a pipe;
the lifecycle census runs to exit 0;
logs/ is still a symlink to persistent state.
Report the live pin. Then continue.
WAVE A-RECONCILE — Four findings that must land before B (parallelizable, disjoint files)
R1 · Kill the self-validating test. test_cio_diligence_scoreboard.py asserts == 406 and
== 54.0 by reading those literals out of the file it validates. It is green forever and
validates nothing, and it would have passed throughout the ten-hour window. Either assert
against a freshly regenerated value or delete it. Do not update the literals — that
reproduces the defect with newer numbers.
Then sweep for the shape: any test whose expected value is read from the artifact under test.
Report the list; fix or delete each.
R2 · The two NO_PRODUCER metrics. Three keys in P4's evidence JSON are emitted by no
script in the repository. Find the producer or establish there is none. If there is none, those
numbers were never measured — strike them, and change P4's status from DONE, since its
evidence cannot be regenerated. Do not reconstruct a producer to justify a published number.
R3 · as_of on every emitted metric. (Standing rule, and the fix for the phantom
disagreement.) Four measurements of lineage completion — 447/800, 448/803, 450/805 and one
more — were all correct at their own timestamps and none comparable, because the store appends
live and the metric carries no as-of.
Every metric-emitting script stamps as_of and the root it read.
Every published number carries its as-of wherever it is displayed or compared.
Add the rule to the multi-agent protocol below: two measurements of a live-appending store
are not in conflict unless they share an as-of.
R4 · Record the two method findings durably. relatime makes file atime useless as
evidence of a live consumer. TRADEAI_ROOT can neither fix nor break the lineage collector,
because that store sits at an absolute path outside every checkout — four runs, both cwds,
identical output. Both are conclusions that were dropped rather than defended; write them where
the next investigation will find them, not in a comment.
WAVE B — The catalyst pipeline (strictly serial; order is load-bearing)
Registration before filtering mints junk into the registry permanently.
B1 · Filter research-directive slugs at ingestion. They are not securities and must never
reach identity resolution.
B2 · Constrain the extractor to a known ticker universe. Any 1–5 uppercase run is not a
symbol. SSDI, IRMAA, TO, NEED, FIND are English words and acronyms scraped from prose.
B3 · Register the ~149 real names deliberately. One at a time, each verified against the
real universe. This is the only genuine registry gap. Do not widen a rule to catch them.
B4 · Re-measure catalyst completion from source, with an as-of. Not from a pre-computed
tally. State the number honestly whatever it is.
B5 · The stale catalyst source. Graph and momentum files are days old. Find the writer,
establish whether it is scheduled, and if this is the served-copy split again, fix it at the
resolution layer rather than the cron's working directory.
Keep the identity guard exactly as it is. Refusing to bind an unrecognized symbol is correct —
an edge to the wrong company is worse than a missing edge, as the module's own docstring says.
WAVE C — Close the loop
C1 · A scheduled wake loads the record before acting. (Proof M5.) Wire load-by-subject
into the scheduled wake path ahead of everything else. Prove a days-old disposition is honoured
under cron with nobody replaying it. Enumerate every producer; state which write the record and
which side-store.
C2 · The frozen notification arc. One arc has grown by dozens while the other has not moved.
Establish whether it stopped running, runs and writes nothing, or writes under a key the
predicate misses. Report when it stopped and what changed. This is the arc the operator's
notifications come from.
C3 · Checkpoint → outcome → lesson under schedule. Establish whether horizons are
legitimately future-dated — an acceptable answer — or the due query is wrong. Emit nothing for
workflows that did not complete; a manufactured lesson permanently poisons the store.
C1 and C2 run in parallel. C3 waits on both.
WAVE D — Judgment (serial; defaults specified so nothing parks)
D1 · The retired overnight window. Establish why it was retired. If quality or supersession,
stop and report. If cost, the enforced cap now governs it. Discard the backlog, do not drain
it — jobs raised months ago were raised against positions, prices and theses that have moved,
and draining produces confident wrong analysis aimed at the operator's phone. Re-raise from
current state. Do the cap arithmetic first and write the number down. If the lane cannot run
meaningfully inside the cap, that is the finding.
D2 · Critique changes the question. (Proof M2.) A critique verdict must move
next_research_question, not sit beside it. CognitionNoOp already exists for writes that move
nothing — use it. Prove it on a live record, on schedule, not by hand.
D3 · Research reaches the record. (Proof M1.) A completed result must attach to the plan it
was raised for and change a named field. Show the before/after diff.
D4 · Research→action policy — default specified. The gate encodes
POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION. Default: a research-backed positive delta
may raise notify_priority, change cc_narrative, and set next_research_question. It may
never touch size, weight, order, or any behaviour field — BehaviorWriteRefused continues to
raise on all of them. That is MBI_COGNITION=1 inside its existing definition; MBI_BEHAVIOR
stays 0. Implement it. If a case appears the default did not anticipate, stop and report.
D5 · The cash letter becomes real prose. Keep every guard: closed option-id set,
standalone_sell always false, refusal of any "deploy $N into TICKER" construction. The shell
is correct; only the text changes.
WAVE E — Delivery and consistency
E1 · opportunities.reentry_total — first, because it is on a money surface. A three-way
branch makes it 25, 70, or 43 depending on the day's data, in the field position that reads as
the total of the list above it, and reentry_pipes — the map that exists to bind fields to
pipes — omits exactly that field. Either bind it to one book or rename and label it so the
reader knows which population it counts. Add it to reentry_pipes either way.
E2 · Per-block as_of. 19 of 31 payload blocks inherit a composition timestamp instead of
carrying their own. Every cash number is in that group. Cash blocks first.
E3 · Provenance at the point of display. Every operator-facing field carries its class. The
unconditional constant serving as cash guidance either becomes conditional on real state or
stops being rendered as guidance. Fix the footer asserting a model provenance for a brief no
model produced.
E4 · Surface scope labels. The two re-entry books answer different questions and are both
correct. Each states its question and population. No merge, no precedence.
E5 · The earnings field. Data is ingested at scale and the field ships empty. Ship what the
data supports — dates and events are honest; implied analysis the system did not perform is not.
E6 · New names reach a surface, behind a labeled section marking them as unheld candidates.
E7 · Alert routing. Critical on money surfaces immediate, everything else digest, no deploy
gate, dedupe applies.
WAVE F — The maturity report
The five proofs, each OBSERVED with command and output, or NOT OBSERVED with the specific
blocker. NOT OBSERVED is an acceptable result.
What runs at runtime today, each with the command that demonstrates it.
What is built and unwired.
What is claimed and unverifiable.
The count of agent-originated fields reaching any operator surface.
The regenerated metric table with as-ofs, and the current VERIFIED_FRESH count out of the
total. It was 7 of 22.
Every decision still genuinely the operator's — and the list must be shorter than the one
this prompt starts with.
Multi-agent protocol
Parallel is for independent investigation, disjoint fixes with declared file sets, and tests
for separate modules.
Never parallel: two agents writing the same file, store, or crontab; anything touching
holdings, the identity registry, lineage stores, or the InstrumentRecord store; deploys.
Before dispatch: each agent declares its file set and store set; overlaps are serialized.
On report: every claim tagged [VERIFIED] (command run, output quoted), [CODE], or
[DOC-CLAIM]. On conflict: the [VERIFIED] claim wins; if both are verified, re-run both —
and check as-ofs before calling it a conflict at all. No agent marks its own work DONE; the
coordinator marks it against the proof.
When a finding contradicts this prompt, the finding wins. That has been the correct outcome
in every wave. Report it once and continue.
Standing traps
compile(), never ast.parse, for any "does this parse" question.
Check exit codes for the specific expected value; $? after a pipe is the pipe's.
A declaration is a claim about reality — check cron and systemd.
Follow symbols to the actual write call; filename greps have produced three wrong conclusions.
An aggregate that discards its members is a hypothesis, not a measurement.
A metric without an as-of cannot be compared, by anyone, including two of your own agents.
A test whose expected value comes from the artifact under test validates nothing.
Read tracebacks whole.
safe_text_edit for every edit; line-ending gate green before pushing.
prepare → promote → verify live independently; the deploy script reads its own worktree's HEAD.
Additive only on append-only stores; verify by byte snapshot.
Never mint a placeholder identity; never a ticker as a GUID.
Never auto-remediate store divergence.
A gate that edits source must verify its own edit still compiles.
Never route around a permission denial. Stop and report.
Not accepted as completion
A package DONE on CI alone. A number quoted rather than regenerated. A proof shown by hand where
the claim is that it happens on schedule. A metric whose floor makes failure unreportable. A gate
that has never executed. A check whose name promises more than its code verifies. Five proofs
observed on the first attempt — if that happens, assume something is wrong and find it first.
Still the operator's
Collapsing the two holdings copies into one. Changing ranked surface order beyond E6's labeled
addition. Any new production cron entry — propose, do not install. Raising MBI_BEHAVIOR above
0, in any form, for any reason.
