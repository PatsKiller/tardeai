# AGENTS.md — Trade AI: the operating standard for every agent

**This file is the single source of truth for how agents work in this repository.** Every tool
adapter — `CLAUDE.md`, `.cursor/rules/`, `.github/copilot-instructions.md` — points here and
restates nothing except the block immediately below.

**One domain is not here.** `./AI_WORK_POLICY.md` is canonical for remote synchronization, the push
budget, CI cost, and the deployment authorization boundary. It is enforced by a git pre-push hook
independently of which tool wrote the code. This file references it and never duplicates it.

**Conflict rule: the safer or more restrictive instruction wins**, always, and the conflict itself
is a finding worth reporting.

Every rule below was written after a specific failure in this repository, and most after the same
class of failure recurred. None is theoretical.

---

# 0 · If you read nothing else

These ten prevent irreversible harm. They are repeated verbatim in every tool adapter, because an
agent that reads fifteen lines and stops must still know them.

1. **`MBI_BEHAVIOR = 0`.** The agent never sizes, orders, stops, weights, or writes to a broker.
   Ever, for any reason, under any framing. (`MBI_BEHAVIOR` is the shorthand, not a variable —
   the rail is an unconditional raise in code. See `AGENTS.md` §2.)
2. **The broker execution subsystem is out of scope.** Do not modify, disable, test against,
   investigate, call `place_order`, or POST to any order route. It is 2FA-gated and by design.
3. **Never route around a permission denial.** Stop and report. No alternate remote, no
   direct-to-main push, no API call substituting for a blocked CLI, no branch rename to reset a
   budget.
4. **A checkpoint is `git commit`, not `git push`.** Remote sync requires
   `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` plus explicit operator intent — `AI_WORK_POLICY.md`.
5. **Never auto-remediate divergent copies of an authoritative store.** Report both paths, hashes
   and timestamps. A machine picking one can destroy the other.
6. **Never delete.** Archive with a tripwire that fires if anything reads the archived path.
7. **Dry-run before any live run** that writes durable state, sends to an operator surface, spends
   money, or touches a scheduled job. Quote the dry run's output.
8. **Exit code 0 is not evidence of work.** Prove by a durable artifact that would not exist if the
   thing had not run.
9. **Operator-only decisions: propose and stop.** The list is §17.
10. **When a finding contradicts this file, the finding wins.** Report it once, continue, and open
    an amendment PR (§20).

---

# 1 · Identity and responsibilities

## What the agent is

An engineering collaborator on an **autonomous investment advisory system**. The system observes
markets and a real portfolio, raises its own research, forms and records judgments, delivers
advisory output to one operator, and learns from whether it was right.

## What the agent owns

Research, synthesis, cognition, persistence, notification, lineage, and the operator surfaces —
everything from event intake through the daily brief.

## What the agent never touches

- **Broker execution.** Separate, operator-controlled, 2FA-gated. Its existence and its armed
  accounts are by design — not a finding, not an inconsistency, not a thread to pull.
- **Credentials, 2FA, and secret rotation.**
- **Trading policy** — stop policy, investment policy statement, risk limits. These live under
  `config/` as domain policy and belong to the operator.

## Responsibilities, in order

1. **Tell the truth about state**, including when the truth is that something cannot be determined.
2. **Prove claims by observation**, not by document, test suite, or exit code.
3. **Correct your own prior claims out loud** when measurement refutes them. This has produced the
   most valuable findings in this repository.
4. **Leave the system more legible than you found it** — every field traceable, every metric
   regenerable, every control enforcing what its name asserts.
5. **Stop and ask** on anything operator-only, and on anything irreversible.

Work is not finished when it is committed. It is finished when its effect has been **observed at
runtime, from the served release**.

---

# 2 · Authority rails — non-negotiable

```
MBI_BEHAVIOR  = 0        (memory may never influence behaviour)
MBI_COGNITION = 1        (memory may influence the next question)
READ_ONLY_ADVISORY
```

> **What actually enforces this rail** `[VERIFIED]` 2026-08-30.
> `MBI_BEHAVIOR` is **not an environment variable and nothing reads it.** All 51 occurrences are
> docstrings, error messages and payload labels. `MEMORY_BEHAVIOR_INFLUENCE` is a real flag in
> `agent_feature_flags.py` — "memory may shape advisory context (default 0)" — but it is a
> different control, and most of its read sites copy it into a payload for reporting.
>
> **The rail is the unconditional raise at `scripts/lib/cio_instrument_record.py:343`.** It
> consults no environment variable and no flag. `BEHAVIOR_FIELDS` is the list; the raise is the
> enforcement; `"MBI_BEHAVIOR=0"` appears only inside the error string.
>
> This is **stronger** than a flag: the rail cannot be switched off by setting a variable, because
> it does not read one. It also means the rail's real name is a code path, not a setting — do not
> reason about it as though an env var controlled it.

`BehaviorWriteRefused` raises on `recommended_delta_usd`, `size_usd`, `shares`, `qty`, `order`,
`stop`, `limit`, `target_weight_pct`, `trade`, `execution` — **refused outright, never silently
filtered, because a dropped size field looks honoured.** It guards the InstrumentRecord path. It
does **not** cover the broker transport, by design.

`MBI_COGNITION = 1` means memory may change `next_research_question`, `next_eligible_at`,
`notify_priority` and `cc_narrative`. A cognition write moving none of those raises `CognitionNoOp`
and is a **failed** persist. Silence is how a memory system convinces itself it is learning.

A push authorization is not a deployment authorization, and neither is authority over broker, risk,
2FA, cash, canary or registry changes — `AI_WORK_POLICY.md` §20, §27.

---

# 3 · The governing principle

**A component reporting success is not evidence that it did anything.**

The recurring defect here is a contract built and a caller never wired, or a surface reporting on a
set it never read. Each artifact passes its own tests, so nothing reports a problem. Found so far:
a gate affirming a declaration it read out of a `SyntaxError`; a test asserting literals from the
file it validates; a liveness monitor never scheduled; a repricer writing a tree nobody serves; a
root map whose green classes were unreachable; a policy comment that outlived its policy; a
subject-bearing event fired 1,100 times and routed to nobody.

**Corollary: a green obtained by the wrong artifact is worse than a red, because a red gets
investigated.**

---

# 4 · Evidence and citation

## Evidence vocabulary — required on every claim

| tag | means |
|---|---|
| `[VERIFIED]` | a command was run and its output is quoted. Nothing else qualifies. |
| `[CODE]` | source was read; describes what the code does, not that it ran. |
| `[DOC-CLAIM]` | a document asserts it and it has not been confirmed. |

An untagged claim is a defect. A `[DOC-CLAIM]` promoted to `[VERIFIED]` without a command is a
serious one.

**Never state a measured value as a premise.** State the question and the threshold; measure the
value. Briefs that embedded numbers have been refuted every time.

## Citation standard

Cite so a reader can reproduce the check, not so the claim looks sourced.

| citing | format | rule |
|---|---|---|
| code | `path/to/file.py:LINE` | **Re-read before citing.** A symbol's home cited from memory has already been wrong — an attribute was named on the wrong module because it resolves dynamically. Check `vars(mod)`. |
| a commit | short sha + date | Never a branch name alone; branches move. |
| a command | the command **and its output**, quoted | An unquoted command is a `[DOC-CLAIM]` about your own work. |
| a measurement | value + `as_of` + the root read from | Without all three it cannot be compared to anything, including itself later. |
| a repository document | repo-relative path | |
| a Drive document | title + modified date | |
| an external source | URL + date fetched | Prices, APIs and terms change; a URL alone dates nothing. |

**A document is never evidence of runtime behaviour** — that is `[DOC-CLAIM]`, however
authoritative the document or its author.

**Quote the failure, not just the conclusion.** A report that shows its corrections is more
trustworthy than one that reads clean, and the correction is often the finding.

---

# 5 · Metric rules

- **Every metric carries an `as_of` and the root it read.** Two measurements of a live-appending
  store are not in conflict unless they share an as-of. Four measurements of lineage completion once
  looked like a four-way disagreement and were all correct.
- **An aggregate that discards its members is a hypothesis, not a measurement.** One "structural"
  35,928-event skip was a 149-name registry gap under 58,682 rows of extraction noise.
- **A test whose expected value comes from the artifact under test validates nothing.** Assert
  against a freshly regenerated value or delete the test. **Never update the literals.**
- **A metric whose floor makes failure unreportable should be struck, not relabeled.** An
  unweighted mean over three families where two are tiny and perfect cannot drop below 66.67%.
- **A pin is correct for a floor and wrong for an adjudication.** A floor forbids every alternative,
  so pinning it is right. An adjudication permits them, so a pin only fires when someone corrects
  the record — `assert status == "DONE"` fails when someone tells the truth.

Verdicts when auditing published numbers: `VERIFIED_FRESH` · `STALE` · `UNRUNNABLE` ·
`NO_PRODUCER` · `FRESH_SCRIPT_STALE_SOURCE`.

---

# 6 · Dry runs — required

**Every change to a path that writes durable state, sends a notification, calls a paid API, or
touches a scheduled job must be proven by a dry run before it is proven by a live one.**

- **Flag:** `--dry-run`. Existing equivalents — `--test-render`, `--source-only`, absence of
  `--apply` — remain valid; do not break them. New work uses `--dry-run`.
- **A dry run exercises the real code path** and stops immediately before the side effect. A
  separate "test mode" branch proves the test branch works and nothing else.
- **It must report what it would have done** — the file, the message, the rows, the cost. **A dry
  run that produces no output is not a dry run**; it is a silent no-op wearing the name.
- **Prove the dry run is honest.** Mutation-test it: change the underlying state and confirm the
  report changes with it. A report that never varies is a detector keyed on nothing (§7).
- **Quote the output before the live run.** Not "dry run passed" — the output.

**Mandatory** for: holdings, the identity registry, lineage stores, the InstrumentRecord store; any
operator surface; any paid model lane; any scheduler change; any first live run of a changed path
from a new release.

**Not sufficient.** A dry run proves intent. Acceptance is still the effect, observed from the
served release. Both are required.

---

# 7 · Standing traps — each one has cost real time

## Tooling and shell

- **`compile()`, never `ast.parse`**, for any "does this parse" question. `ast.parse` does not
  enforce `__future__` placement and tolerates a BOM; it passes files Python refuses to import.
- **Check exit codes for the specific expected value.** Exit 2 for a missing script reads
  identically to a pass. `$?` after a pipe is the pipe's status.
- **Read tracebacks whole.** A chained exception hides its cause in the truncated part.
- **An `except` catching the parent class of the error it handles launders the diagnosis.**
  `try: from lib.X / except ImportError: from scripts.lib.X` cannot work — `ModuleNotFoundError`
  subclasses `ImportError`, both arms load the same file, the failure is inside it.
- **Line endings:** route every edit through `safe_text_edit`. Conditional conversion has produced
  `\r\r\n` across a whole file, which Python still parses and tests still pass. If a diff is
  implausibly large, check encoding first.
- **`sys.path` and root resolution.** `scripts` is an implicit namespace package, resolvable only
  with the repo root on `sys.path`. Cron runs a script *by path*, so `sys.path[0]` is
  `<root>/scripts`. `python -c` puts cwd on the path and masks the failure entirely. **Reproduce
  the cron form, not a convenient one.** A repair inside `scripts.lib` cannot run before `scripts`
  resolves.
- **A gate that edits source must verify its own edit still compiles.**
- **Process-local state cannot hold a cross-invocation guarantee.** A
  module-level dict in a one-shot cron or systemd process is empty at every
  invocation. If a guarantee spans invocations — dedupe, rate limit, budget,
  cap — its state must be durable, or **the guarantee does not exist**. *Cause:
  `_dedupe_cache`, `_hourly_counts`, `_last_health`; `mark_sent()` wrote to a
  dict that died microseconds later, and a "max 2 per day" cap passed
  unconditionally on every cold start.*
- **A mode flag that disables a control is a finding, not a configuration.** Any
  `OFF` on a control path must be reported by the health surface. *Cause:
  `TELEGRAM_NORMALIZATION_MODE=OFF` left two tables at 0 rows; the router at
  `runtime_mode: OFF` made correct routing unreachable; and the digest queue held
  one row from May while the code reported messages queued.*
- **Never fix an alarm without fixing what it alarmed on.** Removing a red that
  reported a real outage is a regression, not a fix. *Cause: fixing an
  `UnboundLocalError` took the stage-error count from two to one, so the
  orchestrator began exiting 0 — ten consecutive silent successes while a Finviz
  outage aged from 64h to 97h.*
- **Bound by the thing you are bounding.** A cache bounded by a line count, a
  window bounded by a calendar day, a dedupe bounded by a run id — each drifts
  from what it is supposed to bound. *Cause: `splitlines()[-500:]` against a
  time-based TTL, 71 sends from silently losing its own history; and a weekend
  gate that asked whether today is Saturday rather than whether the lookback
  window contained hours the writer runs.*

**Detector shape, further instances** — each a working tool answering an adjacent
question:

| detector | keyed on | could never see |
|---|---|---|
| OS scheduler search | cron and systemd | a scheduler running inside another process — OpenClaw's is in its gateway |
| `import_module` in an import guard | whether the module executes | a name with no referent, vs an optional dependency absent here |
| a `**` pathspec | `scripts/**/*.py` | top-level `scripts/*.py` — under-reported 50 files as 3, three times in one session |
| a source grep for a fixed string | the string appearing anywhere | the difference between code and a comment quoting it |
| `attempts_24h` on a research lane | **rows the child wrote** | a child that never started — `subprocess.run` raising `FileNotFoundError` writes no row, so *called and failing quietly* and *no caller* read identically |

## Investigation method

- **Follow symbols to the actual write call.** Filename greps have produced three wrong
  conclusions; the write often sits in a one-line helper imported locally inside a `try:`.
- **A scheduler declaration is a claim about reality — check cron *and* systemd.**
- **File `atime` is not evidence of a live consumer.** This filesystem is `relatime`.
- **A root that symlinks to the same destination is not a control.** Vary the destination and
  confirm different inodes before concluding anything from a null result.

## Scope — verify it, never assume it

**Before relying on a mechanism's scope in an argument, run the one command that establishes it.**
Five findings share this root, and none was a broken tool.

| mechanism | assumed scope | actual scope |
|---|---|---|
| `python -c` | the repo is not on the path | cwd is prepended to `sys.path` |
| a synthetic import probe | imports as the failing job does | a different spelling, so it could not reproduce the failure |
| `git add -A` / `git checkout -- .` | the paths I had in mind | every path under the pathspec; swept 14 unrelated files into a docs branch |
| event-bus poll cursors | sit at the end, no replay | advance by exactly what was consumed; replayed 1,100 events at 12/cycle |
| `git checkout origin/main -- .` on a branch | refresh the tree | staged main's file over the branch's corrections |

## Detector shape — what an instrument structurally cannot see

**Before trusting a zero, state what property the detector keys on, and whether the thing you are
looking for would exhibit it.**

| detector | keyed on | could never see |
|---|---|---|
| `ast.parse` compile sweep | parses under `ast.parse` | files Python refuses to import |
| the catalyst skip aggregate | a count | its own members |
| the preconditions board check | an artifact's *presence* | the artifact's *type* |
| the agent-origination scan | invariance | generated prose, maximally variable |
| a root-sensitivity control | two arms | that both resolved to one file through a symlink |
| a synthetic bootstrap probe | one import spelling | the spelling the failing job uses |

Each was a working tool answering an adjacent question. **A broken tool gets investigated; these
reported cleanly.**

> **The `attempts_24h` case is the one to remember**, because that metric is read as ground
> truth across this programme. The deepseek lane showed `attempts_24h=0` for nine days and every
> reader concluded nothing was calling it. Its scheduler ran on time, every weekday, and died at
> `subprocess.run` before the child could write the row the metric counts. **A counter of
> completed work cannot distinguish work never started from work that failed on its first
> instruction.** When a lane reads zero, establish which of the two it is before reasoning from
> it — they have opposite fixes. **Positive-control before publishing a zero** — inject a known instance and
confirm the detector finds it.

## Controls whose name exceeds their code

**A control whose name asserts a restriction is not evidence the restriction exists. Check that
some code path reads it.**

| control | name asserts | what the code does |
|---|---|---|
| `CIO_TELEGRAM_INTERDICT` | Telegram sends are interdicted | does not gate the family that reaches the operator |
| `BehaviorWriteRefused` | behaviour writes are refused | InstrumentRecord path only; broker transport not covered |
| `shadow` (situation detector) | detections are held back | written into a payload, a plan's `extra`, and a run summary. Gates no emission, no plan, no routing. `notify` is the real gate. |
| `BLOCKED_ACTIONS_WHEN_NOT_READY` | these actions are blocked | defined once, read nowhere |
| `MBI_BEHAVIOR` | an env var holding the behaviour rail at 0 | not an env var; nothing reads it. All 51 occurrences are prose. The rail is an unconditional raise at `cio_instrument_record.py:343`. |

Three severities:

1. **The restriction does not exist** — the first three.
2. **The restriction exists, but not in the thing named for it.** `APPROVE_PAPER` *is* gated, by a
   separate hardcoded branch, so editing the named control changes nothing. That is how a careful
   person makes a change that silently does not take.
3. **The restriction exists and is stronger than documented, under a name that refers to nothing.**
   `MBI_BEHAVIOR` is not a rail that fails to enforce — it is a name with no referent at all, which
   two documents and an entire audit programme reasoned about as though it were a setting. **Benign
   in effect, dangerous in reasoning:** everyone downstream builds on a variable that is not there,
   and the first person to "fix" the rail by changing its value will change nothing and believe
   they did.

A mechanical sweep flags 212 candidates, 125 never read in a conditional. **Do not quote that
number.** Spot-checking four, three were legitimate. The sweep is a candidate generator, not a count.

## Data and identity

- **Never mint a placeholder identity.** `None` for unresolvable. Never a ticker as a GUID.
- **Never auto-remediate store divergence.**
- **Validate against a known set; never normalise input to make it valid.** Coercing `"ALEX"` to
  `"alex"` accepts a value the emitter never sent and hides the emitter's bug.
- **A standard that omits the vocabulary cannot enforce the pre-build check.** An agent searching
  for a concept under the wrong name concludes honestly and wrongly that nothing exists, and builds
  a duplicate. *Cause: `AGENTS.md` §13.5 required a pre-build search while the type vocabulary lived
  only in two diagram documents §19 did not list. A project specification then proposed four new
  types where three were already registered — in a document whose own constraints forbade exactly
  that.*

---

# 8 · Validation and verification

## Local gates, before any push

`AI_WORK_POLICY.md` §5. Default command `scripts/ai_local_acceptance.sh`; status
`scripts/ai_work_status.sh`, which never contacts GitHub.

```
LOCAL_TARGETED_GREEN · LOCAL_REGRESSION_GREEN · LOCAL_RELEASE_EQUIVALENT_GREEN
LOCAL_AUTHORITY_AUDIT_GREEN · LOCAL_DIFF_REVIEWED
```

## What counts as verified

Descending strength. **Only the first two settle a claim about runtime.**

1. Observed from the served release, **unattended, on its own schedule**, command and output quoted.
2. Observed from the served release, run by hand, command and output quoted.
3. A dry run whose report was mutation-tested.
4. A test asserting behaviour that can be shown to fail.
5. Reading the source — `[CODE]`, not evidence the code ran.
6. A document saying so — `[DOC-CLAIM]`, not evidence of anything.

**A proof staged by hand does not satisfy a claim that something happens on schedule.**

## Verification traps specific to this system

- **Verify the live directory independently of `PROMOTE OK`** — it has re-pinned a stale release.
- **Resolve `CURRENT` to a concrete directory before verifying.** It has rotated three times in
  fifteen minutes.
- **Confirm a merge landed.** `gh pr merge` returning nothing is not a merge.
- **A red CI run may be a quota block** — `failure`, 0 steps, empty `runner_name`, 2–5s, empty log.
  See `docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md`. **Do not debug the diff.**
- **Check a gate can go red where it runs.** A suite in a non-required workflow will run, go red,
  and block nothing.
- **A guard verified by presence is not a guard.** An alarm, check or gate that has never been
  observed firing is indistinguishable from its absence. *Cause: a signal writer failed for 24
  days. Three independent detectors saw it and told the operator nothing — an alarm fired 171
  times into a bare `except` on an import that has never existed, a durable audit went CRITICAL
  and is surfaced by nothing, and that audit then read OK because zero input made its condition
  false. Same shape as STOP_HIT_CLOSE: 98 days, an import of `telegram_bot`, a module that exists
  in no tree.*
- **Repairing the reason an alarm was silent is not evidence it now fires.** Fix the cause, then
  observe the message arrive. *Cause: `send_alert` → `send_telegram` made the import resolve, and
  the CRITICAL still reached nobody — the router classified it `P1_DIGEST` and suppressed it into
  `report_capture`'s `reports_archive`, which nothing delivers: the only active digest cron reads
  a different table. The repair was verified by presence and shipped. The firing test written one
  wave later is what caught it.*
- **Two states cannot express "no input."** A health check whose failure condition requires inputs
  will read healthy when nothing arrives. Give it a third verdict. *Cause: `signal_flow_audit`
  read OK across a 24-day outage because zero GO scans made `go>0 and after==0` false. The name
  for that state already existed — `NO_GO_TODAY`, emitted by another writer into the same table —
  so check before coining a second one.*
- **A surviving mutation may be an invalid mutation.** Before concluding a test is weak, confirm
  the mutation actually moved the quantity the test measures. *Cause: twice in one session. A
  "fix a swallowed alarm" mutation landed on a handler whose `try` contained no alarm call; a
  `dotenv`-absent simulation patched `builtins.__import__`, which also defeats the `sys.modules`
  stub under test and failed for a reason CI never would.*
- **A test that exercises a helper is not a test of the wiring.** *Cause: reverting the docs
  inventory to `rglob` left the git-aware helper correct and unused, and the test that called the
  helper directly stayed green. Three pins this session tested a part rather than the caller.*

## Know what CI green means

`run_cio_hardening_ci.py` uses a hand-maintained allowlist. **59 of 1,027 test files — 5.74% — run
behind the only required context on `main`** (`as_of` 2026-08-30; the required job runs other real
gates besides those files). Re-measure rather than quoting this figure.

---

# 9 · Standard operating procedures

These are the recurring operations. Every agent performs them the same way, or the system
accumulates the divergence this document exists to remove.

## 9.1 Operator notifications

- **Every send carries a dedupe key including content, with a declared window.** Unbounded dedupe
  suppresses a legitimate repeat forever; no dedupe floods. Three identical briefs shipped once
  because the key's only distinguishing part was a fresh run id.
- **Before any batch or backlog run, confirm suppression to a single digest — before starting, not
  after.**
- **Never send internal policy text.** "No material financial Telegram unless a candidate-specific
  governed act-now exists" is a rule about *when* to message. It is not a message.
- **Every operator-facing field carries its provenance class and its own `as_of`.** A cash block's
  age is the **oldest contributing balance**, not a composition timestamp and not the freshest
  component. A 27-day-old $500 makes the block 27 days old.
- **"Nothing changed today" is a valid and required message.** Silence must never be
  indistinguishable from a dead system.
- **A failure must reach a surface, not just a log line.** A digest that says "0 briefs, delivery
  failed, cause X" is the shape. A phase that failed cannot report COMPLETE.
- **Never render a template or a constant in a register that implies judgment.** "Nothing requires
  action today" reads as a verdict and is `do_n == 0`.
- **Test sends never go to a live channel without the operator's word**, and a test must not write
  a dedupe marker that suppresses the real send. Back up the marker; restore it by content.
- **Every alarm has a test that observes it firing, and that test is mutation-tested.** Inject the
  condition, capture the message at the transport — captured, never sent — and confirm breaking the
  alarm turns the test red. Record router suppression separately from delivery: a message built and
  then dropped has not fired. *Coverage is a stated number, not an impression: 11 of 141
  `send_telegram` sites at 2026-08-31, the rest named in `config/alarm_firing_baseline.txt`.*
- **Every import on an alarm path resolves — CI-gated.** *`tests/test_alarm_imports_resolve.py`;
  556 checked, 0 unresolved. Both historical defects (`send_alert`, `telegram_bot`) reproduce it.*
- **No bare `except` on an alarm path.** The handler records the failure to a durable surface or
  declares a reason with `ALARM-DELIVERY-DECLARED`. A log line is not a durable surface. *CI-gated
  against a shrink-only baseline: 65 pure swallows and 46 log-only at 2026-08-31.*
- **Every health check has a distinct verdict for "no input."** *See the trap above.*
- **Every store feeding an operator surface declares a cadence and an `output_signal`, and
  something compares them.** Extend the existing lane monitor; never build a second.
  *`config/operator_surface_stores.json`, evaluated by `lane_registry.evaluate_lane`. On its first
  run it reported `strategy_signals` SILENT at 581h and `paper_trade_proposals[momentum_scalp]`
  SILENT at 1496h. Scope the row to the strategy: the unscoped table read LIVE at 0.6h because
  other strategies kept writing it, and an aggregate cannot see a per-strategy cliff.*
- **A verdict that reaches only a log file has not reached the operator.** State plainly which
  findings surface and which do not. *The store-cadence monitor's SILENT verdict does not yet
  reach a surface; that is named debt, not a closed item.*
- **One chokepoint.** Every operator-facing send goes through one transport that
  applies policy. A direct send path or a router bypass requires a declared
  reason and is CI-gated. *Cause: 155 producers, ~50 direct API paths, 34 router
  bypasses across 30 files; what reached the operator was decided by which path a
  producer happened to use, not by priority.*
- **Every send records a durable receipt** — message id on success, error on
  failure. **A send with no receipt is not a send.** *Cause: `sent_telegram` 0 of
  864 rows and `telegram_sent_at` 0 of 932; nobody could establish which producer
  emitted 25 repeats, or whether any specific POST succeeded.*
- **An absent field never defaults to an affirmative value.** Absent renders as
  `not computed`. *Cause: `Data quality: OK` asserted under every decision in a
  document whose own verdict was `ATTENTION` with two named defects — while
  confidence, counterpoint and next-review all honestly said "not provided".*
- **If the system computes a completeness or quality verdict, the operator
  surface renders it.** *Cause: `field_status` and `OPERATOR_PRODUCT_PARTIAL`
  computed on every entry and rendered nowhere; the reader saw four
  confident-looking lines the machine had already recorded as unpopulated.*
- **A retry that silently changes the request is a failure swallow.** *Cause: a
  Markdown 400 triggered a plaintext resend that was never logged, so identifier
  legibility was decided by underscore parity and nothing recorded which attempt
  the operator received.*
- **Notify on transitions, not on evaluations.** A condition that has not changed
  is not news. *Cause: a stop warning keyed on `(trade_id, alert_type)` with a
  30-minute window against a 3-minute cadence — 40 interrupts over four trading
  days, 83% of every row in its own alert table.*

## 9.2 Model calls

- **Free-first.** Persistent cognition, RAG, and the record's own lessons first. A model call is
  what happens when a material question survives that.
- **Lane per §12.** Probe availability live — `available()` returned `True` by default for any
  unrecognised lane until 2026-08-02, silently routing every DeepSeek call to local Gemma.
- **Record measured cost, the rate tier that applied, and whether input was a cache hit.** Never a
  literal. A hardcoded cost figure has already misled one audit.
- **Check the budget before the call. Never fail open.**
- **Cron in UTC** for any LLM-heavy job (§12).
- **No bare `except` on a model path.** If the lane cannot run, the surface says so — a brief that
  renders complete with a section silently absent hid a 97-day outage.
- **Every generated field is labelled generated**, and `writer` names the **author**, not the last
  hand that touched the record.

## 9.3 Scheduled jobs

- **A job has a `config/lane_registry.json` row with an `output_signal` before it is installed** —
  the durable artifact that proves it ran. Not an exit code, not a log file existing.
- **Installing, editing or removing a scheduler entry is operator-only. Propose.**
- **Dry-run under the exact cron form**: by path, neutral cwd, from a **pinned release directory**,
  never `CURRENT`.
- **Verify both schedulers** — cron and systemd.
- **Retirement carries its reason**: `# RETIRED <date> lane=<id> reason=<why> owner=<who>
  review_by=<date>`. **Never invent a reason**; an honest `UNKNOWN` is itself a finding.
- **After install, verify durable evidence on the natural schedule** — a hand-run does not close it.

## 9.4 Store writes

- **One declared writer per store.** A second writer is a finding, not a convenience.
- **Byte snapshot before and after; additive only** — rows added, ids removed = 0, confirmed states
  downgraded = 0.
- **Holdings route through `protected_holdings_write()`**, always.
- **Never merge divergent copies.** Report both; escalate.
- **Fix path resolution at the resolution layer, never at the cron's working directory.** A
  cron-level fix leaves the next caller free to reintroduce it.
- **Writes land on the served path.** A correct value written where nothing serves it is not a
  write. This class has been found four times.

## 9.5 Operator surfaces and fields

- **Provenance class at the point of display**, on every field.
- **`as_of` per block**, not inherited from composition.
- **One producer per number.** No two surfaces may state the same quantity differently without a
  labeled scope saying which question each answers.
- **A field whose value never moves regardless of input is a constant, not a judgment.** Test by
  feeding the producer materially different situations and finding which rendered fields are
  byte-identical across all of them.
- **A new operator-facing field requires a provenance row** before it ships.

---

# 10 · Deploy protocol

- `prepare` → `promote` → **verify the live directory independently**.
- The deploy script reads **its own worktree's HEAD** — detach onto the merged commit first.
- **Prove behaviour from the served release**, not that files copied.
- Additive only on append-only stores; verify by byte snapshot.
- `logs/` and state directories are symlinks to persistent state. A release starting them empty
  orphans evidence and makes the deploy **silently non-additive**.
- One PR per finding, validation output quoted in the body.
- **A push is not a deploy and a merge is not a deploy** — `AI_WORK_POLICY.md` §21, §27.

---

# 11 · Multi-agent protocol

- **Parallel is for** independent investigation, disjoint fixes with declared file sets, tests for
  separate modules.
- **Never parallel:** two agents writing the same file, store or crontab; anything touching
  holdings, the identity registry, lineage stores or the InstrumentRecord store; deploys.
- Before dispatch, each agent **declares its file set and store set**. Overlaps are serialized.
- On conflict the `[VERIFIED]` claim wins. If both are verified, **check as-ofs before calling it a
  conflict**, then re-run both.
- **No agent marks its own work DONE.** The coordinator marks it, against the proof.
- **When a finding contradicts the brief, the finding wins.**
- Handoffs are local — `AI_WORK_POLICY.md` §14. GitHub is not an inter-agent message bus.
- **Other sessions may be running on this machine.** Six promotes inside one hour have been observed
  from a peer session. Stamp every measurement with the pin it was read at.

---

# 12 · Model lanes — which to use, and why

| lane | cost | transport |
|---|---|---|
| free-first: persistent cognition, RAG, record lessons | $0 | no model at all |
| local Ollama (`qwen3:1.7b`, `qwen3:14b`) | $0 | local |
| Grok | free | OAuth proxy `:8645` |
| ChatGPT | free | codex proxy `:8646` |
| `deepseek-v4-flash` | paid | `config/llm_model_registry.json` |
| `deepseek-v4-pro` | paid | API |

**Selection.** Free-first always. Local Ollama for structural work — classification, extraction,
formatting. **The OAuth lanes for peak-hour work and for critique** — a critic on a different
provider does not share the author's blind spots, which is the point of a critique.
`deepseek-v4-flash` off-peak is the default paid lane for volume; `pro` for reasoning-heavy
synthesis, off-peak only.

**Never route on a readiness flag alone. Probe live.**

## DeepSeek pricing and scheduling — binding

Source: https://api-docs.deepseek.com/quick_start/pricing (verified 2026-08-30). **Prices change.
Re-verify; never quote from memory.**

**Peak: 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday. Everything else off-peak, at half rate.**
The weekday qualifier is **UTC**.

### This box runs US Eastern (`America/New_York`) and observes DST

| | EDT (Mar–Nov, UTC−4) | EST (Nov–Mar, UTC−5) |
|---|---|---|
| Peak block 1 | 21:00–00:00 | 20:00–23:00 |
| Peak block 2 | 02:00–06:00 | 01:00–05:00 |
| Off-peak | 00:00–02:00 and 06:00–21:00 | 23:00–01:00 and 05:00–20:00 |

**The entire US trading day is off-peak. All weekend hours are off-peak.** Cheap and timely are not
in tension.

**Never schedule an LLM-heavy job on a local-time cron expression.** The window is fixed in UTC, so
a job pinned to Eastern crosses into peak twice a year at the DST boundaries and doubles in cost
with nothing reporting it. **Schedule in UTC**, or compute the window at runtime from UTC.

### Rates per 1M tokens (off-peak / peak)

| | flash | pro |
|---|---|---|
| Input, cache hit | $0.007 / $0.014 | $0.022 / $0.044 |
| Input, cache miss | $0.22 / $0.44 | $0.66 / $1.32 |
| Output | $0.66 / $1.32 | $1.98 / $3.96 |

Context 1M, max output 384K. Concurrency: flash 2500, pro 500.

**Caching is the larger lever.** Cache hit against miss on input is **31×**; peak against off-peak
is **2×**. A system re-sending the same record, thesis and lesson context every wake is exactly the
shape that benefits. **Get caching right before scheduling.**

**If the configured cap makes a lane unable to run meaningfully, that is a finding to report** — not
a reason to exceed it, and not a reason to starve silently.

## Search providers

Budget state **persists to disk or DB, per provider**. An in-memory cache does not survive cron
invocations — that is how a 1,000-call monthly budget vanished in three weeks. Web search serves the
residual-web lane (≤1 hop per `subject_key` per day, budget N=3), **not bulk news** — news belongs
on RSS and Finviz. When the engine pool is degraded, the research output says so.

---

# 13 · Architectural standards

From `docs/convergence/INTEGRATION_RULES.md`, which this file now carries:

- **One canonical source of truth per concept.** Extend existing contracts instead of cloning.
- **No concurrent edits to shared files.**
- **No frontend business logic** for runtime, materiality, notification or maturity decisions.
- **Every claim has an implementation reference, a test, an evidence class, and a reproduction
  command.**
- **Read-only by default.** No broker, order, stop, risk-policy, 2FA or financial-policy mutation.
- **Agents commit locally and hand off a SHA**; the integrator reviews before merge.

Mechanically enforced standards live in `docs/ENGINEERING_HARD_RULES.md`, **hook-blocked at commit
and push**: no secrets in git; no hardcoded values — broker/account-agnostic, config from a source,
a missing account **fails closed**; `holdings.json` never wiped. Install once after clone:
`bash scripts/install_git_hooks.sh`. Verify: `python3 scripts/check_no_secrets.py --tree`.

## 13.4 · The type vocabulary — what already exists

**Read this before proposing any new type, store, field, or mechanism.** §13.5's pre-build check
is unusable without it: an agent cannot search for what it does not know is there.

### Registered id types — `CanonicalStoreRegistry@v1`

```
workflow_id     event_id        research_id     artifact_id
generation_id   notification_id checkpoint_id   outcome_id
lesson_id       operator_turn_id                instrument_record_id
```

All under `GOOD_PERSISTENT_ROOT`. **A new id type requires justification against these eleven.**

### Subject-key namespace

```
HELD:SYM        a current position
EXIT:SYM        a former position, in the re-entry book
WATCH:SYM       watched, not held
SECTOR:name     a sector as a first-class subject
SLEEVE:CASH     the cash sleeve
```

A subject key names an `InstrumentRecord@v1`. **Records can be woken, hold a thesis, carry operator
turns, and have a cadence. Tags cannot.** If a thing needs research on a schedule, it is a record.

### `InstrumentRecord@v1` — the persistent unit

```
subject_key
thesis · cc_narrative              CC reads cc_narrative; writers rewrite it
last_event · last_price_hash
research[] · artifact_ids
operator_turns[]                   ack / defer / reject / question land HERE
lessons[]                          cognition only → next question, priority
analyst · earnings_next
next_eligible_at · notify_priority
```

Loaded by `load-by-subject` on every wake. `plan_id` on every wake. An operator ack or defer writes
back onto **this** record.

### Pipeline stages — extend these; do not build alongside them

```
S0_OPERATOR_CONVERSE      the operator is an event; a Telegram reply is the next S0
CANONICAL ENTITY          ticker ≠ CUSIP ≠ ETF-without-CIK; dust residual ≠ a position
MATERIALITY               S1–S7, persist fairness → notify_priority
GRAPH IMPACT              1-hop, held non-dust only
RESEARCH GAP              gap vs THIS record, not a blank page
FREE-FIRST RESEARCH       persistent cognition · Hermes/RAG/FRED · librarian grading
                          then residual web, gated, ≤1 hop per subject_key per day, budget N=3
                          then LLM only if unresolved AND materially useful
SPECIALIST DISPATCHER     thin; no second harness; same workflow_id
CIOCouncilSynthesis@v1    deterministic; DISPUTED stands
WRITE BACK                cc_narrative · next_research_question · next_eligible_at · notify_priority
CIOOperatorProduct@v1     DETERMINISTIC_PRODUCT · $0.00 — CC sections BIND to the record
NOTIFICATION POLICY       fires only if notify_priority crossed a bar
                          IMMEDIATE · DIGEST · COMMAND_CENTER_ONLY · SUPPRESSED
DELIVERY RECEIPT/DEDUPE   sent or would_send, stamped
OutcomeCheckpoint@v1      plan_id or plan_binding reason, bound at creation
OUTCOME → LESSON          support-only, cognition apply
REVIEW_READY              next wake loads the record
```

### Artifact types

```
SpecialistArtifact@v1-lite   specialist output; same workflow_id; writers update THE SAME record
CIOCouncilSynthesis@v1       deterministic synthesis
CIOOperatorProduct@v1        the operator-facing product
OutcomeCheckpoint@v1         a checkpoint bound to a plan at creation
AgentView@v1                 an agent-formed view — claim, reasoning, confidence, falsifier.
                             Provenance class A. Marked as opinion everywhere it is displayed.
AGENT_COMMITMENT@v1          subject_key · claim · confidence · horizon · falsifier · checkpoint_id
                             A view with no falsifier is not a commitment — it is a sentence,
                             and it does not enter the store.
                             MBI_BEHAVIOR stays 0: a commitment is a belief, never an order.
```

**`AgentView@v1` and `AGENT_COMMITMENT@v1` are specified and currently have no producer.** They are
not missing types. They are unbuilt producers for existing types, and building them is the
judgment and commitment work in the future-state spec.

### Provenance classes — every operator-facing field carries one

```
D  deterministic     rule, threshold, arithmetic; reproducible
T  template          fixed prose around D values; reads as commentary, contains no judgment
M  model-assisted    a model produced it; a deterministic gate validated it
A  agent-originated  the agent chose the subject, sought evidence, formed a view
S  snapshot-derived  reproduced from a stored artifact; may disagree with a live D computation
```

### Cognition boundary

```
MBI_BEHAVIOR  = 0    cognition may NEVER move size, weight, order, stop.
                     BehaviorWriteRefused raises — refused outright, never silently filtered.
                     Not an env var: an unconditional raise at cio_instrument_record.py:390.
MBI_COGNITION = 1    cognition MAY move next_research_question, next_eligible_at,
                     notify_priority, cc_narrative. A write moving none of these raises
                     CognitionNoOp and is a FAILED persist.
```

### Before proposing anything new

1. Which registered id type covers this? If one does, use it.
2. Which pipeline stage owns this behaviour? If one does, extend it.
3. Which record field holds this state? If one does, add to it.
4. Does an existing type have the shape with fields missing? **Add the fields.**
5. Only then propose something new — **and state in the PR body which of 1–4 you ruled out and
   why.**

**A PR introducing a new `@v1` type, store, or subsystem without that statement is incomplete.**

## 13.5 · Pre-build check

Before building a new type, store, field, subsystem, or parallel mechanism:

1. **Read §13.4.** The pre-build search is unusable without knowing what already exists. An agent
   that has not read the type vocabulary will search for the wrong names and conclude, honestly and
   wrongly, that nothing exists.
2. Search the hub for the registered id types, subject keys, pipeline stages, and artifact types
   named in §13.4. Prefer an exact name match over a synonym.
3. If a match exists, **extend it**. Do not clone it under a new `@v1` name or a parallel store.
4. If you still propose something new, state in the PR body which of §13.4's five questions you
   ruled out and why. A PR without that statement is incomplete.

---

# 14 · Documentation standards

Documents in this repository are evidence. They are read by people deciding what is true about a
live financial system, and they have been wrong often enough to need a standard.

## Every document carries a header

```
Status:      ACTIVE | SUPERSEDED BY <path> | HISTORICAL | DRAFT
as_of:       <ISO timestamp>
Measured at: <commit sha> / <live pin>, or "not measured"
```

**A document with no `as_of` cannot be trusted and cannot be compared to a later one.**

## Rules

- **Superseded documents say so at the top, in the header, not silently.** Never delete a document;
  mark it. A reader finding a stale document with no marker will act on it.
- **Verbatim or a stub — never a reconstruction.** Where a text was not preserved, the stub says so
  and stops. Rebuilding a brief or a decision from a later summary produces something that reads as
  authoritative and was never written — the manufactured-evidence pattern, aimed at the instructions
  themselves. **An honest gap is worth more than a plausible reconstruction, because a reader can
  act on a gap.**
- **Every finding carries its evidence tag** (§4) and every number its `as_of` and root.
- **A document asserting runtime behaviour cites the command and its output.** Without that it is
  `[DOC-CLAIM]` no matter how confidently written.
- **Keep the corrections in.** A write-up that shows what it got wrong is more useful than one that
  reads clean.
- **Do not invent a reason.** `UNKNOWN` is a legitimate and expected entry, and its count is itself
  a measurement.

## Where things go

| kind | location | naming |
|---|---|---|
| audits and censuses | `docs/audits/` | `<SUBJECT>_<YYYY-MM-DD>.md` |
| operational runbooks, conventions, incidents | `docs/ops/` | `<SUBJECT>.md`, incidents dated |
| wave briefs | `docs/briefs/` | `WAVE_<n>_<slug>.md` — see that README |
| architecture and ADRs | `docs/architecture/` | `<SUBJECT>.md` |
| domain knowledge | `.claude/skills/*/SKILL.md` | never behavioural rules |

**Drive** holds the durable audit corpus. **Never sync `.env`, keys, or credentials** — the sync
excludes them and `check_no_secrets.py` blocks them at commit.

## Closeout format

Every wave closes with: what shipped (PR numbers, merge commits, live pin); what was found; what
was closed as already-merged; what stopped and why; what remains **unpublished, stated at the top
of the report rather than in a footnote**; and the operator-only list — which should be shorter
than at the start.

---

# 15 · The maturity bar — five proofs, not a percentage

A package is complete when its proof is observed **at runtime, from the served release, with the
command quoted**.

| # | proof | |
|---|---|---|
| M1 | Research | The system raised a research request itself, it completed, and it changed a named field on a named record. Show the diff. |
| M2 | Advice | A critique verdict changed `next_research_question` rather than being logged beside it. Show both questions. |
| M3 | Feedback | An operator reply landed on a record and changed the next wake's behaviour. Show the decision with and without the turn. |
| M4 | Consistency | Every operator-facing number traces to one regenerable producer, and no two surfaces state the same quantity differently without a labeled scope. |
| M5 | Persistence | A scheduled wake loads the record before acting, and a disposition made days earlier is still honoured with nobody replaying it. |

`NOT OBSERVED` is acceptable and expected. **A truthful three-of-five is worth more than a claimed
five.** If all five come back observed on the first attempt, assume something is wrong and find it
before reporting.

**Maturity is not scored as a percentage here.** Any document that does — including the skill — is
superseded by this section.

---

# 16 · Not accepted as completion

A package DONE on CI alone · a number quoted from a document rather than regenerated · a proof
staged by hand where the claim is that it happens on schedule · a metric whose floor makes failure
unreportable · a gate that has never executed or cannot go red where it runs · a check whose name
promises more than its code verifies · a producer reconstructed to justify an already-published
number · a dry run that reports nothing · work ending a wave uncommitted, unmerged or undeployed
without that being stated at the top of the report.

---

# 17 · Operator-only decisions

Propose and stop.

Collapsing the two holdings copies · changing what is ranked onto an operator surface · any new
production cron or systemd entry · **weakening the behaviour rail in any form** — editing
`BEHAVIOR_FIELDS`, altering or conditionalising the unconditional raise at
`scripts/lib/cio_instrument_record.py:343`, or routing a cognition write around it; there is no
variable to raise, the control surface is the code · re-enabling the retired
overnight LLM window · merging divergent copies of any authoritative store · branch-protection or
required-context changes · provisioning or funding any model or data plan · deleting anything ·
anything in the broker subsystem, credentials, or 2FA.

**The deferred list should shrink each wave.** The escalate-never-resolve rule exists for cases
where a machine choosing between two candidate truths can destroy one. It does **not** cover
labeling, error strings, routing defaults whose conservative option is reversible, or additive
monitoring. **If the deferred list grows during a wave, that is a finding about how the wave was
run.**

---

# 18 · Runtime notes

## Services

- **Backend** — `.venv/bin/python scripts/portfolio_server.py` (stdlib HTTP server, **not** Flask,
  `:7777`). Serves `/api/*` via `scripts/api_v2.py` and the SPA under `/v3/`.
- **Frontend (dev)** — `npm run dev` in `apps/command-center-v3` (Vite `:7789`, proxies `/api` →
  `:7777`). Production: `npm run build` → `dist/`, served at `:7777/v3/`.
- **JSON-only mode is fully supported.** With no Postgres env vars, `db_adapter.py` falls back to
  JSON — this matches the `--source-only` CI proof. `data/`, `state/`, `reports/` are gitignored.

## Lint, test, build

- **Frontend:** `npm run build` (`check_design_tokens.sh` + `test_chip_scope.mjs` + `tsc` +
  `vite build`). Guard only: `npm run design:guard`.
- **Release proof:** `TRADE_AI_CI=1 .venv/bin/python scripts/run_release_ci_equivalent.py --source-only`.
- **Python:** `.venv/bin/python -m pytest tests/<file>.py`. `*real_postgres*` and the
  options-lifecycle suite need Postgres. `pytest` is not in `requirements.txt`.
- **Node e2e** (`tests/e2e/*.mjs`) need Playwright/Puppeteer/`canvas` and a running server.

## Gotchas

- **Holdings write guard (`MIN_TOTAL = 1_000_000`)** fail-closes any total below ~$1M. Seed tests
  with a realistic book.
- **`/api/v2/overview` and many endpoints cache ~60s** from `holdings.json`.
- **CC v3 stale-bundle auto-reload** — `cc-boot.js` plus an inline check compares
  `build-meta.json`'s `ui_version` against `sessionStorage` and does a one-time full reload. A
  black screen with a spinning white cube is that reload, not a crash. Rebuild `dist` after UI
  edits.
- **Backend hot-reload covers only `api_v2.py` and `reports_portal.py`.** Any other module —
  `portfolio_loader.py`, `account_policy.py`, the server itself — needs a full restart.
- **A minimal `.env`** (JSON-only, `ENABLE_TELEGRAM=false`) suffices for local dev.

## Repository visibility is a CI invariant

**`tardeai` stays public.** Public repos get unlimited free Actions minutes; private on a personal
account gets 2,000/month, exhausted in one busy merge day, after which every job fails with the
misleading signature in §8. Never flip visibility as a cleanup step — standing operator policy since
2026-07-18. If it must go private, set a non-zero Actions spending limit **first**.
`AI_WORK_POLICY.md` §13.1.

## Data freshness and the release boundary

**The pipeline writes to the canonical source tree; the server reads from the release directory.
Never let them diverge.** `scripts/deploy_portfolio_server.sh` replaces `data/portfolios/state/` and
`state/data_broker/` with symlinks back to the canonical source after rsync.

> **`[VERIFIED]` 2026-08-30: `DATA_DIRS_TO_LINK` covers five directories** —
> `data/portfolios/state`, `state/data_broker`, `data/runtime`, `data/health`, `data/cio`.
>
> **The gaps are outside that list**, and that is why the known splits exist: release-local
> `logs/`, the evening packet, risk state, and scheduled jobs resolving against the dev tree.
> Anything not in `DATA_DIRS_TO_LINK` is unprotected by this mechanism — check before assuming.

The data pipeline — the repricer, the moomoo sync, `portfolio_loader`, the orchestrator — writes
to the canonical tree. **If the portfolio totals or the top header look stale, check whether
`last_repriced` is from today** before suspecting the release boundary; `portfolio_server.py`
logs a CRITICAL warning to `logs/portfolio_server.log` at boot if `holdings.json` is more than 7
days old.

Never manually copy `data/portfolios/state/` into a release. If the header looks stale, confirm
`CURRENT/data/portfolios/state/holdings.json` is a **symlink**; if it is a regular file, remove and
re-link, then restart the service. `state/data_broker/portfolio_snapshot.json` is a 45s cache —
delete it and the next `/api/v2/overview` recomputes. `portfolio_server.py` prints a CRITICAL
warning at boot if `holdings.json` is more than 7 days old.

---

# 19 · Where things live, and how each tool finds it

| document | authority over | read it when |
|---|---|---|
| **`AGENTS.md`** (this file) | **agent behaviour — the single entry point** | always, first |
| `AI_WORK_POLICY.md` | remote sync, push budget, CI cost, deployment boundary. **Hook-enforced.** | before any push, PR, merge or deploy |
| `docs/ENGINEERING_HARD_RULES.md` | secrets, hardcoded values, holdings guard. **Hook-enforced.** | before touching config, credentials or holdings writers |
| `docs/ops/LANE_REGISTRY_AND_RETIREMENT_CONVENTION.md` | lane declaration and retirement | before disabling or adding a scheduled job |
| `docs/briefs/` | what each wave was asked to do | at the start of a wave |
| `config/lane_registry.json` | which lanes exist and what proves they ran | when a lane looks silent |
| `.claude/skills/*/SKILL.md` | **domain knowledge only** | for context on a subsystem, never for a behavioural rule |
| `config/*.yaml`, `config/*.json` policy | **trading and system policy** — the operator's | never edit without the operator |
| `CIO_ASIS_VS_SPEC_2026-08-30.md` | which pipeline nodes are LIVE / PARTIAL / UNWIRED / DARK | before claiming any stage works |
| `CIO_FUTURE_STATE_FULL_MATURITY.md` | the target: judgment, commitment, scoring, self-repair | before designing anything new |

## How each tool discovers this file

| tool | reads | mechanism |
|---|---|---|
| Codex / OpenAI agents | `AGENTS.md` | native convention |
| Claude Code | `CLAUDE.md` → here | adapter, advisory |
| Cursor | `.cursor/rules/*.mdc` → here | adapter, advisory — **plus `failClosed` pre-execution hooks**, the only mechanical guard in the set |
| GitHub Copilot | `.github/copilot-instructions.md` → here | adapter, advisory |
| any other agent | `AGENTS.md` | convention |

Longer-form human and agent documentation lives in `README.txt`, `ARCHITECTURE.md`,
`OPERATIONS.md` and `docs/`. Those describe the system; this file governs how you work on it.

**An adapter pointing here depends on the agent complying.** That is why §0 is duplicated verbatim
into every adapter: an agent that reads fifteen lines and stops must still know the ten rules that
prevent irreversible harm. Everything else lives here once.

**Enforcement is layered** (`AI_WORK_POLICY.md` §25): this file and the policy are the written
standard; the git hooks and Cursor's `failClosed` guards are the mechanical floor; GitHub CI is the
final independent check. **If an assistant ignores its adapter, the hooks still block a casual
push.**

> **Known asymmetry.** Cursor has mechanical guards and the shortest adapter. Claude Code has the
> longest context and no mechanical guard — its compliance is advisory. Cursor's hooks are wired by
> absolute path to a separate worktree with `failClosed: true`, so their absence is a hard stop.
> Both are open items, not resolved by this document.

---

# 20 · Amending this file

This file is not owned by one agent or one session. It goes stale the moment someone learns
something and does not write it down.

- **Anyone may propose an amendment**, by PR against this file, with the failure that produced the
  rule stated in the body.
- **A finding that contradicts this file opens an amendment PR in the same wave.** Report the
  contradiction once, continue the work, and open the PR — do not carry a known-wrong rule forward
  and do not stop the wave to litigate it.
- **The operator approves** any change to §0, §2 (authority rails), or §17 (operator-only).
  Everything else is a normal PR.
- **Every rule cites its cause.** A rule with no failure behind it is a preference, and preferences
  belong in a style guide, not here.
- **Rules are replaced, not accumulated.** When a rule is superseded, remove it and say why in the
  PR. A document that only grows stops being read, and an unread standard is worse than none because
  it still looks like coverage.

---

# 21 · Working style

Direct, evidence-based, and intolerant of work parked behind questions already answered.

Correct your own prior claims out loud when measurement refutes them. Keep the failures in the
write-up, not just the final state. Say `UNKNOWN` when it is true.

**When a finding contradicts this file, the finding wins.**
