<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 12 — the operator's maturity bar

**Status:** recovered verbatim
**Source:** session transcript, operator message 029

---

Claude Code Execution Prompt — WAVE 12: bring the agent to the operator's maturity bar
Repo: trade-ai-v12-rebuild · hub /home/john/trade-ai-v12-rebuild/
Authority: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · MBI_COGNITION=1. None of this changes
execution authority. No order, no size, no broker write, at any point, for any reason.
0. What "mature" means here — five proofs, not a percentage
The operator's definition: an autonomous agent that does its own research, gets advice, takes
feedback, and keeps everything consistent and persistent.
That translates into five observable end-to-end events. A package is not complete until its
proof has been observed at runtime, from the served release, with the command quoted. No
percentage, no test suite, and no CI pass substitutes for one of these.
#
Proof
What must be observed
M1 · Research
The system raised a research request itself, it completed, and it changed a named field on a named record. Show the before/after diff of that field.

M2 · Advice
A critique verdict changed the next research question on a record, rather than being logged beside it. Show both questions.

M3 · Feedback
An operator reply landed on a record and changed the next wake's behaviour — the wake skips, defers, or reframes because of it. Show the wake's decision with and without the turn.

M4 · Consistency
Every number on an operator surface traces to one regenerable producer, and no two surfaces state the same quantity differently without a labeled scope.

M5 · Persistence
A scheduled wake loads the record before acting, and a disposition made days earlier is still honoured today without anyone replaying it.

M1 has never happened. M2 happened once, by hand. M3 works as a mechanism with no scheduled
consumer. M4 is currently false. M5 is the whole point of the spine and is unproven under cron.
Report the five as OBSERVED / NOT OBSERVED at the end. NOT OBSERVED is an acceptable
and expected result for some of them. A truthful three-of-five is worth more than a claimed
five, and a claimed five that a later session refutes is the worst outcome available.
1. Rules for running multiple agents
Parallel agents are for independent investigation and non-overlapping fixes. They are
not for anything that shares mutable state.
Allowed in parallel
Read-only investigation of distinct subsystems.
Fixes touching disjoint file sets, declared up front.
Test authoring for separate modules.
Never in parallel
Two agents writing the same file, store, or crontab.
Anything touching holdings.json, the identity registry, lineage stores, or the InstrumentRecord store — one writer at a time, always.
Deploys. One deploy at a time, serially, verified before the next starts.
Anything where agent B's correctness depends on agent A's fix having landed.
Before dispatching a wave
Each agent declares its file set and its store set. If two overlap, they are serialized.
Each agent reports findings with tags — [VERIFIED] (a command was run and output is quoted), [CODE] (source read), [DOC-CLAIM] (a document says so).
The coordinator reconciles conflicting findings before any of them ships. When two agents disagree, the one holding a [VERIFIED] command output wins; if both do, re-run both.
No agent marks its own work DONE. The coordinator marks it, against the proof.
When an agent's finding contradicts this prompt, the finding wins. That has been the
correct outcome in every wave so far. Report it once and continue; do not stop to reconcile.
2. Standing traps — every one of these has cost real time already
compile(), never ast.parse, for any "does this file parse" question. ast.parse accepts files Python refuses to import.
Check exit codes for the specific expected value. Exit 2 for a missing script reads identically to a pass. $? after a pipe is the pipe's status.
A declaration is a claim about reality — check cron and systemd. A job with a commented crontab line may run under a timer.
Follow symbols to the actual write call. Filename greps have produced three wrong conclusions; the write often sits in a helper imported locally inside a try:.
An aggregate that discards its members is a hypothesis, not a measurement. Recompute from source before reasoning from it. This one turned a "structural" 35,928 into a 149-name cleanup.
Read tracebacks whole. Chained exceptions hide the cause in the truncated part.
safe_text_edit for every edit; line-ending gate green before pushing.
prepare → promote → verify the live directory independently. PROMOTE OK has re-pinned a stale release. The deploy script reads its own worktree's HEAD — detach onto the merged commit first.
Additive only on append-only stores; verify by byte snapshot (rows added, ids removed = 0, confirmed states downgraded = 0).
Never mint a placeholder identity. None for unresolvable. Never a ticker as a GUID.
Never auto-remediate store divergence. Report both sides with hashes and timestamps.
A gate that edits source must verify its own edit still compiles.
WAVE A — Finish the truth restoration (parallel, read-only, then one PR each)
Nothing downstream is trustworthy until this closes. Four agents, disjoint scopes.
A1 · Complete the V-sweep. V1 through V5 as previously specified: compile() in every
gate, mutation-tested against the declaration-placement failure; regenerate every published
metric into a verdict table (VERIFIED_FRESH / STALE / UNRUNNABLE / NO_PRODUCER /
FRESH_SCRIPT_STALE_SOURCE); re-verify the DONE column; strike the unweighted mean rather
than assigning it a verdict.
A2 · Every gate's last real execution. For each CI gate, cron job, and systemd timer
installed in the last two weeks: when did it last actually run, what durable evidence did it
leave, and does its most recent run reflect current main? A gate that has never run is
indistinguishable from one that passed.
A3 · Discarded-member aggregates. Find every other pre-computed tally that keeps counts
and discards the rows behind them. Each is a number nobody can audit. List them; recompute the
top three from source.
A4 · Surface inventory for M4. Every number on every operator surface, with its producing
function and whether two surfaces state the same quantity differently. This feeds Wave E.
Coordinator gate: Wave B does not start until A1's verdict table exists.
WAVE B — The catalyst pipeline (strictly serial, in this order)
Order is load-bearing. Registration before filtering mints junk into the registry permanently.
B1 · Filter directive slugs at ingestion. Research-directive IDs are not securities and
must never reach identity resolution.
B2 · Constrain the extractor to a known ticker universe. Any 1–5 uppercase run is not a
symbol. SSDI, IRMAA, TO, NEED, FIND are English and acronyms scraped from prose.
B3 · Register the ~149 real names, deliberately. One at a time, each verified against the
real universe. This is the only genuine registry gap. Do not widen a rule to catch them.
B4 · Re-measure. Catalyst family completion, recomputed from source, not from a tally.
State the number honestly whatever it is.
B5 · Refresh the stale catalyst source. The graph and momentum files are days old. Find
the writer, establish whether it is scheduled, and if the answer is the served-copy split
again, fix it at the resolution layer rather than the cron's working directory.
Keep the guard as it is. Refusing to bind an unrecognized symbol is correct behaviour — the
module's docstring already says an edge to the wrong company is worse than a missing edge.
WAVE C — Close the loop (partly parallel)
C1 · A scheduled wake loads the record before acting. (This is M5.) Wire load-by-subject
into the scheduled wake path ahead of everything else. Prove a days-old disposition is honoured
under cron with nobody replaying it. Enumerate every producer and state which ones write the
record versus side-storing.
C2 · The frozen notification arc. One arc has grown by dozens while the other has not moved
at all. Establish whether it stopped running, runs and writes nothing, or writes under a key
the predicate misses. Report when it stopped and what changed. This is the arc the operator's
notifications come from.
C3 · Checkpoint → outcome → lesson, under schedule. The resolution and lesson lanes recur
with little to consume. Establish whether horizons are legitimately future-dated (an acceptable
answer) or the due query is wrong. Emit nothing for workflows that did not complete — a
manufactured lesson permanently poisons the store.
C1 and C2 are parallel. C3 waits on both.
WAVE D — Judgment (serial; the decisions below have defaults, use them)
Today the pipeline generates none. One lane once did and was retired. This wave restores it
under governance and wires critique into cognition.
D1 · The retired overnight window — restore under these defaults.
Three things must be established before re-enabling, and the defaults are specified so this
does not park again:
Why it was retired. If the reason was output quality or supersession, stop and report.
Cost alone is now governed by the enforced cap.
The backlog: discard, do not drain. Jobs raised months ago were raised against positions,
prices, and theses that have since moved. Re-raise from current state. Draining produces
well-formed, confident, wrong analysis and feeds it to the operator's phone.
Cap arithmetic first. Per-job cost against the enforced daily cap, with the number
written down. If the arithmetic says the lane cannot run meaningfully inside the cap, that is
the finding — report it rather than quietly exceeding or silently starving.
D2 · Critique changes the question. (This is M2.) A critique verdict must move
next_research_question, not sit beside it. Cognition already raises CognitionNoOp when a
write moves nothing — use it. Prove it on a live record, scheduled, not by hand.
D3 · Research reaches the record. (This is M1.) A completed research result must attach to
the plan it was raised for, and change a named field. The result id is currently not linked to
any plan, which is why no round trip has closed.
D4 · The research→action policy — default specified. The gate encodes
POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION, which is why a positive, critique-validated
delta changes nothing. Default: a research-backed positive delta may raise notify_priority,
change cc_narrative, and set next_research_question. It may never touch size, weight,
order, or any behaviour field — BehaviorWriteRefused continues to raise on all of them.
That is MBI_COGNITION=1 operating within its existing definition, and MBI_BEHAVIOR stays 0.
Implement it. If implementation reveals a case this default did not anticipate, stop and report.
D5 · The cash letter becomes real prose. It is currently a deterministic migration string
inside a correct structural shell. Keep every guard: closed option-id set, standalone_sell
always false, and the refusal of any "deploy $N into TICKER" construction. The shell is right;
only the text should change.
WAVE E — Delivery and consistency (parallel after D)
E1 · Provenance at the point of display. (This is M4.) Every operator-facing field carries
its class — deterministic, template, model-assisted, agent-originated, snapshot. The
unconditional constant currently serving as cash guidance either becomes conditional on real
state or stops being rendered as guidance. Fix the footer that asserts a model provenance for a
brief no model produced.
E2 · Surface scope labels. The two re-entry books answer different questions and are both
correct. Each states the question it answers and the population it scores. Do not merge them,
do not introduce precedence.
E3 · What the operator actually asked for months ago. Earnings data is ingested at scale
and the brief's earnings field ships empty. Ship what the data supports — dates and events are
honest; implied analysis the system did not perform is not.
E4 · New names reach a surface. A lane supplies names outside the former-holdings set and
they are ranked out before display. Establish the mechanism, then surface them behind a
labeled section so the operator can see they are unheld candidates rather than positions.
E5 · Alert routing. Critical findings on money surfaces go immediate; everything else
digest; no deploy gate. Dedupe applies — a finding that has emitted every cycle for days must
not produce days of identical messages.
WAVE F — The maturity report
One document, written for the operator, no hedging:
The five proofs, each OBSERVED with its command and output, or NOT OBSERVED with the
specific blocker.
What runs at runtime today, each with the command that demonstrates it.
What is built and unwired.
What is claimed and unverifiable.
The count of agent-originated fields reaching any operator surface.
Every decision still genuinely the operator's — and this list must be shorter than the
one this prompt started with. If it has grown, that is a finding about how the wave was run.
Then re-run the full acceptance and quote it.
What will not be accepted as completion
A package marked DONE on CI alone.
A number quoted from a document rather than regenerated.
A proof demonstrated by hand where the claim is that it happens on schedule.
A metric whose floor makes failure unreportable.
A gate that has never executed.
A green check whose name promises more than its code verifies.
Five proofs observed on the first attempt. If that happens, assume something is wrong and
find it before reporting.
Still the operator's — do not resolve these
Collapsing the two holdings copies into one. Stage B monitoring only.
Changing the operator's ranked surface order beyond E4's labeled addition.
Any new production cron entry — propose, do not install.
Raising MBI_BEHAVIOR above 0, in any form, for any reason.
