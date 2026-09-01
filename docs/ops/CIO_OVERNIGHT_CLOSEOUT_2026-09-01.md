Status:      ACTIVE
as_of:       2026-08-31T23:47:00-04:00 (America/New_York)
Measured at: served release `d276657b7` (`CURRENT -> d276657b7-main-exact-phase2-20260831-225546`,
             symlink mtime 2026-08-31 22:56 EDT, re-verified unrotated at 23:41 ET);
             wave branch `overnight/maturity-maceration-2026-09-01` @ `5a65db998` (was `d20ed6a03`
             when §1 was first measured — the coordinator commits under this worker as it works);
             `origin/main` @ `2b9dc0de0` (moved FOUR times during the wave — §1, §1.1)
Corrections: §6.10 and §6.11 correct §1's own arithmetic. Read them before quoting any count here.
Canonical repo path: docs/ops/CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md
Authority:   READ_ONLY_ADVISORY closeout. Not a behaviour spec. No verdict here authorises an action.
             MBI_BEHAVIOR = 0. No broker path touched, considered, or called.
See also:    docs/briefs/WAVE_OVERNIGHT_2026-09-01.md  (the five-minute version of this file)
             docs/ops/CIO_OVERNIGHT_STITCH_2026-09-01.md  (coordinator log, 6 stitches)
             docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md  (A)
             docs/audits/CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md  ·  docs/ops/CIO_OUTCOME_DRY_2026-09-01.md  (B)
             docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md  (C)
             docs/audits/CIO_SURFACE_ASOF_2026-09-01.md  (D)
             AGENTS.md §14 §15 §16 §17

# CIO overnight wave — closeout, 2026-09-01

---

# 0 · UNPUBLISHED — read this before anything else

**AGENTS.md §14 requires this at the top of the report, not in a footnote. Here it is.**

**Nothing was pushed. Nothing was merged. Nothing was deployed. No cron entry was created,
edited or removed. No systemd unit was created, edited, restarted or stopped. No code file was
changed. No store was written. No process was killed. No Telegram message was sent. No model was
called. No broker path was touched.**

This wave produced **documents only**, as **local git commits** on the branch
`overnight/maturity-maceration-2026-09-01`, in the worktree
`/home/johnclaw/tradeai-wt-final-operator-convergence`.

`[VERIFIED]` as_of 2026-08-31T23:41 ET:

```
$ git rev-parse --abbrev-ref HEAD
overnight/maturity-maceration-2026-09-01
$ git status --porcelain
                                    # empty — clean tree, everything committed locally
```

A local checkpoint is `git commit`, not `git push` (AGENTS.md §0 rule 4). Remote sync requires
`TRADEAI_REMOTE_PUSH_AUTHORIZED=1` plus explicit operator intent, and **was not sought and not
performed.** Per §16, work ending a wave uncommitted, unmerged or undeployed is not a defect
**provided it is stated at the top of the report**. It is stated here.

**Every remediation in this document is a PROPOSAL.** Nothing below was applied. Where a command
is given, it is given so the operator can run it — not as a record that it ran.

---

# 1 · The unpublished commit count — and the number that counts 126 commits this wave did not write

Two baselines are available. **The larger one is wrong, and it is the one a reader reaches for
first.** It is wrong by a **constant offset of 126 commits** — not by a ratio, which is why §1.1
exists and why the ratio is deliberately not the headline here.

`[VERIFIED]` as_of 2026-08-31T23:41 ET, root `/home/johnclaw/tradeai-wt-final-operator-convergence`:

```
$ git log --oneline main..HEAD | wc -l
136
$ git log --oneline origin/main..HEAD | wc -l
10
```

**The honest number is 10. The misleading number is 136.**

## Why the smaller number is the honest one

`main` is a **local branch ref that has not been updated in a day**. `origin/main` is the published
history — what "unpublished" is measured against.

```
$ git log -1 --format='%H %ci %s' main
1b8002903e36ec3eb4e3270b5eab62a03dd76c3c 2026-08-30 23:40:02 -0400 test: align AI work-policy hooks with AGENTS.md behaviour hub (#739)
$ git log -1 --format='%H %ci %s' origin/main
8c4d109f50a5ba19d0c1115705f6458691dafa6c 2026-08-31 23:39:06 -0400 M3: the wake records what it would have decided without the operator turn (#715)
$ git log --oneline main..origin/main | wc -l
129
```

**Two different quantities live here and they must not be conflated.** This is the section whose
whole job is to stop a reader quoting a bad commit count, so both are named:

| quantity | value | what it is | moves? |
|---|---|---|---|
| **the offset** — `\|main..HEAD\| − \|origin/main..HEAD\|` | **126** | already-published commits that `main..HEAD` wrongly attributes to this wave | **no — constant** |
| **the staleness** — `git rev-list --count main..origin/main` | **130** (was 129 at 23:41) | how far the local `main` ref is behind published history | yes |

**The offset is 126.** Diffing this branch against local `main` counts 126 already-published
commits — other people's merged work — as though this wave had produced them:

```
136 (main..HEAD)  −  10 (origin/main..HEAD)  =  126        exactly, no remainder
```

**Reporting 136 would attribute 126 other people's merged commits to a docs-only overnight
census.** That is the manufactured-evidence shape §14 forbids, arrived at by laziness rather than
intent — which is exactly why it needs naming.

### Why staleness (130) and offset (126) differ by exactly 4

The gap is **4**, and those 4 are a finding rather than a rounding artifact — they are the commits
published after this branch was cut that were never merged into it. `[VERIFIED]` as_of
2026-09-01T00:02 ET:

```
$ git log --format='%h  %ci  %s' HEAD..origin/main
2b9dc0de0  2026-08-31 23:52:12  fix(finviz): cap momentum-class screens at 100M float (#811)
8c4d109f5  2026-08-31 23:39:06  M3: the wake records what it would have decided without the operator turn (#715)
db115caec  2026-08-31 23:28:26  docs(agents): amendment -- nine gaps, each citing the failure that produced it (#735)
d276657b7  2026-08-31 22:55:27  Merge pull request #810 from PatsKiller/feat/cio-p1-load-by-subject
$ git log --oneline HEAD..origin/main | wc -l
4
```

So `130 = 126 + 4`. The branch was cut from `c0ae53cf1` at **22:51**; stitch 0 opened the wave at
**23:14**. **Three of the four landed while the wave was running** (23:28, 23:39, 23:52); the
fourth, `d276657b7`, landed at 22:55 — in the nineteen-minute window between the branch point and
the wave opening, which is why the served release carries it and this branch does not.

**Those 4 commits are this wave's own duration, measured in other people's merged work.** Finding
(1) below — that `origin/main` was never a fixed baseline — is the same fact showing up in the
arithmetic. A reader who wants one number should take **126**; a reader who wants to know how stale
the local ref is should take **130** and re-measure it, because it moves.

The ten, in full `[VERIFIED]`:

```
$ git log --oneline origin/main..HEAD
d20ed6a03 cio(overnight): land Worker C deliverable + stitch 6 — the frozen CURRENT
542cb502d cio(overnight): correct the stitch log's own mis-stamped headers
afa8dd212 cio(overnight): land Worker D deliverable + stitch 5 — 14 cash statements, 3 values, one body
751b6ef86 cio(overnight): land Worker A and Worker B deliverables
340525e4f cio(overnight): stitch 4 — Worker D lands; three cash totals in one payload
158f6d6dc cio(overnight): stitch 3 — the record-store writer never existed; Worker B lands
b8832f8c8 cio(overnight): stitch 2 — Worker A lands; AGENTS.md 13.4 dark contract is stale
d660d7cea cio(overnight): record standing wake-on-pin-abort trigger
3ffef60d5 cio(overnight): stitch 1 — rule out tradeai-continuous; correct the holiday error
dddfd7cb6 cio(overnight): open federated maturity-maceration wave — stitch 0
```

All ten are docs-only. This closeout and the brief will make it twelve when the coordinator commits
them.

## CORRECTION TO THIS WORKER'S OWN BRIEF — `origin/main` moved during the wave

The brief that commissioned this closeout stated `origin/main` was at `d276657b7` and that
`main..HEAD` reported `132`. **Both were true when written and both are now stale.** The finding
wins (§0 rule 10), so the correction is recorded rather than quietly absorbed:

```
$ git log --oneline HEAD..origin/main
8c4d109f5 M3: the wake records what it would have decided without the operator turn (#715)   2026-08-31 23:39:06
db115caec docs(agents): amendment -- nine gaps, each citing the failure that produced it (#735)  2026-08-31 23:28:26
d276657b7 Merge pull request #810 from PatsKiller/feat/cio-p1-load-by-subject                 2026-08-31 22:55:27
```

`[VERIFIED]` as_of 2026-08-31T23:41 ET. **Two commits landed on `origin/main` while this wave was
running** — one at 23:28 and one at 23:39, both after stitch 0 opened at 23:14.

Three things follow, and the third matters most:

1. **The count `10` is stable across both baselines.** `d276657b7..HEAD` also reports `10`. The
   upstream movement does not change what this wave has left unpublished, because those commits are
   not ancestors of `HEAD`. The honest number survives the correction.
2. **The served release is now behind `origin/main` by two commits.** `CURRENT` is pinned at
   `d276657b7`. Nothing in this document measures `db115caec` or `8c4d109f5`, and no claim here
   should be read as covering them.
3. **`#715` is titled "M3: the wake records what it would have decided without the operator turn."**
   Work aimed squarely at one of the five maturity proofs merged upstream at 23:39, **thirty-two
   minutes after this wave began measuring, into a release that is not served, and it was not
   observed by any worker.** This is recorded in §3 under M3. It is not evidence for M3 and this
   document does not treat it as such — it is a pointer for the morning.

**The general lesson, and the reason this section is this long:** `main` in this worktree is a stale
local ref. Any wave measuring "what is unpublished" against it will inflate its own output by two
orders of magnitude while appearing rigorous. The correct baseline is `origin/main`, re-fetched, and
the count must be re-measured at close because upstream moves underneath a long-running wave.

## 1.1 · Re-measured at close — and the drift is itself the finding

Everything in §1 above was `[VERIFIED]` at **23:41 ET** and is left exactly as measured. By the time
this file was finished, **both refs had moved again.** `[VERIFIED]` as_of **2026-08-31T23:57 ET**:

```
$ git rev-parse HEAD            → c400501c1      (was d20ed6a03 at 23:41)
$ git rev-parse origin/main     → 2b9dc0de0      (was 8c4d109f5 at 23:41, d276657b7 in the brief)
$ git log --oneline main..HEAD        | wc -l    → 138        (was 136)
$ git log --oneline origin/main..HEAD | wc -l    → 12         (was 10)
$ git log --oneline d20ed6a03..HEAD
dc11dd94b cio(overnight): stitch 7 — operator raises frozen-CURRENT daemon to P0
c400501c1 cio(overnight): record standing wake-on-E-landing trigger
```

**The honest unpublished count at close is 13** — the coordinator added stitch commits under this
worker while it was writing, exactly as it did to Worker C (C's correction 1), and then landed this
packet as `5a65db998` *"land Worker E packet + stitch 8 — wave closed, M1-M5 zero of five"*.

**This sentence has itself been overtaken twice, and both versions are kept.** It first read that the
count was **10** and the files were untracked; then that it was **12** and the files were still
untracked (`git status --porcelain` showing `??`); as of 00:05 ET the count is **13** and the files
are committed. **The count moved three times while the paragraph describing it was being written.**
That is not a defect in the paragraph — it is the strongest available demonstration of the point the
section is making, which is why it is recorded rather than smoothed into a single final figure.

**This worker made no git write of any kind at any point** — no `add`, no `commit`, no `push`. The
coordinator commits. The offset stayed **126** across every one of these measurements.

**`origin/main` has now moved three times during a wave that ran under two hours**: `d276657b7`
(22:55) → `db115caec` (23:28) → `8c4d109f5` (23:39) → `2b9dc0de0` (by 23:57). The served release is
pinned at the first of those and is now **three or more commits behind published `main`.**

**Three things this section is for, and the third is the point:**

1. **The correction is kept rather than applied in place** (§14). A reader comparing §1's `136 / 10`
   against a fresh `git log` will get different numbers, and needs to know why before concluding the
   document is wrong.
2. **The ratio is unchanged and the lesson survives.** `origin/main..HEAD` went 10 → 12;
   `main..HEAD` went 136 → 138. **Both moved by the same +2, because the stale-`main` error is a
   constant 126-commit offset, not a rate.** A third pair taken at 00:02 ET makes the point
   conclusively — `[VERIFIED]` `main..HEAD` → **139**, `origin/main..HEAD` → **13**:

   ```
   136 − 10 = 126        (23:41)
   138 − 12 = 126        (23:57)
   139 − 13 = 126        (00:02)
   ```

   **Three measurement pairs, twenty-one minutes apart, one offset.** The misleading number stays
   misleading by exactly the same margin no matter when it is taken. **Re-measuring does not rescue
   the wrong baseline** — only changing the baseline does.

   Note what this kills: the *ratio* is not constant and must not be quoted. It was 13.6× at 23:41
   and 10.7× at 00:02, falling as the wave commits accumulate. **State the harm as the constant
   126, never as a multiple** (correction 6.11).
3. **A count is not a fact about a repository; it is a fact about an instant.** This is the same
   defect §12 item 10 names for every other number in this packet — `record_consult` read 335 / 337 /
   340, the checkpoint store grew three rows in eight minutes, the split sweep gave three totals —
   and it applies to the closeout's own headline measurement. **The document that spent §1 warning
   about a stale baseline had a stale measurement of its own within sixteen minutes.** Recorded
   because an error found by the party that made it is the cheapest kind there is (§6.4), and because
   a closeout exempting itself from its own standard is the failure mode §6.4 describes.

**Nothing else in this document was re-measured at 23:57.** Every other number carries its own `as_of`
and should be read at that instant, not at this one.

---

# 2 · P0 — a production daemon has been running frozen code for five days

**This is the top item in the morning packet, above every other finding.** It is a **PROPOSAL with a
verified diagnosis**, not an action taken. Nothing was restarted, killed, or touched.

Found by Worker C (`docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §2.4d), traced to the process by
the coordinator, and **independently re-verified by this worker at 23:44 ET** before publication.

## The diagnosis

`[VERIFIED]` as_of 2026-08-31T23:44 ET:

```
$ cat /proc/3637980/cgroup
0::/user.slice/user-1000.slice/user@1000.service/app.slice/tradeai-health-agent.service

$ systemctl --user status tradeai-health-agent.service
● tradeai-health-agent.service - TradeAI Health Agent daemon (continuous score + auto-remediate + tier1 escalation)
     Loaded: loaded (/home/johnclaw/.config/systemd/user/tradeai-health-agent.service; enabled; preset: enabled)
    Drop-In: 20-exact-main.conf, 30-current-collectors.conf
     Active: active (running) since Wed 2026-08-26 20:38:03 EDT; 5 days ago
   Main PID: 3637980 (python)        CPU: 2h 38min

$ systemctl --user show tradeai-health-agent.service -p Restart -p NRestarts -p WorkingDirectory
Restart=always
NRestarts=0
WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT

$ readlink /proc/3637980/cwd
/home/johnclaw/trade-ai-releases/portfolio-server/40360117-main-exact-phase2-20260826-202631
```

**`WorkingDirectory=` names `CURRENT`. The running process's cwd is `40360117`.** systemd resolved
the symlink once at start and froze it. The unit is `enabled`, `active`, and has **never restarted**.

The cause is one line in the wrapper the drop-ins point `ExecStart` at
(`/home/johnclaw/.config/tradeai/bin/health_agent_daemon_current.py`, mtime 2026-08-17) `[CODE]`:

```python
CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT").resolve()   # :15 — ONCE, at import
...
lpr.get_live_project_root = lambda: CURRENT                                             # :28
```

`.resolve()` follows the symlink and returns a concrete directory. The lambda then hands that frozen
path to **every subprocess** for the life of the daemon. It started 2026-08-26 20:38:03, twelve
minutes after release `40360117` was promoted at 20:26:31, and has held that one resolution ever
since. `[VERIFIED]` **166 release trees have been built under
`/home/johnclaw/trade-ai-releases/portfolio-server/` since that instant** (`find -maxdepth 1
-name '*-main-exact-phase2-*' -newermt "2026-08-26 20:26:31" | wc -l` → `166`), including tonight's
`d276657b7` at 22:56.

## Why this is P0 and not merely untidy — three reasons, all three required

**1 · It auto-remediates.** The unit description is *"continuous score + auto-remediate + tier1
escalation"*, and it is doing so right now `[VERIFIED]`, from the journal at 23:38:11:

```
{"cycle_done": true, "status": "degraded", "score": 70, "sleep_s": 310, "elapsed_s": 201.6,
 "enqueued": 0, "remediated_ok": 1, "skipped": null, "escalation": true}
```

`remediated_ok: 1` — and its escalation log records `dry_run=False`. **Five-day-old remediation code
is taking live remedial action against a system that has moved 166 builds underneath it.** Any fix
landed in `claude_escalation_handler.py` since 2026-08-26 is not running.

**2 · It is failing where nobody reads.** `[VERIFIED]`:

```
$ ls -l …/40360117-main-exact-phase2-20260826-202631/logs/claude_escalation_daemon.log
-rw-rw-r-- 1 johnclaw johnclaw 20121233 Aug 31 23:38          # 20 MB, appended tonight

$ ls -l /home/johnclaw/trade-ai-releases/persistent-state/logs/claude_escalation_daemon.log
ls: cannot access …: No such file or directory                # the filename does not exist there AT ALL

$ tail -4 …/40360117-…/logs/claude_escalation_daemon.log
  ❌ retry_cmd failed (rc=127, 0.1s)
Skipping Tier 2/3 LLM (19 remaining) — --tier1-only
[claude-escalation] SKIP Tier2/3 LLM — 19 remaining unfixed; Tier1 resolved=0 dry_run=False

$ grep -c "rc=127" …/40360117-…/logs/claude_escalation_daemon.log
16356
```

**16,356 `rc=127` failures** — *command not found*, exactly what a stale tree whose referenced paths
have moved produces — and **19 unfixed escalations with zero resolved**, written into a file that an
auditor reading `CURRENT/logs` cannot see. `logs/` under the served release is a symlink into shared
`persistent-state`; this log has no counterpart there. It is invisible by construction.

**3 · THE INVERSION — and this is the sentence that should land.**

`Restart=always`, and `NRestarts=0`. The daemon **would have re-resolved `CURRENT` on any crash.**
It has not crashed in five days.

**It is stale precisely because it has been healthy.** The longer it runs without fault, the more
wrong it gets. A daemon whose correctness decays monotonically with its uptime will never be caught
by a liveness check, an uptime check, or a restart counter — and every monitor on this box reports
it green. Health, here, is the failure mode.

## The remediation — two things, and they are not the same thing

**MITIGATION** — one command, safe, reversible, and self-healing under `Restart=always`:

```
systemctl --user restart tradeai-health-agent.service
```

Then verify it actually re-resolved, **which is the entire point**:

```
readlink /proc/$(systemctl --user show -p MainPID --value tradeai-health-agent.service)/cwd
```

That must print the current release directory, **not** `40360117-…`. Verifying by "the service is
active" would repeat the defect this finding is about: a guard verified by presence is not a guard
(§8). The service has been active and wrong for five days.

**DURABLE FIX** — the mitigation only resets the clock. A restart makes the daemon correct **until
the next promote**, and from that moment it silently rots again. Two candidate shapes, **proposed
and stopped; this document does not choose between them**:

- **(a)** Make the wrapper re-resolve the release root **per cycle** rather than freezing it at
  import.
- **(b)** Add a post-promote hook that restarts this unit.

**(a) alone may not be sufficient**, and this is stated rather than assumed away: the unit's own
`WorkingDirectory=` is also the `CURRENT` symlink path, and systemd resolves that at start too — so
the process cwd would remain frozen even if the wrapper's Python-side resolution were fixed. Whether
that matters depends on which subprocesses use cwd versus `get_live_project_root`, and **that was
not traced.** UNKNOWN.

## The bitter part, kept because it is the general lesson

The wrapper exists **to fix a root-resolution bug.** Its own docstring `[CODE]`:

> *"Host overlay: run exact-main CURRENT health daemon. `CURRENT/scripts/health_agent_daemon.py`
> rebases PROJECT_ROOT to the git checkout (DEV_ROOT) whenever that tree exists. That made #349
> collectors dead on a live exact-main release."*

It fixed that one and introduced this one. **A repair verified by the symptom it targeted** — §8,
almost verbatim. And the file is named `health_agent_daemon_**current**.py`: §7, a control whose
name exceeds its code.

## Classification

**OPERATOR-ONLY (§17).** Restarting a production daemon is not a docs-only action and is not within
this wave's authority. **DISCOVERED by this wave, not created by it** — the defect is five days old
and predates the wave by four days. Counted as a discovery in §7's tally.

---

# 3 · The maturity bar (AGENTS.md §15) — five proofs

**Per §15 this is not scored as a percentage, and no percentage appears anywhere in this document.**
Any document that scores one is superseded by §15. Per this wave's standing constraint, **no proof
may be recorded as OBSERVED**; the only admissible verdicts are `NOT_OBSERVED` and `CANDIDATE`.

| # | proof | verdict | pin / as_of |
|---|---|---|---|
| M1 | Research | **NOT_OBSERVED** | `d276657b7` · 2026-08-31T23:45 ET |
| M2 | Advice | **NOT_OBSERVED** | `d276657b7` · 2026-08-31T23:45 ET |
| M3 | Feedback | **NOT_OBSERVED** | `d276657b7` · 2026-08-31T23:45 ET |
| M4 | Consistency | **NOT_OBSERVED** — a documented *failure* case | `d276657b7` · 2026-08-31T23:43 ET |
| M5 | Persistence | **NOT_OBSERVED** | `d276657b7` · 2026-08-31T23:22 ET (Worker A) |
| — | *separately stamped, never merged into M5* | `M5_CANDIDATE` | **pin `1d64cb59f`** · 2026-08-31T07:12 ET |

**Zero of five observed.** §15 says a truthful three-of-five is worth more than a claimed five; a
truthful zero-of-five is the same instrument pointed at a system that is earlier than it looks. §15
also says that if all five come back observed on a first attempt, assume something is wrong — the
converse discipline applied here is that a zero must be *diagnosed*, not merely reported, and each
row below says what would remain to be shown.

**Four of the five fail through one shared cause: `cio_instrument_records.jsonl` has no production
writer** (§4.1). M1, M2, M3 and M5 all require a named field to change on a named record. Nothing
writes records. That is not four independent failures; it is one failure with four faces.

## M1 · Research — NOT_OBSERVED

> *The system raised a research request itself, it completed, and it changed a named field on a
> named record. Show the diff.*

**Met:** the system does raise research and it does complete. `[VERIFIED, Worker B §6]` **344
distinct `LessonCandidate@v2`, of which 343 are research-derived.** Research requests are raised,
run, and produce durable artifacts.

**Not met:** the clause *"changed a named field on a named record."* `[VERIFIED]` by this worker
against the served store, as_of 2026-08-31T23:38 ET, root
`/home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_instrument_records.jsonl`:

```
rows: 131
    126  migration:deterministic         updated_ts max 2026-08-30T14:53:41Z
      5  cognition:defer_honored         updated_ts max 2026-08-30T14:58:17Z
updated_ts min 2026-08-30T02:23:59Z   max 2026-08-30T14:58:17Z
```

Every row was written inside one twelve-hour window on 2026-08-30, and **126 of 131 by a migration
script.** Worker B traced the remaining five: they were produced by the migration too, through its
own call to `attach_operator_turn` (§4.1). **No research request has ever changed a field on a
record in production.** Additionally all 343 candidates carry `cannot_become_policy: true`
`[VERIFIED, B §6]` — the rail holds, and it also means none of them can become a record change by
design.

**What would remain to be shown:** a research request, raised on a schedule from the served release,
completing and writing a named field to a named `InstrumentRecord`, with the before/after diff
quoted. **Blocked on the missing writer.** This is not a research-lane defect; the research lane
works.

## M2 · Advice — NOT_OBSERVED

> *A critique verdict changed `next_research_question` rather than being logged beside it. Show both
> questions.*

**This is the closest of the five to a proof, and it still fails.** The field genuinely changed, and
both questions can be shown. `[VERIFIED]` by this worker, as_of 2026-08-31T23:45 ET, same store —
7 of 131 rows carry a non-empty `next_research_question`, all on subject `HELD:SCHD`:

```
HELD:SCHD  writer='migration:deterministic'   ts=2026-08-30T02:23:59Z
    q='Has the condition behind the defer changed (wait for price buffer)?'
HELD:SCHD  writer='cognition:defer_honored'   ts=2026-08-30T02:33:18Z
    q='Has a catalyst or earnings event changed the condition behind the defer (wait for price bu…'
HELD:SCHD  writer='cognition:defer_honored'   ts=2026-08-30T14:58:17Z
    q='Prior research was refused (rejected). What INDEPENDENT evidence would settle this without…'
```

The question was **replaced, not appended beside** — that is the right shape, and the third form
even names a refusal verdict as its cause. The code that does it is real: `cio_residual_web.py:883`
compares the new question to the record's existing one and writes it through at `:889` `[CODE]`.

**Three things disqualify it, and all three are needed:**

1. **The change cannot be attributed to a critique verdict.** The council store
   `data/cio/cio_council_synthesis.jsonl` is **4 lines, last written 2026-08-26 11:46**
   `[VERIFIED]` — four days *before* the question changed on 2026-08-30. Nothing links the two.
   Worker C independently scored `CIOCouncilSynthesis@v1` as **regressed, `█ → ░`**: one artifact,
   five days stale, `DISPUTED` count 0, sole caller not in crontab.
2. **The writer is the migration.** Every `cognition:defer_honored` row was produced by the one-off
   migration (§4.1). §16 does not accept *a proof staged by hand where the claim is that it happens
   on schedule.*
3. **Nothing schedules the path.** `[VERIFIED]` `crontab -l | grep -inE "residual_web|council"` →
   empty, rc=1. The only non-test importer of `cio_residual_web` is
   `cio_research_governance_census.py`, a report script.

**What would remain to be shown:** a critique verdict produced by a scheduled council run, changing
`next_research_question` on a record, from the served release, with both questions and the linking
verdict id quoted. The *mechanism* exists and is written; the *loop* is not closed.

## M3 · Feedback — NOT_OBSERVED

> *An operator reply landed on a record and changed the next wake's behaviour. Show the decision
> with and without the turn.*

`[VERIFIED]` by this worker, as_of 2026-08-31T23:45 ET, served store:

```
rows: 131
rows with non-empty operator_turns: 0
```

**Zero operator turns on any record, ever.** Worker C reached the same result from the opposite
direction — scoring OPERATOR turn / S0 as **regressed, `▓ → ✗`**, with the turn store **absent in
every root examined**. Two workers, two methods, one answer.

The second clause — *"changed the next wake's behaviour… with and without the turn"* — is a
counterfactual, and Worker A found that the system's own attempt at it is not admissible evidence:
the `record_changed_decision` line asserts `without_record=proceed`, but **that is the program's
claim about a branch it did not take** (A §8, rung 5, not rung 1).

**Late fact, recorded and explicitly not counted as evidence:** `#715`, *"M3: the wake records what
it would have decided without the operator turn"*, merged to `origin/main` at **2026-08-31
23:39:06** — during this wave. It is **not in the served release**, it was **not observed by any
worker**, and no measurement in this document covers it. If it does what its title says, it
addresses the *counterfactual-recording* half of M3. It does not address the half measured above:
there are no operator turns to record a counterfactual against.

**What would remain to be shown:** an operator reply persisted onto a named record, followed by a
scheduled wake at the served pin whose decision differs from the same wake without the turn, both
quoted. **Blocked on the missing writer, and on a turn store that does not exist.**

## M4 · Consistency — NOT_OBSERVED, and this one is a documented failure

> *Every operator-facing number traces to one regenerable producer, and no two surfaces state the
> same quantity differently without a labeled scope.*

**Naming a failure is not the same as proving a proof.** Worker D declined to declare M4 observed
and was right to; this row records the failure case, and the failure is severe.

`[VERIFIED]` by this worker — **single GET** of `http://127.0.0.1:7777/api/v3/cio/home`, as_of
2026-08-31T23:43 ET, pin `d276657b7`:

```
TOTAL statements of total cash in ONE response body: 14      distinct values: 3

  630,784.82  ×7   cash_letter.cash_usd
                   cio_now.decisions[2].cc_narrative.evidence_refs[3].total_cash
                   cio_now.decisions[3].cc_narrative.evidence_refs[1].total_cash
                   opportunities.watch[1].cc_narrative.evidence_refs[1].total_cash
                   opportunities.reentry[0].cc_narrative.evidence_refs[2].total_cash
                   opportunities.reentry[3].cc_narrative.evidence_refs[2].total_cash
                   opportunities.reentry[4].cc_narrative.evidence_refs[2].total_cash
  630,790.42  ×5   capital_plan.cash_total_usd · capital_plan.cash_earmarked_redeploy_usd
                   capital_plan.sources[2].usd · cash.cash_usd · operator_product.cash.cash_usd
  630,791.10  ×2   temperament.cash · operator_product.temperament.cash
```

**Fourteen statements of one quantity. Three answers. One page.** Reproduced exactly as Worker D
reported it, path for path. And `/api/v2/overview` states a fourth instance of the same quantity,
`total_cash = 630791.10`, stamped `as_of 2026-08-29` `[VERIFIED]`.

M4's first clause fails: there is no single regenerable producer — there are three, and
`/api/v3/cio/home` carries **all three at once**. M4's second clause fails: the surfaces disagree
and **no scope label distinguishes them.** A reader can find the contradiction without leaving a
single page.

**What would remain to be shown:** one canonical producer for total cash, both surfaces calling it,
and any legitimate variant carrying an explicit labeled scope. **Choosing that canonical producer is
OPERATOR-ONLY (§17)** — it is a schema and store question (§7 item 18). The tractable agent-safe
step is D's P4 parity assertion, which *surfaces* the gap rather than resolving it (§8).

## M5 · Persistence — NOT_OBSERVED at `d276657b7`

> *A scheduled wake loads the record before acting, and a disposition made days earlier is still
> honoured with nobody replaying it.*

Worker A's verdict, accepted: **`NOT_OBSERVED`** at pin `d276657b7`, as_of 2026-08-31T23:22 ET.

Criterion (a) — unattended, cron-parented — **is met**; A captured the ancestry
`python ← bash ← cron ← cron(pid 6472) ← systemd`. Criterion (b) — real wakes arriving — **is met**.
Criteria (c), (d), (e) are not met.

**A rejected both categories the brief offered it, and was right.** The verdict is neither *for want
of wiring* (the consult runs, on every fire) nor *for want of input* (wakes arrive). A named a third:
**`NOT_OBSERVED` for want of a live disposition.** `[VERIFIED, A §8]`:

```
distinct subject_keys (last-wins):                              40
  with no next_eligible_at:                                     38
  with next_eligible_at IN THE FUTURE (would cause a skip):      0
  with next_eligible_at EXPIRED:                                 2
     HELD:SCHD    next_eligible_at=2026-08-31T14:58:17Z
     SLEEVE:CASH  next_eligible_at=2026-08-31T14:53:41Z
```

**Zero unexpired deferrals exist.** Criterion (d) is therefore **structurally unsatisfiable at any
wake volume**, and the prediction is confirmed by the log: the last `skipped_cadence_not_due ≥ 1`
line in the entire history is `2026-08-31 10:57:32` — **45 seconds before the last deferral
expired.** Nothing about the timer, the queue, or the loader needs fixing.

**What would remain to be shown:** a wake at the served pin meeting (b)–(e); that `1d64cb59f` and
`d276657b7` share the consult path unchanged across eleven promotes (**UNKNOWN — not checked**); that
`record_found ≥ 1` reflects a real read rather than a skipped fail-open branch; and a mutation test
removing `next_eligible_at` to prove the skip is causal rather than correlational. **Blocked on the
missing writer.**

### `M5_CANDIDATE @ pin 1d64cb59f, as_of 2026-08-31T07:12 ET` — correctly stamped, NEVER merged

A separate claim against a **different release**. It is recorded here in full and is **not** part of
the `d276657b7` verdict above. `[VERIFIED, A §8]`:

```
2026-08-31 07:12:05,623 [tradeai.cio_wake_dispatch_entrypoint] record_consult:
  wakes=5 subject_resolved=5 record_found=5 changed_by_record=5 skipped_cadence_not_due=5 no_subject=0
```

Every clause met: (a) in the regular `*/5` series · (b) `wakes=5` · (c) `record_found=5` ·
(d) `skipped_cadence_not_due=5`, corroborated by named `HELD:SCHD` skip lines · (e) disposition
written 2026-08-30T14:58:17Z, store untouched for 24h.

**Worker A refused to promote this to a candidacy for `d276657b7`, and the coordinator and this
closeout both accept that reasoning.** `1d64cb59f` was the served release at 07:12; `logs/` is a
symlink into shared `persistent-state`, so the log spans **twelve promotes on 2026-08-31 alone**.
Rung 1 requires observation *from the served release*. Promoting a measurement across a promote
boundary would be an unstamped measurement in a repository where `CURRENT` rotated twelve times in a
day. **A declined a stronger headline against its own interest.** That is §11 working.

**Never merge this candidate into the M5 verdict.** Any future reader who wants it to count must
first show that the two pins share the consult code path unchanged — which is currently **UNKNOWN**.

**Corroborating detail this worker found while verifying the late fact (§5)**, worth recording
because it shows the proof's own sentence in the log, from a night ago at a different pin
`[VERIFIED]`:

```
2026-08-30 23:57:04,487 [tradeai.cio_wake_dispatcher] wake wake_ev_morgan_… skipped by record:
  HELD:SCHD: the record defers research until 2026-08-31T14:58:17+00:00 (11.0h away).
  The disposition was recorded earlier and nobody replayed it.
```

Three such lines fired at 23:57 on 2026-08-30 — **exactly twenty-four hours and one deferral-expiry
before the identical wake ids fired tonight with `subject_resolved=0`.** The system said M5's own
sentence out loud a day ago and cannot say it tonight, because the deferral it was honouring has
expired and nothing exists to write another.

---

# 4 · The seven headline findings

They are numbered as the packet leads with them, and **they connect** — 1 → 3 is a single causal
chain, and 1 → 2 is the same defect committed twice.

## 4.1 The record store has no writer, and never had one

`[VERIFIED]` by this worker, as_of 2026-08-31T23:38 ET, root `persistent-state`:

```
$ wc -l …/data/cio/cio_instrument_records.jsonl
131
    126  cc_narrative.writer = migration:deterministic
      5  cc_narrative.writer = cognition:defer_honored
updated_ts: min 2026-08-30T02:23:59Z   max 2026-08-30T14:58:17Z    rows with no updated_ts: 0
$ ls -l …/cio_instrument_records.jsonl
-rw------- 1 johnclaw johnclaw 392062 Aug 30 10:58        # ~37h silent at time of writing
```

**126 of 131 rows written by `cio_migrate_instrument_records.py` in one 12-hour window on
2026-08-30.** The file mtime (Aug 30 10:58 EDT = 14:58 UTC) matches the last row to the second.

`[VERIFIED]` by this worker — `persist_instrument_record` has **ZERO callers** in the entire served
release:

```
$ grep -rn "persist_instrument_record" …/CURRENT --include=*.py
…/CURRENT/scripts/lib/instrument_record.py:116:def persist_instrument_record(record: Mapping[str, Any]) -> bool:
```

**One occurrence: its own definition.** Nothing calls it.

`[VERIFIED]` Nothing in the crontab reaches `upsert()` by any path:

```
$ crontab -l | grep -inE "specialist_artifact|migrate_instrument|rehydrate|instrument_record"
(empty, rc=1)
```

Worker C traced the full write graph `[CODE]`: `InstrumentRecordStore.upsert()`
(`scripts/lib/cio_instrument_record.py:309`) is the class's only write. `stamp_last_artifact_id()`
is the one path plausibly reachable on a wake — and it is not reached, because of a **name
collision**: `cio_run_worker.py:33` imports `cio_specialist_artifact**s**` (plural) while the stamp
lives in `cio_specialist_artifact` (singular). Even if reached it writes `last_artifact_id` only and
**cannot set `next_eligible_at`** — it could never create a deferral. `apply_after_cycle()`'s only
non-test caller chain terminates at `cio_migrate_instrument_records.py:152`.

**So the five `cognition:defer_honored` rows — the only non-migration writes that have ever
existed — were themselves produced by the migration.** The cognition writer has never run outside a
migration.

**This is `AGENTS.md` §3's defect and §13.4's own warning, by name:** *"An agent that ships a
feature on top of them without wiring the consumer is repeating the filing-cabinet defect."*

**M5 is blocked on the writer, not the wake.** So are M1, M2 and M3. Corollary: the five deferrals
that expired this morning were the *migration's* deferrals, and when they expired the system's
entire supply of honourable dispositions was exhausted with no process existing to make more.

**Contradiction with a register entry, flagged for morning.**
`docs/audits/CIO_DILIGENCE_GAP_REGISTER.md` records **`G-IR-01` as `CLOSED (mitigated)`** —
*"InstrumentRecord not universal wake load — #702: wake load + `last_artifact_id` stamp"*. Tonight's
evidence shows the `last_artifact_id` stamp path is **unreachable** (singular/plural collision,
zero log evidence: `grep -ci "last_artifact_id\|stamp_last"` over the whole dispatcher log → `0`).
A gap register entry closed on a mitigation whose stamp half never fires is a **`[VERIFIED]`
contradiction between this wave and a standing register**, and it is queued for the morning
(§9). This closeout does not edit the register.

**Evidence tag on the doc:** `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §3;
`docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md` §8; stitch 3.

## 4.2 PR #810's own contract is dark — the PR written to close the filing-cabinet defect reproduced it

Worker C `[CODE + VERIFIED]`, `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §3.4.

C refused to answer "is `load-by-subject` dark?" as one question, and splitting it is what produced
the finding:

- **The pre-claim consult** at `cio_wake_subject.py:168` is **(b) CODE-WIRED, RUNTIME-UNPROVEN.** It
  runs on a schedule. This is the half that made §13.4 look stale.
- **PR #810's own contract is (a): DARK.** `decide_after_load` — *the module whose title is "load
  InstrumentRecord before `ResearchNeedDecision.decide()`"* — has exactly two non-test callers: one
  behind `--dry-run`, **which the cron does not pass**, and one unscheduled report script.

**The PR written to close the filing-cabinet defect reproduced it.** That is the single sharpest
sentence the wave produced, and it corrects the coordinator's stitch 2 reading: the telemetry that
made `load-by-subject` look wired is a **different, shallower consult** than the one #810 shipped.

The general shape recurs — see 4.6, where three of four regressions are the same defect.

## 4.3 The stale store leaks into operator prose, and six live decisions cite it as evidence

This is the chain that closes 4.1 to the operator's screen, and **no single worker could see it** —
A found the dead writer, D found the leak, and the wave connected them.

`[VERIFIED]` by this worker, as_of 2026-08-31T23:43 ET, single GET of `/api/v3/cio/home`:

```
cash_letter.what:              'Cash sleeve 630784.82.'
cash_letter.cash_usd:          630784.82
cash_letter.cash_investable_usd: 374195.2
cash_letter.as_of:             2026-08-03
```

**`630,784.82` is the sentence the operator reads.** It originates in the stale `SLEEVE:CASH`
`InstrumentRecord` — the store 4.1 proves no production process has written since 2026-08-30.
Precedence at `cio_record_narrative.py:103-105` lets the record win over the live plan `[CODE, D]`.

**And it is cited six times as `evidence_refs[*].total_cash`** — by `cio_now.decisions[2]`,
`decisions[3]`, `opportunities.watch[1]`, and `opportunities.reentry[0]`, `[3]`, `[4]` (paths
enumerated in §3/M4). **The stalest of the three values is the one live decisions and re-entry
candidates point at to justify themselves.**

The block does not even reconcile with itself: `630,784.82 − 256,595.22 = 374,189.60`, but it
displays `374,195.20` — a stale total paired with a live investable figure, both stamped under an
`as_of` belonging to neither `[VERIFIED, D §6]`.

**Chain, end to end:** a store with no writer → a record 37 hours stale → the number six live
decisions cite as their evidence → the sentence the operator reads. **The missing writer is not a
theoretical gap.**

## 4.4 A production daemon has a frozen `CURRENT`

Stated in full as **§2, the P0 item.** Summarised here only so the seven read as a set:
`health_agent_daemon_current.py` calls `.resolve()` once at start; PID 3637980 started 2026-08-26
20:38:03 and has held release `40360117` across five days and 166 subsequent builds, running stale
auto-remediation code, logging 20 MB into an orphaned tree, reporting 16,356 × `rc=127` and 19
unfixed escalations where nobody reads. It is stale **because** it has been healthy.

## 4.5 Three `AGENTS.md` §13.4 entries are stale — each needs an amendment PR, queued, NOT opened

Three standing entries in the repository's own operating standard were falsified or halved tonight.
**Per §0 rule 10 the finding wins; per §20 each requires an amendment PR; per this wave's hard pin
none was opened, because opening a PR is a remote action.**

| §13.4 entry | states | measured tonight | worker |
|---|---|---|---|
| `load-by-subject` | *"built, tested, no scheduled wake consumes it… persistence is unwired"* | **Partly false.** A scheduled wake *does* consume the pre-claim consult, 340 times as of 23:38. **But #810's own `decide_after_load` contract remains dark** — so the entry is wrong about the consult and right about the PR, for the wrong reason. | A + C |
| `OUTCOME` edge | *"checkpoints exist; settlement is dark"* | **False.** **158 RESOLVED**, 402 resolution rows across 08-27/29/30/31, most recent `2026-08-31T14:20:02Z`, written by an **hourly `--apply` resolver** (crontab line 964) proven by its own durable log. 152 travelled `SCHEDULED→OUTCOME_PENDING_DATA→RESOLVED`. | B |
| Telegram gate (§13.4/§7) | *"does not gate the family that reaches the operator"* | **One day stale.** True until commit **C4** (dated in-code 2026-08-31) moved `_interdicted()` to `deliver_text`, the lowest common layer. It now **does** gate the CIO family — but still does not gate **46 chokepoint bypasses**, so the entry is half-right and must be amended rather than deleted. | C |

**The `load-by-subject` row is the subtle one and must not be amended carelessly.** A naive
amendment reading "the contract is now live" would be *more* wrong than the current stale entry,
because #810's actual contract is dark (4.2). The amendment must split the two consults.

## 4.6 Node movement since 2026-08-30 — four advanced, four regressed, and three regressions share one shape

Worker C, `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §1.1.

**Advanced (4):**
- `OUTCOME` edge `✗ → ▓` — corroborates B independently, by a different method.
- `LESSON` `▓` — the first **outcome-derived** lesson exists, **n = 1 of 345**. The AS-IS sentence
  *"the system learns from what it read, not what happened"* is now false **by exactly one**. "Never
  fired" and "fired once" are different states, and only one of them proves the edge exists.
- `SpecialistArtifact@v1-lite` `░ → ▓` — the formal type exists; the N=100 gate still fails and
  **instrument bind regressed 64% → 59%**. An advance and a regression in one node, recorded as both.
- `MODEL_CALL_RECORDED` phantom receipt **stopped** 2026-08-28.

**Regressed (4):**
- `CIOCouncilSynthesis@v1` `█ → ░` — one artifact, five days stale, `DISPUTED` count 0, **sole caller
  not in crontab**.
- `NOTIFICATION POLICY` IMMEDIATE and COMMAND_CENTER_ONLY `█ → ✗` — **zero all-time across 2,046
  scanner wakes.** Only SUPPRESSED (4,611) and DIGEST (38) have ever fired.
- `DeliveryReceipt@v1` `█ → ░` — **n = 1, and that single row is `would_send: false`. 114 real
  deliveries produced zero receipts.**
- `OPERATOR turn / S0` `▓ → ✗` — **zero `operator_turns` on any record** (independently re-verified
  by this worker, §3/M3); turn store absent in every root.

**C's synthesis, and the reason this is a headline rather than a table:** *three of the four
regressions share one shape — a correct, tested module whose only caller is a report script not in
crontab.* That is **§3's defect found three more times in one night**, and it is the same shape as
4.2. The system's characteristic failure is not broken code. It is correct code with no scheduled
caller.

The S0 regression compounds 4.1: the record store has no writer **and** no operator turn has ever
landed on it. A and C reached that from opposite directions.

## 4.7 315 store splits measured against 4 claimed — plus a split class no document has a category for

Worker C, §2.3–2.4. `[VERIFIED]`, `find -L` from the served release versus the same relative paths
under the main checkout, as_of 2026-08-31T23:2x ET:

```
REL_files=16979  PROJ_files=25639
BOTH=15916  REL_ONLY=1063  PROJ_ONLY=9723
AGREE=15633  DIVERGE=283
```

**315 divergent files — 283 under `data/`, 32 under `logs/` — plus 10,786 paths present in only one
root.** The AS-IS document claims **four**. The four named are four instances of a systemic
dual-write, **not the population**; one of them (`holdings.json`) is not currently divergent at all.
**266 of the 283 data divergences have no registry contract**, and six registry-declared stores do
not exist under either root.

Cause named in one artifact: `"legacy_read_only": false`, plus **266 PROJ-rooted cron lines against
45 at CURRENT.**

**The fifth class, which no existing document counts:** per-release stranding.

| store | copies across 302 release trees | distinct sha256 |
|---|---|---|
| `data/audit/cio_defer_revisit_last.json` | 254 | 119 |
| `data/audit/cio_material_scan_last.json` | 258 | 232 |
| `data/state/finviz_throttle.json` | **267** | **197** |

**779 copies, 548 distinct**, each frozen at the instant its release stopped being `CURRENT` —
**inode-verified as genuinely separate files**, not aliases (C's correction 7, after correction 6
made doubting them the right instinct). The first two are the durable state of two **CIO systemd
timers**. Every promote hands them a fresh, empty, or months-old last-run file; their dedupe and
cursor state does not survive a deploy, and there were twelve promotes today. **Neither timer can
know this** — reading a missing last-run file is indistinguishable, to them, from a first run.

**Stability caveat, kept rather than smoothed:** three consecutive runs gave `PROJ_files` =
25633 / 25638 / 25639. The system writes during measurement. **315 is a lower bound at a moving
instant**, not a frozen snapshot. Every per-release count in §2.4 is likewise a **floor** — the 302
trees were sampled on four paths, not swept.

**Nothing was picked, merged, reconciled or deleted** (§0 rule 5). Three decisions are put to the
operator in §7.

---

# 5 · The late fact — the consult runs on an empty set, every time

Captured by the coordinator at 23:39 and **independently re-verified by this worker at 23:42 ET**
`[VERIFIED]`, root `CURRENT/logs/cio_wake_dispatcher.log`:

```
2026-08-31 23:12:58  record_consult: wakes=0 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=0
2026-08-31 23:18:09  record_consult: wakes=3 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=3
2026-08-31 23:23:15  record_consult: wakes=2 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=2
2026-08-31 23:28:09  record_consult: wakes=0 …  no_subject=0
2026-08-31 23:33:17  record_consult: wakes=0 …  no_subject=0
2026-08-31 23:38:07  record_consult: wakes=0 …  no_subject=0
```

**Five wakes fired between 23:12 and 23:38. Every one had `subject_resolved=0` with `no_subject=N`.**
The five, by id `[VERIFIED]`:

```
23:16:00  DISPATCH=[wake_ev_morgan_355b491ea8fdf0fc_2026090103,
                    wake_ev_steph_355b491ea8fdf0fc_2026090103,
                    wake_ev_alex_355b491ea8fdf0fc_2026090103]     → all COMPLETED 23:18
23:21:08  DISPATCH=[wake_goal_goal_f2664540d8c1_2026090103,
                    wake_goal_goal_695a5dbe2401_2026090103]        → both COMPLETED 23:23
```

**The consult runs, on an empty set, every time.** `cio_wake_subject.decide` returns at `:163`
before ever reaching `store.load(key)` at `:168` — so the counters increment without a record ever
being read.

**Why this is a finding about the instrument, not about the workers.** Both A and C independently
nearly mis-scored `load-by-subject` because of this line. C recorded it as its correction 2 — the
telemetry *"reads, at a glance, as an unattended fire consuming the record"*, and it *"very nearly
cost this audit its central claim."* A's §4 records the structural half: **the `record_consult` line
omits a `no_record` counter**, so a total memory outage and a quiet queue emit **byte-identical
lines**. That is §8's trap *"two states cannot express no input"*, and the fix is a third verdict.

**Two independent workers nearly making the same wrong call from the same line is not two worker
errors. It is one instrument defect with a 100% hit rate on the auditors who read it.** An
instrument that misleads everyone who looks at it is more dangerous than one that is obviously
broken.

Partly mitigated empirically — `subject_resolved == record_found` exactly (524 = 524) across the
whole history, so `NO_RECORD` has never fired — but the instrument **structurally cannot** express
the distinction, and the empirical mitigation is not a guarantee.

**Contrast, exactly 24 hours earlier**, quoted in full under §3/M5: the same three `wake_ev_*` ids
fired on 2026-08-30 at 23:57 and produced three `skipped by record` lines reading *"The disposition
was recorded earlier and nobody replayed it."* **The system said M5's own sentence a day ago and
cannot say it tonight**, because the deferral it honoured expired at 14:58 UTC and nothing exists to
write another (4.1).

**A live count moves.** `record_consult` totals read 335 (A, 23:22), 337 (coordinator, 23:23) and
**340** (this worker, 23:42) `[VERIFIED]`. These are not discrepancies; the log is live and the
`*/5` timer fires during measurement. Quoted so a later reader does not treat the drift as an error.

---

# 6 · Corrections — mandatory, prominent, and the best evidence of method in this packet

**AGENTS.md §14: keep the corrections in.** *"A write-up that shows what it got wrong is more useful
than one that reads clean."*

This wave corrected itself **eleven times**, in every direction available to it: the coordinator
corrected workers; workers corrected the coordinator's briefs; workers corrected themselves;
a worker's correction of the coordinator was itself wrong and was withdrawn; and the coordinator
audited its own log and found it defective. **These are presented as evidence of method, not as
apology.** A wave that corrected itself eleven times measured eleven things it would otherwise have
published wrong.

**Two of the eleven (6.10, 6.11) are defects in this closeout's own §1** — the section written to
stop a reader quoting a bad commit count contained a wrong number and an unverified ratio. They were
caught by the coordinator and by a re-derivation prompted by it, **after** the file was first
written and synced. They are placed last not because they matter least but because they are the
newest; a reader weighing this packet's reliability should read them first.

## 6.1 The coordinator's false Labor Day premise

Stitch 0 and Worker A's dispatch brief both asserted 2026-09-01 was Labor Day, a US market holiday.

```
$ date -d 2026-09-01 +%A
Tuesday
$ date -d 2026-09-07 +%A
Monday        # Labor Day 2026 is the first Monday of September: 2026-09-07
```

**Why it is kept rather than edited out is what matters:** it handed Worker A a ready-made excuse. A
night of zero CIO wakes could have been written off as *"a holiday eve with no events"* and closed
as benign. It is an ordinary overnight into an ordinary Tuesday session, so **if wake volume were
zero all night the reason would be either real or UNKNOWN — no longer explainable by the calendar.**
The correction made A's required diagnosis harder and considerably more valuable, and A went on to
find a *third* category neither the brief nor the correction anticipated (§3/M5).

**A false premise that would have licensed a comfortable conclusion is the most expensive kind of
error a brief can carry.**

## 6.2 The coordinator's false `plan_id` premise in Worker B's brief

The brief asserted *"a checkpoint bound to nothing cannot settle."* **Worker B measured it instead
of inheriting it, and it is wrong:** `[VERIFIED, B §7]` **0 of 1,125 checkpoints carry a real
`plan_id`, and all 158 settled anyway.** Settlement keys on `decision_id` +
`original_decision_state.symbol`.

The coordinator wrote a premise into a brief and the worker refused to defend it. That is §4 and
§0 rule 10 working exactly as designed, and it is the reason
`docs/briefs/README.md` forbids putting readings into briefs at all.

B refuted **four** brief/authority claims in total: this one; *"337 lessons, ALL research-fed"*
(actually **344 distinct, 343 research-derived, 1 outcome-derived** — "never fired" and "fired once"
are different states); the store-root trap (**tested, then falsified** for
`outcome_checkpoints.jsonl`, which resolves via `production_state_root()`, **and confirmed** for
`CIOPlanStore`, where the same dry command in the same minute returned **43 from the served root and
0 from `$PROJ`**); and the AS-IS claim that the outcome edge is dark.

**B also found the thing its brief never asked about, which is the most important thing it found:**
**871 of 875 SCHEDULED checkpoints have `due_at: null`** — set unconditionally at
`cio_institutional_learning.py:606`, and `due_checkpoints()` treats null as *not due*. **Roughly
three-quarters of the store is structurally invisible to the resolver, forever.**

## 6.3 Worker D's §13.5 mis-citation, and its withdrawal

D reported: *"Provenance classes are §13.5 (`AGENTS.md:785-793`), not §13.4."* **The line numbers
were right; the attribution was not.**

```
$ grep -n "^## 13\.\|^### Provenance" AGENTS.md
689:## 13.4 · The type vocabulary — what already exists
785:### Provenance classes — every operator-facing field carries one
834:## 13.5 · Pre-build check
```

785 falls between 689 and 834, so *"### Provenance classes"* is a **subsection of §13.4** and the
original brief's citation was correct. D reverted at five sites (546, 566, 576, 579, 1096) after
re-running the grep itself, and **struck through and marked the two correction entries WITHDRAWN
rather than deleting them** — so a reader who saw the wrong claim can find out what happened to it.

**The mechanism is worth more than the error:** D resolved the nearest enclosing `###` and treated
it as a peer of the `##` sections. **A line range alone cannot distinguish a subsection from a
sibling.** That is a reproducible way to mis-cite this specific file and it is now written down.

D named why it stings, and D is right: *it landed in a section whose whole purpose was correcting
someone else, and a confident correction is exactly the claim that gets re-used without
re-checking.* **§11's "the finding wins" is not a licence to skip verifying the finding.** This is
the multi-agent protocol tested in the direction it usually is not — the finding lost, because it
did not survive re-measurement.

## 6.4 The coordinator's stitch log mis-stamped its own headers

Every stitch header carried a **hand-estimated** time rather than a measured one. Checked against
`git log`, which is authoritative:

```
dddfd7cb6  23:14  stitch 0        claimed 23:12
3ffef60d5  23:18  stitch 1        claimed 23:22   ← 4 min AFTER its own commit
b8832f8c8  23:26  stitch 2        claimed 23:26   ok
158f6d6dc  23:31  stitch 3        claimed 23:34   ← 3 min after
340525e4f  23:33  stitch 4        claimed 23:38   ← 5 min after
afa8dd212  23:35  stitch 5        claimed 23:45   ← 10 min after
```

**Four of six headers claimed a time later than the commit that contains them — physically
impossible.** The drift grew monotonically, which is the signature of estimating forward from the
last estimate instead of reading the clock.

**This is the wave's own standard turned on the wave.** §4 requires every measurement to carry
value + `as_of` + root; §14 says a document with no trustworthy `as_of` cannot be compared to a
later one. The coordinator spent the night enforcing that on four workers — correcting D's citation,
correcting A's holiday premise, re-measuring every headline count — **while its own document
invented its timestamps.** A coordinator that only audits downward is an incomplete instrument.

Scope, stated precisely: nothing downstream depended on these values. No verdict, count, hash or pin
was derived from a stitch header, and every measurement *inside* the stitches carries its own
separately-sourced `as_of` and root. **The defect is in the log's self-description, not in its
evidence** — and the next reader has no way to know that without being told.

## 6.5 Worker C's detector-artifact zero, caught by accident

Checking whether stranded release trees were still being written, C ran
`find … -newermt "-90 minutes"` and got **0**. One minute later a direct `ls` on the same six paths
showed mtimes of `23:32:45`. **The relative-time form matched nothing, silently.** Re-run with an
absolute timestamp, the query worked.

**This is §3's "positive-control before publishing a zero", and C had not done one.** C then did the
honest thing and generalised it against its own document: *every zero elsewhere in this document
should be read with that in mind*, and its "cannot see" section names which zeros remain
unvalidated. C's blunt statement stands: **no positive control was injected anywhere**, because
every available positive control writes durable state, sends to an operator surface, or spends
money — all pinned. **The zeros in that document are unvalidated detectors, and that is the honest
state of the evidence.**

## 6.6 C's six stranded writes collapsed to one write seen through six aliases

Six August-05 release directories appeared to receive a write simultaneously with `CURRENT`.
`stat -c '%d:%i'` showed **all six on one inode** (`66306:3223608`) with `nlink=1` — impossible for
hardlinks, therefore path aliasing. Their `data/state` is a symlink to the main checkout. **It was
one write to PROJ seen through six paths, not six stranded writes.**

Kept because **the inflated form is the more alarming one and would have been published.** A
surviving mutation that was an invalid mutation — §8, by name.

C then re-ran the *other* per-release counts with `-printf '%D:%i'` and confirmed
`paths=267 DISTINCT_INODES=267` — `find` without `-L` never descended the aliasing symlinks, so the
267/197 figures in 4.7 **stand**. Recorded because correction 6.6 made doubting them reasonable, and
doubting them was the right instinct.

## 6.7 Worker A's initial misattribution of wake volume to the cron quoting bug

A first blamed the crontab 928–930 shell-quoting bug for the wake volume, **was wrong, and recorded
the correction** (its §10.8). The corrected scope, confirmed by the coordinator:

```
$ bash -c 'echo python3 -c "… print(f'"'"'Wakes: {r.get("wakes_created",0)}'"'"')"'
python3 -c from x import y; r=y(); print(f'Wakes: {r.get(wakes_created,0)}')
```

The shell strips the inner double quotes, so `"wakes_created"` becomes a bare name. Confirmed at
rung 1 in the detector's own unattended cron log: `NameError: name 'wakes_created' is not defined`,
×2, last at Aug 31 05:00.

**But the `NameError` is raised evaluating the `print`, which is the third statement on the line.**
`run_cio_event_detector_once()` has already returned. **Wakes are still created; only the telemetry
is lost.** Line 928 is `0 5 * * 1-5`; Tuesday matches, so **it fires again at 05:00 ET and will lose
its telemetry again.** Editing a crontab is a hard pin and operator-only (§17) — recorded, not
touched.

## 6.8 Worker A's storage claim, refined by the coordinator — and strengthened

A reported *"`logs/` is a symlink to shared persistent-state while `data/` is per-release."* Imprecise,
and the correction matters:

```
drwx------  … /data                                    # per-release, real directory
lrwxrwxrwx  … /data/cio -> …/persistent-state/data/cio
lrwxrwxrwx  … /logs     -> …/persistent-state/logs
```

`data/` is per-release, **but `data/cio` is itself a symlink into shared persistent-state.** The
consequence: the 37-hour store silence is **not** an artifact of tonight's 22:55 promote stranding
writes in an old release tree. **The store is genuinely shared and genuinely untouched.** A's
conclusion survives the correction and is strengthened by it.

## 6.9 This worker's own correction — `origin/main` moved during the wave

Stated in full at §1. The brief that commissioned this closeout named `origin/main` as `d276657b7`
and `main..HEAD` as `132`; both were stale by the time this file was written. Re-measured:
`origin/main` is `8c4d109f5`, `main..HEAD` is `136`, and **`origin/main..HEAD` is `10` against both
the old and the new baseline.** Recorded here so this closeout is held to the standard it applies to
everyone else in §6.4.

## 6.10 The coordinator corrected this worker's offset — 126, not 129 — in the section written to prevent exactly this

**This is the most embarrassing correction in the packet and the most instructive, so it is recorded
at full strength.**

§1 originally stated the stale-`main` offset as **129** and built its arithmetic on it. **It is
126.** The coordinator re-measured and caught it. `[VERIFIED]` — every available pair gives 126:

```
136 − 10 = 126        (23:41)
138 − 12 = 126        (23:57)
139 − 13 = 126        (00:02)
```

**There is no measurement that gives 129 as the offset.**

### Where 129 actually came from — a real number, used for the wrong job

129 was not invented. It was the `[VERIFIED]` output of `git log --oneline main..origin/main | wc -l`
at 23:41 — **the staleness of the local `main` ref**, which is a different quantity, and a moving one
(it reads **130** now that `#811` has landed). The error was not a bad measurement. It was **taking a
correctly-measured number and using it to answer a question it does not answer.**

### The tell this worker walked straight past

The original text read:

> `136 = 129 (already on origin/main) + 10 (this wave, actually unpublished) − 3 (see below)`

**That `− 3` is a fudge term.** It exists only because 129 + 10 overshoots 136, and the identity was
forced to balance rather than derived. The correct offset needs no correction term at all —
`136 = 126 + 10`, exactly. **An equation that requires an unexplained remainder to close is telling
you the inputs are wrong, and this worker wrote the remainder in, labelled it "(see below)", and
moved on.** Manufacturing a term to preserve a conclusion is the §14 pattern in miniature, committed
inside the section warning about it.

### Why it matters more here than anywhere else in the packet

§1's entire purpose is to stop a reader quoting a bad commit count. **A wrong number inside the
guard against wrong numbers is the worst place it could have landed** — it is the shape §2's daemon
has (a repair that introduced the defect it was built to prevent) and the shape §4.2 has (the PR
that reproduced the defect it was written to close). **That pattern has now appeared three times
tonight in the system under audit and once in the audit itself.**

### The correction made the section better, which is the argument for keeping corrections

Forced to separate the two quantities, §1 now states both — **offset 126 (constant), staleness 130
(moving)** — and explains that they differ by exactly **4**, those 4 being the commits published
after this branch was cut and never merged in: three of them landing while the wave ran. **The
wave's own duration, measured in other people's merged work.** That is a better explanation than the
original ever contained, and it exists only because the number was wrong.

Recorded per §14 and per the coordinator's instruction that it stay visible. **The coordinator
audited upward and the finding won (§0 rule 10)** — the same direction §6.4 found missing when the
coordinator was auditing only downward.

## 6.11 "Nineteen times too large" was inherited from the brief and never re-derived

Caught by this worker while applying 6.10, and it is the **same class of error one paragraph away**.

§1's original heading and body claimed the misleading number was *"nineteen times too large"* and
that the two baselines *"disagree by a factor of nineteen."* **The word came from the commissioning
brief, which said getting this wrong "would overstate the wave's unpublished work by nineteen
times." It was never checked.** `[VERIFIED]`, the ratio has never been nineteen:

```
136 / 10  = 13.6×     (23:41)
138 / 12  = 11.5×     (23:57)
139 / 13  = 10.7×     (00:02)
```

**Two failures, not one.** First, a number was quoted from a brief rather than regenerated — §16
lists *"a number quoted from a document rather than regenerated"* as not accepted, and
`docs/briefs/README.md` forbids briefs carrying readings **precisely because "numbers embedded in a
brief have been refuted every single time one was embedded."** This is that rule earning its place,
against the very worker that quoted the README approvingly at the top of File 2.

Second, and worse: **the ratio is the wrong statistic entirely.** It is not constant — it falls as
the wave's own commits accumulate, from 13.6× to 10.7× in twenty-one minutes. A reader who quotes
"eleven times" tomorrow will be wrong by tomorrow. **The harm is a constant 126 phantom commits and
must be stated that way.** The heading and body were rewritten to lead with the offset; **no ratio
is quoted as a finding anywhere in this packet.**

Both corrections are the same lesson from opposite ends: **6.10 is a measured number applied to the
wrong question; 6.11 is an unmeasured number inherited from an authority.** Neither survived being
re-derived, and the wave's own standard is that nothing should be published that has not been.

---

# 7 · Operator-only list (§17) — propose and stop

**Every item below is PROPOSED. None was acted on. Nothing was chosen between, merged, collapsed,
enabled, restarted, edited or deleted.**

## Did the list grow or shrink?

**It grew. Sixteen items were added and zero were closed.** §17 says the deferred list should shrink
each wave, and that **if it grows, that is a finding about how the wave was run.** So, plainly:

**The finding is that the wave's own shape determined the direction of the list before a single
measurement was taken.** This was commissioned as a docs-only, read-only census with `git push`,
promote, deploy, cron edits, `--apply`, live sends and model spend all set as hard pins. **A wave
constituted that way is structurally incapable of closing a §17 item and can only add to the list.**
That is not a defect in the workers' execution; it is a property of the instrument, and it is the
same class of error §5 describes — an instrument that can only return one answer.

**The distinction that makes this an honest reading rather than an excuse:** every one of the
sixteen was **DISCOVERED, not CREATED.**

| | count |
|---|---|
| Items this wave **created** (new deferred decisions caused by work done tonight) | **0** |
| Items this wave **discovered** (pre-existing conditions surfaced by measurement) | **16** |
| Items this wave **closed** | **0** |

Every item traces to a condition that existed before 23:12 ET: a five-day-old daemon, a store
unwritten since 2026-08-30, splits accumulated across 302 releases, a cron bug that has fired every
weekday, surface disagreements a code comment dates to 2026-08-29. **The wave wrote no code, changed
no configuration, and created no new decision for the operator to make.** It found sixteen that were
already waiting.

**The load-bearing consequence, and the recommendation this closeout makes:** a census wave that
grows the list is doing its job, but **a programme of consecutive census waves will grow the list
without bound.** The next wave should be constituted with the authority to *close* items —
specifically the reversible ones. §17's own final paragraph is explicit that the escalate-never-
resolve rule *"does not cover labeling, error strings, routing defaults whose conservative option is
reversible, or additive monitoring."* **By that test, several items below are not genuinely
operator-only and are marked accordingly** — they are listed here for visibility, not because an
agent may not do them.

## The sixteen — with the flag that makes each one operator-only

**P0**

| # | item | why §17 | source |
|---|---|---|---|
| 1 | **Restart `tradeai-health-agent.service`** to unfreeze `CURRENT` | restarting a production daemon; not docs-only | §2 · C §2.4d |
| 2 | **Durable fix** for the frozen root — (a) per-cycle re-resolve in the wrapper, or (b) a post-promote restart hook. **Do not choose; (a) may be insufficient because `WorkingDirectory=` is also frozen** | (b) is a new scheduled/hook entry — §17 and §9.3 | §2 |

**Stores and divergent copies — §0 rule 5 territory, where a machine choosing can destroy**

| # | item | why §17 | source |
|---|---|---|---|
| 3 | **The holdings pair.** Currently byte-identical across PSTATE and PROJ. **Trap: it agrees *today*, so a collapse looks free — but both roots are actively written by different cron lines and will diverge on any day the writers disagree.** The safe framing is not "which copy wins" but "which of the 266 PROJ-rooted cron lines should be re-rooted" | §17 names *"collapsing the two holdings copies"* explicitly | C §2.7 |
| 4 | **Flip `"legacy_read_only": false` → `true`** — the single change that would stop 315 divergences from growing | deploy-protocol change | C §2.7 |
| 5 | **Symlink `data/audit` and `data/state` into PSTATE** as `data/cio` already is — would fix two CIO timers' state loss. **Doing it would silently merge 779 divergent copies into one**, which is exactly the destructive act rule 5 forbids an agent from choosing | §0 rule 5 | C §2.7 · 4.7 |
| 6 | **Two divergent copies of `advisory_kb_lessons.jsonl`** — paths, sizes, hashes, mtimes reported; nothing picked | merging divergent copies of an authoritative store | B §1 |
| 7 | **Six copies of `outcome_checkpoints.jsonl`;** the `$PROJ` copy is a strict subset (153/153 upstream, 0 unique). Whether to archive the stale checkout copy | same | B §1 |

**Scheduled entries — §9.3: installing, editing or removing a scheduler entry is operator-only**

| # | item | why §17 | source |
|---|---|---|---|
| 8 | **crontab 928–930 shell-quoting bug.** Fires `0 5 * * 1-5`; Tuesday matches, so it fires at 05:00 ET and loses its telemetry again. **Wakes are unaffected — only the printout is lost** | editing a crontab entry | A §6 · 6.7 |
| 9 | **Arm the `OUTCOME_EXPIRED` path** (`--apply-pending-data` + `TRADEAI_PENDING_DATA_APPLY=1`). **A state that exists in code and has never occurred** | changes a scheduled job's behaviour | B §7 · DRY §7 |
| 10 | **Give `due_at` to the 871 structurally-invisible SCHEDULED checkpoints** — decides what the hourly resolver acts on | changes what settles; store + schedule | B §0 |

**Operator surfaces — §17: changing what is ranked onto an operator surface**

| # | item | why §17 | source |
|---|---|---|---|
| 11 | **P2 — disclose the earmark clamp.** `$395,338.80` of earmark is currently invisible; `cash_free_unearmarked_usd = 0.00` is **forced by the clamp, not measured** | changes what an operator reads on a ranked surface | D P2 |
| 12 | **P4 — choose the canonical producer for total cash.** Which of `portfolio_totals.total_cash`, the row sum, or the `SLEEVE:CASH` record is authoritative. **Do not "fix" the $0.68 by writing to `holdings.json`** | schema + store question determining a ranked surface | D P4 · §3/M4 |
| 13 | **P5 — rename `as_of` → `composition_as_of`** on seven blocks / 543 fields. **The additive half is safe; the rename is not** | schema change on a ranked surface, sequenced migration | D P5 |
| 14 | **P7 — reclassify `case_summaries` from `A` to `T`.** **If `A` was deliberately reserved for a future `AgentView@v1` producer, this diff erases an intentional marker.** The AS-IS "zero class-A" claim suggests it was not deliberate — *but that is inference, not evidence* | architect's call; **ask** | D P7 |

**Live-exercise pins — cannot be proven without crossing a rail**

| # | item | why §17 | source |
|---|---|---|---|
| 15 | **Positive-control the Telegram send gate.** `_interdicted_result()` **writes no log line — it is silent by construction**, so the gate cannot be observed firing by any means short of a live send. **Gate status: ENABLED, not interdicted**, proven at rung 1 by an unattended systemd fire at 20:22:02 ET | requires a live Telegram send | C §4.6 |
| 16 | **`--apply` catalyst rebuild** | `--apply` is a hard pin | C |

## Items deliberately NOT on this list — because §17 says they are not operator-only

§17's final paragraph excludes *"labeling, error strings, routing defaults whose conservative option
is reversible, or additive monitoring."* These four qualify and an agent may do them with ordinary
review:

- **A third `no_record` verdict on the `record_consult` telemetry line** (§5) — additive monitoring,
  and the single highest-value small change in the packet.
- **Fix `entrypoint.py:168-171`**, which hard-codes `"unattended": True` and the cron string as
  literals so a hand-run writes them identically. **That artifact is worthless as M5 proof — it
  cannot go red where it runs** (§16). Additive honesty, no behaviour change.
- **D's P1** — invert `cash_letter` precedence at `cio_record_narrative.py:103-105`. Single
  read-site flip; reads the record, never writes it.
- **D's P4 parity assertion only** (not the convergence) — surfaces the gap rather than resolving it.

## Pre-existing deferred items this wave bears on but did not close

- **`G-NOTIFY-01`** (register, `DEFERRED_OPS`, explicit *no notify-on*) — C's finding that
  NOTIFICATION POLICY IMMEDIATE and COMMAND_CENTER_ONLY are **zero all-time across 2,046 scanner
  wakes** is new evidence for it. Not closed.
- **`G-LOOP-01`** (`PARTIAL`, lineage completion) — untouched.
- **`G-IR-01`** (`CLOSED (mitigated)`) — **contradicted** by 4.1. Flagged for morning; the register
  was not edited.

---

# 8 · Proposed morning diffs — aggregated from all five documents

**PROPOSALS ONLY. Nothing here was committed to any branch, nothing was pushed, nothing was
applied.** All line numbers are from the served release at pin `d276657b7` and **must be re-read
before editing** — the working tree differs and `origin/main` has moved twice (§1).

Flags: **[STORE]** touches a store · **[SCHEMA]** changes a served field's shape or name ·
**[CRON]** touches a scheduled entry · **[SURFACE]** changes what an operator reads on a ranked
surface · **[OP]** operator-only under §17.

Ordered by ratio of operator harm removed to blast radius.

| # | proposal | file:line | flags | source |
|---|---|---|---|---|
| 1 | **Restart the health-agent daemon**, then verify by reading `/proc/<pid>/cwd` — **not** by "service is active" | `tradeai-health-agent.service` | **[OP]** | §2 |
| 2 | **Durable frozen-root fix** — per-cycle re-resolve **or** post-promote hook; note `WorkingDirectory=` is frozen too, so the wrapper fix alone may not suffice | `/home/johnclaw/.config/tradeai/bin/health_agent_daemon_current.py:15,28` | **[OP] [CRON]** | §2 |
| 3 | **`cash_letter` must not render a stale stored cash total.** Invert precedence so the live plan wins and the record is fallback; add `cash_usd_source` and `cash_record_drift_usd` so the gap reaches the surface instead of being silently resolved. `what` regenerates automatically at `:112-114`. **Fixes the `630784.82` on the operator's page**, the internal non-reconciliation, and the false `cash_source: "position_rows"` | `scripts/lib/cio_record_narrative.py:103-105` | — (reads the record, **never writes it**) | D P1 |
| 4 | **Add a `no_record` third verdict** to the `record_consult` telemetry line, so a memory outage and a quiet queue stop emitting byte-identical lines | `cio_wake_dispatcher.py` telemetry | — additive monitoring | A §4 · §5 |
| 5 | **Stop hard-coding `"unattended": True`** and the cron string as literals — the artifact cannot go red where it runs, so it is worthless as M5 proof (§16) | `entrypoint.py:168-171` | — | A §4 |
| 6 | **Give `/api/v2/overview` a cash block with its own `as_of`** by calling the already-correct `cash_evidence_as_of()`. **Fixes the 26-day understatement — the single largest freshness error found** | `scripts/api_v2.py:2606-2610`; reuses `cio_capital_plan.py:841-890` | **[SURFACE]** additive; endpoint is latency-sensitive (80 ms) | D P3 |
| 7 | **Disclose the earmark clamp** — widen the `sources` projection to carry `maturities_capped_to_cash` and `maturities_raw_usd` (both already computed at `:409-410`, carried at `:751`, then dropped by the renderer) and make the label conditional | `/api/v3/cio/home` `capital_plan.sources` projection | **[SURFACE] [OP]** | D P2 |
| 8 | **`cash_parity` assertion** — surface the three values and the `$0.68` gap rather than resolving it, in the shape `consistency.decision_field_parity` already uses. **The assertion is safe and additive; the convergence is not an agent's call** | `/api/v3/cio/home` | **[SURFACE]** additive / **[OP] [STORE] [SCHEMA]** for the convergence half | D P4 |
| 9 | **`block_as_of` should cover every top-level block**, `null` where unknown — converts ~597 silent root-inheritors into an explicit auditable table **without touching any producer** | `/api/v3/cio/home` renderer | **[SURFACE]** additive | D P6 |
| 10 | **Stop stamping composition clocks as `as_of`** across 7 blocks / 543 fields. Ship `composition_as_of` additively first, migrate readers, **then** change `as_of`. Where no evidence clock exists emit `"as_of": null, "unstamped": true` — *"a visible absence rather than a false freshness"* | 7 blocks incl. `report`, `evidence`, `strategy_context`, `seasonality` | **[SCHEMA] [SURFACE] [OP]** on the rename half | D P5 |
| 11 | **Provenance class coverage** — block-level `class` on every top-level block as the tractable first step. **`/api/v2/overview` currently has nothing** | both surfaces | **[SCHEMA] [SURFACE]** additive; sequence after 9/10 | D P8 |
| 12 | **Reclassify `case_summaries` `A` → `T`** — two hardcoded literals; update `provenance_footer.classes` to match | `cio_investment_product.py:917,963`; `cio_operator_product.py` | **[SURFACE] [OP]** — **ask the architect first** | D P7 |
| 13 | **Fix the crontab 928–930 shell quoting** so the detector's telemetry survives | crontab lines 928–930 | **[CRON] [OP]** | A §6 |
| 14 | **Wire a production writer for `InstrumentRecord`** — the root cause behind M1, M2, M3 and M5. **No specific diff is proposed**: which process should mint dispositions, and on what cadence, is a design question this wave did not answer and should not guess at | `persist_instrument_record` (`lib/instrument_record.py:116`, zero callers) | **[STORE]** — **design decision, not a diff** | 4.1 |
| 15 | **Resolve the `cio_specialist_artifact` / `cio_specialist_artifact**s**` name collision** — `cio_run_worker.py:33` imports the plural; the `stamp_last_artifact_id` call lives in the singular. **Note: fixing the import alone does not fix anything** — the stamp writes `last_artifact_id` only and cannot set `next_eligible_at`, so it could never create a deferral | `scripts/lib/cio_run_worker.py:33` | **[STORE]** | C §3 · 4.1 |
| 16 | **Make `telegram_transport._interdicted_result()` log a line.** It is silent by construction, so the gate can never be observed firing without a live send | `scripts/telegram_transport.py:110` | — observability only | C §4.6 |
| 17 | **Delete or date-stamp the stale policy comment** at `api_v2.py:2593-2601`, which asserts these totals agreed *"to the cent, gap 0.00"* on 2026-08-29. **Measured tonight the gap is `$0.68`** — a policy comment that outlived its policy, §3 by name | `scripts/api_v2.py:2593-2601` | — comment only | D §6 |
| 18 | **Investigate the 6,875 swallowed `Action write failed … 'stream_id'` errors** — a `KeyError` in `cio_run_worker`, logged and discarded, **first 2026-08-27 19:16, last 2026-08-31 23:23, still firing.** An alarm that fires constantly and changes nothing | `cio_run_worker` | — investigation | stitch 3 |
| 19 | **Investigate `/api/v3/cio/brain/capital-plan`**, which returns a **fourth** cash presentation with `investable_cash_usd` and `reserved_cash_usd` as `null` where `/home` states them as known. **Named by D as the first place to look next; deliberately left for morning** | `/api/v3/cio/brain/capital-plan` | — investigation | D §9 |

**Explicitly NOT proposed, by any worker:**

- **Nothing that writes to `holdings.json`, `cio_instrument_records.jsonl`, or any store.** The
  `$0.68` and the `$5.60` are **evidence, not bugs to be normalized away** — normalizing them
  destroys the evidence that a writer stopped writing.
- Nothing touching `place_order`, broker paths, 2FA, order routes, or `BehaviorWriteRefused`.
  **HARD PIN, not approached.**
- No change to notification delivery, dedupe, or any scheduled job's existence.
- **No new `@v1` type.** Every proposal reuses an existing field, type, or shape.
- No mass-expiry of drafts, no deletion of anything, no choosing between divergent store copies.

---

# 9 · Morning amendment queue — PRs to open, none opened tonight

**Opening a PR is a remote action. This wave does not push. All seven are queued.**

1. **§13.4 `load-by-subject`** — must **split the two consults**; a naive "now live" amendment would
   be *more* wrong than the current stale entry (4.2, 4.5).
2. **§13.4 `OUTCOME` edge** — 158 RESOLVED, hourly `--apply` resolver, not dark (4.5).
3. **§13.4 / §7 Telegram gate** — one day stale; now gates the CIO family, still does not gate 46
   chokepoint bypasses (4.5).
4. **AS-IS doc: *"Agent-originated fields reaching any operator surface: zero"*** — it is **22**, and
   **mislabelled**, which is worse. `class: "A"` is a hardcoded literal at
   `cio_investment_product.py:917,963` labelling a pure f-string copied out of a stored record.
   **A mislabelled A is worse than an absent one** — a zero is honest about the system's maturity; a
   false A tells the operator the agent formed a view when it recited a template. Counted *by
   producer*, the doc's other sentence — *"every sentence the operator reads is a rule, a threshold,
   a template, or a constant"* — is substantively correct. **Both are true at once.**
5. **AS-IS doc: *"most payload blocks — including every cash number — carry no `as_of` of their
   own"*** — **half wrong, and the half that is right matters.** `/api/v3/cio/home` *does* give cash
   a correct oldest-balance stamp via `cash_evidence_as_of`, which D assessed as a faithful §9.1
   implementation. The claim holds only for `/api/v2/overview`. **This is the difference between
   "nobody implemented this" and "somebody implemented it correctly in one place and it was never
   carried to the other."**
6. **AS-IS doc: *"the system learns from what it read, not what happened"*** — false **by exactly
   one** (n=1 of 345 outcome-derived lessons).
7. **`G-IR-01` in the gap register**, marked `CLOSED (mitigated)` on a stamp path that never fires
   (4.1).

---

# 10 · What stopped, and why — PINs reached

**No worker aborted. Every pin was reached, recognised, and stopped at.** The standing operator
wake-on-abort trigger did not fire, correctly.

| pin | who | what happened |
|---|---|---|
| **Live Telegram send** | C | Positive-controlling the send gate requires a live send. **Proposed and stopped.** Gate status established by other means (an unattended systemd fire at rung 1). |
| **`--apply`** | C | Catalyst rebuild. **Proposed and stopped.** |
| **`--apply`** | B | Nothing expired. `--apply` never passed. Inverse proof of non-writing recorded (DRY §5). |
| **Permission denial** | B | The auto-mode classifier blocked a **no-flag (dry)** run of `resolve_due_checkpoints.py`. **B did not retry, restructure, or route around it** (§0 rule 3). It substituted the hourly cron's own durable log — **a stronger evidence tier than the run it was denied** — and delivered complete work. Assessed against the wake trigger: **not a pin abort.** Waking the operator for a denial absorbed at zero cost would train them to ignore the alarm. |
| **`sudo`** | A | root's crontab — *"sudo: a password is required."* **Not escalated.** UNKNOWN, left standing. |
| **File permission** | coordinator | `/etc/systemd/system/tradeai-continuous.service.d/singleton.conf` unreadable. Its `flock` singleton effect is **inferred from the resolved `ExecStart`, not read from the file.** No sudo, no alternate read path. **A drop-in we cannot read could alter more than we can see, and that is stated as a limit rather than assumed away.** |
| **Production daemon restart** | E | §2's P0. **Diagnosed, not touched.** |
| **`git push` / PR** | all | Seven amendments queued (§9), none opened. |

**Deliberately not interfered with:** the `06:52` `cio_draft_plan_hygiene.py --apply` cron fires at
2026-09-01T06:52 ET. It has run successfully before (854 hygiene events, 124 on 2026-08-31). **The
43 would-expire plans B itemised are what it is likely to act on.** B ran the dry path only and
recorded all 43 with the criterion each tripped.

---

# 11 · Drive sync

## `DRIVE_SYNC=OK`

| | |
|---|---|
| **Folder** | `TradeAI / CIO overnight 2026-09-01` |
| **Folder ID** | `1Ur6VXRgl2HfVwbDTqdGlkPnLS_Q_85nc` |
| **URL** | https://drive.google.com/drive/folders/1Ur6VXRgl2HfVwbDTqdGlkPnLS_Q_85nc |
| **Path used** | `gog` CLI v0.12.0, account `john@jwwhiting.com` |
| **Result** | **uploaded = 11, failed = 0**, verified by read-back |
| **as_of** | 2026-08-31T23:55 ET |

### What was verified, and how — because exit code 0 is not evidence (§0 rule 8)

`[VERIFIED]` The folder was listed back from Drive after the uploads, and **every byte count matches
the local file exactly**:

```
drive file id                           bytes  name
17AoSM9pS4BaapTHfZAPOpJGQ1cBXPS89       11935  CIO_ASIS_VS_SPEC_2026-08-30.md
1gkutTWRaFdSH5yOscpLoN9l5r39mOiix       76553  CIO_DARK_CONTRACTS_2026-09-01.md
1XhzXmafy5oFJyc9jeJe16klTnvJGUsNB       16952  CIO_FUTURE_STATE_FULL_MATURITY.md
1pXp4Ah8HYSbgxntkXcfg9uxnBA1VZv5U       41439  CIO_M5_TIMER_WATCH_2026-09-01.md
1aK8HpWMRUMa1K7Z7hDGX0hNd0P7Gh__2       26193  CIO_OUTCOME_DRY_2026-09-01.md
12LmVCgmPMSrZ3ppsz55JruOzJpMh-f04       37932  CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md
1dfC_GJuM1L5OvygZ1IsjALi3XRof8TCB       79986  CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md   ← SUPERSEDED: this id no longer exists
1hdMh1S4LDt7H0Nr-aKaGXl1NhBhfbEBL       60795  CIO_OVERNIGHT_STITCH_2026-09-01.md
1oxV_HfY9AJ30cAM8l0j6GX88u1X1wh9C       67871  CIO_SURFACE_ASOF_2026-09-01.md
1busPogLq5IE4-lmNmmCKOBOoo5gZA8TI       17810  PROJECT_THE_DESK_V2.md
1VcxI9e4tBPZ85uRcgIh1cjfEcnklqJfj       13093  WAVE_OVERNIGHT_2026-09-01.md          ← SUPERSEDED: this id no longer exists

FILES IN FOLDER: 11    TOTAL BYTES: 450559
```

**A byte count is not content.** One file was downloaded back out of Drive and compared:

```
$ sha256sum docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md  <drive round-trip>
89415d2bc04cc2ad66b9cf2c4643b2d0377611161755388d78e0de804f592528  (local)
89415d2bc04cc2ad66b9cf2c4643b2d0377611161755388d78e0de804f592528  (downloaded from Drive)
$ diff …  → IDENTICAL
```

Uploaded as raw Markdown — **no Google-Docs conversion** — so the round-trip is byte-exact and the
evidence blocks, code fences and tables survive verbatim. Conversion would have made this check
impossible.

### Two corrections to the sync instruction, recorded rather than absorbed

**1 · The set is eleven files, not nine.** The commissioning brief said *"this wave's six documents
plus the three architecture reference docs"* and instructed that a failure list *"all nine files."*
Six + three = nine **omits this closeout and the wave brief** — the two documents the packet exists
to deliver. A morning packet without its own closeout is not a packet. **Eleven were synced**, and
the discrepancy is named here rather than silently resolved.

**2 · The folder name was ambiguous and was resolved literally.** *"TradeAI / CIO overnight
2026-09-01"* can be read as a path (parent `TradeAI` → child `CIO overnight 2026-09-01`) or as one
literal name. `[VERIFIED]` **no folder named `TradeAI` exists at the Drive root** — the nearest
siblings are `TradeAI CIO Ops` and `TradeAI_Governance_c3e98d4d_2026-08-30`, neither of which uses a
slash convention. The name was therefore created **verbatim as quoted**, at the root, as a **new**
folder. **No existing folder was modified, moved, renamed or written into.** If the intent was
nesting under `TradeAI CIO Ops`, moving it is a one-step operator action; nothing needs re-uploading.

### What was NOT synced

**No `.env`, no keys, no credentials, no `holdings.json`.** All eleven files are Markdown documents
under `docs/`. `[VERIFIED]` before upload: a filename check for `.env` / `key` / `credential` /
`holdings.json` returned nothing, and a content scan for private-key headers, API-key patterns,
`sk-` tokens, Telegram bot tokens and AWS access keys across all eleven returned **no matches**
(rc=1).

### The hourly sync did NOT carry this wave, and its success must not be read as this wave's

`[VERIFIED]` The `5 * * * *` Drive sync ran clean at 23:05 ET with `uploaded: 32`. **That was other
content.** It reads `SRC=…/portfolio-server/CURRENT` — the served release. **Tonight's documents live
on an unpushed branch in a worktree that is never promoted, so that job cannot and will not carry a
single file from this wave.** `scripts/sync-docs-to-drive.sh` was **read, not run**: it syncs the
whole docs tree from `CURRENT` and mutates shared manifest state (`drive-sync-manifest.txt`,
`drive-sync-ids.txt`, `drive-sync-last-result.json`), none of which was touched. The uploads above
were made directly to the new folder and **wrote nothing to that shared state.**

`rclone` was ruled out and is confirmed not the path: installed at `/home/johnclaw/.local/bin/rclone`
with **no remotes configured** (`rclone listremotes` → empty, rc=0).

### The two files that supersede their uploaded copies

This closeout and the wave brief were uploaded, then edited — first to contain this very section,
then again to add §1.1 — and **re-uploaded each time, the superseded Drive copy being removed before
each replacement.** The read-back table above is the **first-upload** snapshot. It is kept unedited
because it is what proved the byte-exact round trip, but **the two file ids it shows for this
closeout and the wave brief are dead**, and the two byte counts beside them are two revisions old.
The other nine rows are unchanged and current.

**Final read-back**, `[VERIFIED]` after the last re-upload, as_of 2026-09-01T00:00 ET:
**11 files in the folder, all eleven byte-matched against their local originals, zero duplicates.**
This closeout's own byte count is deliberately not quoted here — a document that states its own size
invalidates the statement by making it.

**A note on `delete`, because §0 rule 6 says never delete.** The two removed objects were Drive
copies **this worker had uploaded minutes earlier in this same session**, superseded by a newer
revision of the identical file, with the authoritative original intact in the repository. That is
replacing a mirror artifact, not deleting a record. **Nothing pre-existing was removed**, and no
local file, store or log was touched.

### The nine — sorry, eleven — local paths, recorded regardless of sync status

Per the brief's own instruction, these are listed whether the sync succeeded or failed. Worktree root
is `/home/johnclaw/tradeai-wt-final-operator-convergence`. **These paths are on an unpushed branch;
`git fetch` will not produce them.**

```
docs/ops/CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md          (E — this file)
docs/briefs/WAVE_OVERNIGHT_2026-09-01.md               (E)
docs/ops/CIO_OVERNIGHT_STITCH_2026-09-01.md            (coordinator)
docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md              (A)
docs/audits/CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md      (B)
docs/ops/CIO_OUTCOME_DRY_2026-09-01.md                 (B)
docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md           (C)
docs/audits/CIO_SURFACE_ASOF_2026-09-01.md             (D)
docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md       (reference)
docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md    (reference)
docs/architecture/PROJECT_THE_DESK_V2.md               (reference)
```

---

# 12 · What this closeout structurally cannot see

Stated so the gaps are not mistaken for negatives (§14: *do not invent a reason; UNKNOWN is
legitimate and its count is a measurement*).

1. **This closeout re-verified roughly a dozen headline claims and inherited the rest.** Every claim
   tagged `[VERIFIED]` *by this worker* was re-run here with its output quoted. Claims attributed to
   A, B, C or D carry their tag and their document, and were **not** independently re-measured
   unless the text says so. **A reader should treat the workers' documents as the primary evidence
   and this file as an index with spot-checks.**
2. **Only pin `d276657b7` was observed at runtime, for roughly one hour.** Anything said about
   runtime behaviour rests on that window. **`origin/main` is two commits ahead of the served pin**
   (§1) and nothing here covers `db115caec` or `8c4d109f5` — including `#715`, whose title names M3.
3. **Shared, rotation-spanning logs.** `CURRENT/logs` is a symlink into `persistent-state/logs`, so
   log evidence cannot be attributed to a pin without a timestamp cut. C applied that cut and warns
   that other documents in this programme may not have. **This one relies on C's cut where it quotes
   C.**
4. **Logs written into abandoned release trees are invisible to a `CURRENT/logs` reader — including
   to most of this packet.** §2 is a 20 MB instance found by accident. C's negative sweeps covered
   four log roots and **did not cover the `logs/` directories of the other 301 release trees.** A
   gate could have fired into one of those and nobody would have seen it. **This is the single
   largest hole in the packet's negative findings.**
5. **No positive control was injected anywhere in this wave.** Every available positive control
   writes durable state, sends to an operator surface, or spends money — all pinned. **The zeros in
   this packet are unvalidated detectors** (6.5). That is a real weakness and it is the honest state
   of the evidence.
6. **The counter-vs-cause ambiguity.** Where a zero is reported, "never started" and "failed on the
   first instruction" are distinguishable only where a second artifact existed. Where they were not,
   the entry says UNKNOWN.
7. **Nothing Postgres-resident was measured.** If a second outcome lane lives in `agent_scores`,
   `trade_lesson_memory`, `kb_lessons` or `paper_trade`, this packet cannot see it, count it, or
   tell whether it contradicts anything here. A direct `ticker_prices` query was **denied by the
   permission layer and not routed around** (B §10).
8. **Semantic correctness was never checked.** 158 checkpoints carry an `outcome_id` that resolves;
   **whether the price comparison behind any of them is right is unmeasured.** No Telegram message
   body was read. Whether the operator received anything *useful* is outside what any of this
   measures.
9. **~106 `D` provenance declarations were not traced to producers and should be treated as
   unverified** — because the one class D *did* audit end to end turned out to be mislabelled. That
   is the right inference from D's own finding, and it is the opposite of the convenient one.
10. **Counts move while being counted.** `record_consult` read 335 / 337 / 340 across three
    measurements in twenty minutes; the checkpoint store grew by three rows in eight minutes; the
    split sweep gave three different `PROJ_files` totals. **Every count in this packet is a
    photograph, not a state**, and several are explicitly floors.
