# CLAUDE.md — standing rules for this repository

Read this before doing anything. Every rule here was written after a specific
failure, and most were written after the same class of failure happened more
than once.

`./AI_WORK_POLICY.md` remains the canonical engineering, Git, CI-cost,
deployment-boundary and remote-synchronization policy, and `AGENTS.md` remains
the runtime reference. This file is not a second policy — it is the operating
technique those two assume. **If there is a conflict, use the safer or more
restrictive instruction.**

## Authority — non-negotiable

    MBI_BEHAVIOR  = 0
    MBI_COGNITION = 1

No order, no size, no weight, no stop, no broker write. Ever, for any reason,
under any framing. `BehaviorWriteRefused` raises on `recommended_delta_usd`,
`size_usd`, `shares`, `qty`, `order`, `stop`, `limit`, `target_weight_pct`,
`trade`, `execution` — refused outright, never silently filtered, **because a
dropped size field looks honoured**.

`MBI_COGNITION = 1` means memory may change `next_research_question`,
`next_eligible_at`, `notify_priority` and `cc_narrative`. A cognition write that
moves none of those raises `CognitionNoOp` and is a failed persist. Silence is
how a memory system convinces itself it is learning.

## The governing principle

**A component reporting success is not evidence that it did anything.**

The recurring defect in this codebase is a contract built and a caller never
wired, or a surface reporting on a set it never read. Each artifact passes its
own tests, so nothing reports a problem. Instances found so far:

- a gate affirming a declaration it read out of a `SyntaxError`
- a test asserting literals from the file it validates
- a liveness monitor that was never scheduled
- a repricer writing a tree nobody serves
- a root map whose green classes were unreachable
- a policy comment that outlived its policy

**Corollary:** a green obtained by the wrong artifact is worse than a red,
because a red gets investigated.

## Evidence vocabulary — required on every claim

| tag | means |
|---|---|
| `[VERIFIED]` | a command was run and its output is quoted. Nothing else qualifies. |
| `[CODE]` | source was read; describes what the code does, not that it ran. |
| `[DOC-CLAIM]` | a document asserts it and it has not been confirmed. |

An untagged claim is a defect. A `[DOC-CLAIM]` promoted to `[VERIFIED]` without
a command is a serious one.

**Never state a measured value as a premise.** State the question and the
threshold; measure the value. Values here have moved between phases of the same
session, and briefs that embedded numbers have been refuted every single time.

## Metric rules

- Every metric carries an `as_of` and the root it read. **Two measurements of a
  live-appending store are not in conflict unless they share an as-of.** Four
  measurements of lineage completion once looked like a four-way disagreement
  and were all correct.
- **An aggregate that discards its members is a hypothesis, not a measurement.**
  Recompute from source before reasoning from it. One "structural" 35,928-event
  skip turned out to be a 149-name registry gap under 58,682 rows of extraction
  noise.
- **A test whose expected value comes from the artifact under test validates
  nothing.** Assert against a freshly regenerated value or delete the test.
  Never update the literals.
- **A metric whose floor makes failure unreportable should be struck, not
  relabeled.** An unweighted mean over three families where two are tiny and
  perfect cannot drop below 66.67%.

Verdict vocabulary when auditing published numbers: `VERIFIED_FRESH` · `STALE` ·
`UNRUNNABLE` · `NO_PRODUCER` · `FRESH_SCRIPT_STALE_SOURCE` (runnable script,
stale upstream).

## Standing traps — each one has cost real time

- **`compile()`, never `ast.parse`**, for any "does this file parse" question.
  `ast.parse` does not enforce `__future__` placement and tolerates a BOM; it
  passes files Python refuses to import.
- **Check exit codes for the specific expected value.** Exit 2 for a missing
  script reads identically to a pass. `$?` after a pipe is the pipe's status.
- **A scheduler declaration is a claim about reality** — check cron *and*
  systemd. A job with a commented crontab line may run under an active timer.
- **Follow symbols to the actual write call.** Grepping for a filename has
  produced three wrong conclusions; the write often sits in a one-line helper
  imported locally inside a `try:`.
- **Read tracebacks whole.** A chained exception hides its real cause in the
  part that gets truncated.
- **Line endings:** route every edit through `safe_text_edit`. It detects the
  existing style and refuses to convert. Conditional conversion has produced
  `\r\r\n` across an entire file, which Python still parses and tests still
  pass. If a diff is implausibly large, check encoding before reading it.
- **`sys.path` contamination:** measurements run from a worktree read a `data/`
  that isn't there. Use the documented live-measurement path.
- **A gate that edits source must verify its own edit still compiles.**
- **File `atime` is not evidence of a live consumer.** This filesystem is
  mounted `relatime`, so a read may not update `atime` at all. An investigation
  nearly concluded "nothing reads the spine" from atime alone; the conclusion
  happened to be right and the method was worthless. Prove a consumer by finding
  the call site and observing it run, never by timestamp.
- **Check whether a store's default path is absolute before reasoning about
  roots.** `cio_lineage_health.DEFAULT_PATH` points at
  `~/trade-ai-releases/persistent-state/...`, outside every checkout, so
  `TRADEAI_ROOT` can neither fix nor break it — four runs across both cwds with
  and without the variable returned identical output. Two agents drew opposite
  conclusions about that collector's root sensitivity; both were reasoning about
  a path the variable never touched.
- **Never mint a placeholder identity.** `None` for unresolvable. Never a ticker
  as a GUID. A shared "unknown" id joins every unresolved event to every other.
- **Never auto-remediate store divergence.** Report both paths, both hashes,
  both timestamps, both reconciliation verdicts. Two candidate truths means a
  machine picking one can destroy the other.
- **Never route around a permission denial. Stop and report.** No alternate
  remote, no direct-to-main push, no API call substituting for a blocked CLI, no
  merge without a PR. Each produces a "landed" claim with no review artifact —
  the exact failure class this work exists to find.

## Deploy protocol

- `prepare` → `promote` → **verify the live directory independently**.
  `PROMOTE OK` has re-pinned a stale release.
- The deploy script reads its own worktree's HEAD — **detach onto the merged
  commit first.**
- **Prove behaviour from the served release**, not just that files copied.
- Additive only on append-only stores; verify by byte snapshot (rows added, ids
  removed = 0, confirmed states downgraded = 0).
- `logs/` and state directories are symlinks to persistent state. A release that
  starts them empty orphans evidence and makes the deploy silently non-additive.
- A red CI run may be a quota block rather than a test failure — check before
  diagnosing.
- One PR per finding, with the validation output quoted in the body.

## Multi-agent protocol

- Parallel is for independent investigation, disjoint fixes with declared file
  sets, and tests for separate modules.
- **Never parallel:** two agents writing the same file, store or crontab;
  anything touching holdings, the identity registry, lineage stores or the
  InstrumentRecord store; deploys.
- Before dispatch, each agent declares its file set and store set. Overlaps are
  serialized.
- On conflict the `[VERIFIED]` claim wins. If both are verified, **check as-ofs
  before calling it a conflict at all**, then re-run both.
- **No agent marks its own work DONE.** The coordinator marks it, against the
  proof.
- **When a finding contradicts the brief, the finding wins.** That has been the
  correct outcome in every wave. Report it once and continue.

## The maturity bar — five proofs, not a percentage

A package is complete when its proof is observed **at runtime, from the served
release, with the command quoted**. No percentage, test suite or CI pass
substitutes.

| # | proof | |
|---|---|---|
| M1 | Research | The system raised a research request itself, it completed, and it changed a named field on a named record. Show the diff. |
| M2 | Advice | A critique verdict changed `next_research_question` rather than being logged beside it. Show both questions. |
| M3 | Feedback | An operator reply landed on a record and changed the next wake's behaviour. Show the wake's decision with and without the turn. |
| M4 | Consistency | Every operator-facing number traces to one regenerable producer, and no two surfaces state the same quantity differently without a labeled scope. |
| M5 | Persistence | A scheduled wake loads the record before acting, and a disposition made days earlier is still honoured today with nobody replaying it. |

`NOT OBSERVED` is an acceptable and expected result. **A truthful three-of-five
is worth more than a claimed five**, and a claimed five that a later session
refutes is the worst outcome available. If all five come back observed on the
first attempt, assume something is wrong and find it before reporting.

## Not accepted as completion

- A package DONE on CI alone.
- A number quoted from a document rather than regenerated.
- A proof demonstrated by hand where the claim is that it happens on schedule.
- A metric whose floor makes failure unreportable.
- A gate that has never executed.
- A check whose name promises more than its code verifies.
- A producer reconstructed to justify an already-published number.

## Operator-only decisions

Do not resolve these; propose and stop.

- Collapsing the two holdings copies into one file.
- Changing what is ranked onto an operator surface.
- Any new production cron or systemd entry — propose, do not install.
- Raising `MBI_BEHAVIOR` above 0, in any form.
- Re-enabling the retired overnight LLM window.
- Merging divergent copies of any authoritative store.

The deferred list should **shrink** each wave. The escalate-never-resolve rule
exists for cases where a machine choosing between two candidate truths can
destroy one. It does not cover labeling, error strings, routing defaults whose
conservative option is reversible, or additive monitoring. Do not defer those.
**If the deferred list grows during a wave, that is a finding about how the wave
was run.**

## Working style

Direct, evidence-based, and intolerant of work parked behind questions already
answered. Correct your own prior claims out loud when measurement refutes them —
that has produced the most valuable findings in this repository. Keep the
failures in the write-up, not just the final state.
