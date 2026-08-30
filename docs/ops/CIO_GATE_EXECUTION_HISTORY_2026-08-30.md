# CIO Gate Execution History — 2026-08-30

**Agent:** A2, Wave A (CIO validation sweep)
**Question:** *"A gate that has never run is indistinguishable from one that passed."*
For every CI gate, cron job and systemd timer installed or changed in the last two
weeks (since 2026-08-16): when did it last **actually execute**, what durable evidence
did that run leave, and does that run reflect current `main`?

**Posture:** READ_ONLY_ADVISORY, MBI_BEHAVIOR=0. No cron entry or timer was installed,
modified or removed. No promote, merge or deploy. No Telegram, no vendor calls.
Two commands were run by hand and are labelled `[HAND-EXERCISED]`; neither is reported
as a scheduled run.

**Reference points**

| Thing | Value |
| --- | --- |
| `origin/main` | `6bae652966272e065d0f22d5d974d45320c39b43` |
| Live release (`CURRENT`) | `66f97259-main-exact-phase2-20260830-112142`, symlinked 2026-08-30 11:22 |
| Gap | `main` is **1 commit ahead** of the live release |
| That commit | `6bae6529 fix(v0): two scripts could not compile; the census was unrunnable for 10 hours (#705)` |

**Tags:** `[VERIFIED]` = command run, output quoted. `[CODE]` = source read.
`[DOC-CLAIM]` = a document asserts it.

---

## 1. The table

### 1a. CI gates (GitHub Actions)

Scope: the six workflow files changed since 2026-08-16, plus the one new test gate.

| gate/job | scheduler | last actual run | durable evidence | reflects current main? | verdict |
| --- | --- | --- | --- | --- | --- |
| `provider-cost-ci` | GH Actions | 2026-08-30T15:55:19Z | run record, `success` | **yes** — headSha `6bae6529` == `origin/main` | `RUNS_AND_PROVEN` |
| `financial-senses-ci` | GH Actions | 2026-08-30T15:55:19Z | run record, `success` | **yes** — `6bae6529` | `RUNS_AND_PROVEN` |
| `aif-financial-senses-integration-ci` | GH Actions | 2026-08-30T15:55:19Z | run record, `success` | **yes** — `6bae6529` | `RUNS_AND_PROVEN` |
| `release-readiness` | GH Actions | 2026-08-30T15:55:19Z | run record, `success` | **yes** — `6bae6529` | `RUNS_AND_PROVEN` |
| `research-governance` | GH Actions | 2026-08-30T15:55:19Z | run record, `success` | **yes** — `6bae6529` | `RUNS_AND_PROVEN` |
| `cio-production-hardening-ci` | GH Actions | 2026-08-30T15:51:29Z, sha `41b69f22` | run record, `success` | **no** — did not run on `6bae6529` | `STALE_SHA` (benign, see §2.1) |
| `agent-intelligence-foundation-ci` | GH Actions | 2026-08-29T04:42:19Z, sha `e0fd5d2e` (push) | run record, `success` | **no** — 1 day old | `STALE_SHA` |
| `cio-truth-gates-ui-validation` | GH Actions | 2026-08-29T04:03:34Z, sha `55e403af` (PR) | run record, `success` | **effectively yes** — guarded blobs byte-identical on main (§2.2) | `RUNS_AND_PROVEN` (caveat: no `push` trigger) |
| `tests/test_every_script_compiles.py` | — | **never** | **none** | n/a | **`NEVER_RAN`** (§2.3) |

### 1b. Cron jobs

| gate/job | scheduler | last actual run | durable evidence | reflects current main? | verdict |
| --- | --- | --- | --- | --- | --- |
| CIO draft-plan hygiene (`52 6 * * *`) | cron L997 | 2026-08-30 06:52:06 | `/home/johnclaw/logs/cio_draft_hygiene.log` — `would_expire=32 expired=32 apply=True` | ran against the **pre-11:22 release**, not the current one | `RUNS_AND_PROVEN` (first-ever run, §2.4) |
| Docs→Drive sync (`5 * * * *`) | cron L434 | 2026-08-30 12:06:43 | `/home/johnclaw/logs/drive-sync.log` — `sync done: 30 uploaded, 2218 unchanged, 0 failed` | n/a (data sync) | `RUNS_AND_PROVEN` |
| Docs→Drive sync, old `.py` variant | cron L244 — **commented out** | 2026-08-20 21:52 (ended mid-run) | `drive-docs-sync.log`, last line is a `progress:` line, never a `sync done:` | n/a | `NOT_SCHEDULED` (§2.5) |
| PEAK_SKIP gate — 24 wrapped LLM jobs | cron (24 active lines) | wrapped jobs run daily; **gate's skip branch never observed** | **none** — zero `PEAK_SKIP gate=` lines in any log tree | n/a | **`RUNS_NO_EVIDENCE`** (§2.6) |
| `atm_position_reconciler` intraday (`*/15 9-16 * * 1-5`) | cron L378 | **never succeeded** | **none** — no `latest.json` exists anywhere | n/a | **`NEVER_RAN`** (§2.7) |
| `atm_position_reconciler` EOD (`45 16 * * 1-5`) | cron L379 | 2026-08-28 16:45 | `logs/atm_position_reconciliation/eod_20260828.json` | canonical source tree, compiles clean | `RUNS_AND_PROVEN` |

### 1c. systemd timers

| gate/job | scheduler | last actual run | durable evidence | reflects current main? | verdict |
| --- | --- | --- | --- | --- | --- |
| 13 CIO/advisory user timers (delivery, material-scan, defer-revisit, free-first-circulation, due-checkpoints, memory-shadow-measure, desk-memo-regen, nightly-reflection, provider-cost-reconcile, research-lane-health, advisory-shadow-seed, autonomy-watchdog, hermes-cio-worker) | `systemctl --user` | all within last 24 h; most within minutes | journal (persistent) + `Result=success ExecMainStatus=0` for every one | **no** — all execute release `66f97259`, 1 commit behind main | `RUNS_AND_PROVEN` |
| `tradeai-portfolio-backup-cadence` | user timer | timer last fired 2026-08-30 02:30:05; unit file **edited 10:59:44**; service last executed 11:06:52 (not timer-driven) | journal, `Result=success` | current definition has **never been timer-triggered** | `RUNS_NO_EVIDENCE` (§2.8) |
| `hermes-autonomous-loop.timer` | user timer | **never** — `LastTriggerUSec=` empty | **none** | n/a | **`NOT_SCHEDULED`** (§2.9) |
| `at-observation-01.timer` | user timer | **never** — `LastTriggerUSec=` empty | **none** | n/a | **`NEVER_RAN`** (§2.10) |
| `at-observation-01-closeout.timer` | user timer | **never** — `LastTriggerUSec=` empty | **none** | n/a | **`NEVER_RAN`** (§2.10) |
| `tradeai-reprice.timer` | **system** timer | 2026-08-28 15:45:00, `ExecMainStatus=0` | systemd state + journal | n/a | `RUNS_AND_PROVEN` — **but out of scope** (§3.1) |

---

## 2. Findings

### 2.1 `cio-production-hardening-ci` — stale sha, but by design

`[CODE]` The workflow's `push` trigger carries a `paths:` filter (`scripts/lib/cio_*.py`,
`tests/test_cio_*.py`, `docs/investment-office/**`, …). Commit `6bae6529` touched
`scripts/atm_position_reconciler.py`, `scripts/cio_event_lifecycle_census.py` and
`tests/test_every_script_compiles.py` — none of which match. So the gate correctly did
not fire. Its `pull_request` trigger deliberately carries **no** path filter, with an
in-file comment explaining that a filter there would leave the required check Pending
and block merges. `[VERIFIED]` It ran green on `41b69f22` and `66f97259` earlier today.
Not a problem — recorded so nobody "fixes" it.

### 2.2 `cio-truth-gates-ui-validation` — old sha, current content

`[VERIFIED]` Last run 2026-08-29 on `55e403af`, which is an ancestor of `origin/main`
with **149 commits** since. That looks alarming, and the naive read is `STALE_SHA`.
It is not, and the distinction matters:

```
CioHub.tsx blob at 55e403af:   0667a533fcbdd1c69f4ed8c9f25939b3a48b44a2
CioHub.tsx blob at origin/main: 0667a533fcbdd1c69f4ed8c9f25939b3a48b44a2
spec blob at 55e403af:         bde918b01ad592653172d06261c36e49f4f0e87e
spec blob at origin/main:      bde918b01ad592653172d06261c36e49f4f0e87e
```

Both guarded files are byte-identical between the last run and current main. The gate's
last run still describes today's guarded surface.

**The real weakness is structural, not temporal.** `[CODE]` The workflow triggers only on
`pull_request` (+ `workflow_dispatch`). It has **no `push` trigger**, so it never validates
`main` directly — only PR heads. A change reaching main by any route that isn't a
path-matching PR is never checked by this gate.

### 2.3 The compile gate added today has never run — and it guards the break that just happened

This is the sharpest instance of the brief's thesis.

`[VERIFIED]` Commit `6bae6529` (today 11:55) fixed a `SyntaxError` in
`scripts/cio_event_lifecycle_census.py` — a module-level assignment inserted above the
`from __future__` import by commit `aa21559c` at 00:55, leaving the script unrunnable for
ten hours. The same commit added `tests/test_every_script_compiles.py` as the guard
against that class of break.

That guard is wired to nothing:

```
$ grep -rn 'test_every_script_compiles' --include=*.yml --include=*.py --include=*.sh \
    --include=*.cfg --include=*.toml --include=*.ini .
tests/test_every_script_compiles.py:33:def test_every_script_compiles():
tests/test_every_script_compiles.py:70:            continue   # covered by test_every_script_compiles
```

Zero references outside the file itself. `[CODE]` Every workflow invokes pytest with an
explicit, hand-maintained file list — `release-readiness` runs three named scripts and no
pytest at all; `financial-senses-ci`'s "broader regression" is four named files;
`run_cio_hardening_ci.py` carries a hardcoded list. There is no `testpaths` in any pytest
config, and no bare `pytest tests/` anywhere. **Nothing collects it.**

`[HAND-EXERCISED]` Run by hand it passes — `5 passed, 1 warning in 6.70s`. So the gate
works. It has simply never been executed by CI, and on current wiring never will be. The
five green checks on `6bae6529` do not include it.

### 2.4 CIO draft-plan hygiene — real, and today was its first run

`[VERIFIED]` `/home/johnclaw/logs/cio_draft_hygiene.log`, mtime 2026-08-30 06:52:06,
764 bytes, contents `would_expire=32 expired=32 apply=True` plus 32 plan lines. Real work,
not a dry run.

The cron line redirects with `>>` (append), and the file contains **exactly one**
`would_expire` block. Had it run yesterday there would be two. So 2026-08-30 06:52 was its
first-ever execution — the job is three hours older than its own evidence suggests at a
glance, and one run is a thin base for confidence.

Note also that it ran at 06:52, while `CURRENT` was only re-pointed at the present release
at 11:22. Its single run executed a **different, older release** than the one now live.

### 2.5 The Drive-sync trap, inverted

The brief warns that a commented-out crontab line may still run under a timer. Here the
inverse holds, and both halves matter:

- `[VERIFIED]` Cron L244 (`sync-docs-to-drive.py`) is commented out `PAUSED_MASTER_REWRITE`.
  Its log `drive-docs-sync.log` is stale at 2026-08-20 21:52 — and its final line is
  `progress: 50 uploaded, 1167 unchanged`, not a `sync done:` line. The last run of the
  paused job **died partway through 1800 candidates and wrote no completion record and no
  error**. It did not stop cleanly; it stopped silently.
- `[VERIFIED]` Cron L434 is the live one, and it is a **different implementation** —
  `sync-docs-to-drive.sh` (shell, from `CURRENT`), logging to `drive-sync.log`. Fresh at
  2026-08-30 12:06:43, `sync done: 30 uploaded, 2218 unchanged, 0 failed`.

Grepping for the documented `.py` filename finds the dead line and misses the live job.

### 2.6 PEAK_SKIP: 24 jobs wrapped, zero evidence the gate has ever fired

The brief's "~25 LLM jobs wrapped in a PEAK_SKIP gate" is accurate in count —
`[VERIFIED]` 24 active crontab lines call the wrapper (1 more is commented out). But the
string `PEAK_SKIP` **does not appear in the crontab at all**; the jobs call
`~/.config/tradeai/bin/run_with_deepseek_offpeak.sh`. `[VERIFIED]` That file and
`$PROJ/scripts/run_with_deepseek_offpeak.sh` are separate copies with identical content
(md5 `0046dc79af3161b041f715f6572e355c`) — following the name in cron rather than the one
in the repo matters here, even though this time they agree.

`[CODE]` The gate's contract:

```bash
if [[ "$rc" -eq 10 ]]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) PEAK_SKIP gate=${GATE}"
  exit 0
fi
```

**Exit 0 on skip.** A skipped job and a successful job are identical to cron. The only
distinguishing evidence is that log line — and there is none:

- `[VERIFIED]` `grep -rl "PEAK_SKIP gate=" /home/johnclaw/logs/ $PROJ/logs/` → no matches.
- `[VERIFIED]` `grep -rl "run_with_deepseek_offpeak" <both>` → no matches.
- `[VERIFIED]` The only `PEAK_SKIP` text on disk is inside a Cursor editor audit
  transcript (mtime 2026-08-20), i.e. source text being edited, not a run record.

The wrapped jobs themselves are demonstrably running — `hermes_config_governor.log`
11:45, `hermes_outcome_learning.log` 11:35, `hermes_tag_engine.log` 11:09,
`hermes_outcome_grader.log` 10:50, all today, all matching their cron slots. So the gate
is being invoked and always taking the proceed path.

**But it should have taken the skip path.** Two jobs use `--official`, which skips the
official DeepSeek UTC peaks (01:00–04:00 and 06:00–10:00). `[HAND-EXERCISED]` Evaluating
the shipped module against the real run times:

```
date_ET          utc            wd  official_skip?
Mon 08-24 04:00  Mon 08-24 08:00Z  0  True   04:00 atp2
Tue 08-25 23:30  Wed 08-26 03:30Z  2  True   23:30 curation
Thu 08-27 04:00  Thu 08-27 08:00Z  3  True   04:00 atp2
Fri 08-28 04:00  Fri 08-28 08:00Z  4  True   04:00 atp2
Sat 08-29 23:30  Sun 08-30 03:30Z  6  False  23:30 curation   <- weekend, correctly no skip
```

On every weekday from 08-24 to 08-28 the gate says **skip**. `[VERIFIED]` The logs show
both jobs ran to completion on exactly those dates —
`atp2_research_cycle_cron.log` has 226 lines timestamped `2026-08-28 04:00` ending
`[atp2-premarket_4am] Finished`, and `hermes_source_curation.log` has entries for every
day 08-18 → 08-29. Zero `PEAK_SKIP` in either.

`[CODE]` No override explains it: `HERMES_ALLOW_DEEPSEEK_PEAK` appears zero times in the
crontab and zero times in `/run/user/1000/tradeai/env`. `[VERIFIED]` The weekend carve-out
(`weekday() >= 5` → not peak) is real and correctly explains the 08-29 run, but not the
five weekday runs.

The crontab has no history and `/var/spool/cron/crontabs/johnclaw` is unreadable
(`Permission denied`), so **I cannot establish when the `--official` wrapper was added to
those lines.** The most likely explanation is that the wrapping landed after 2026-08-28,
which would mean the gate's skip branch has simply not yet met a peak window — the first
real test is Mon 2026-08-31 04:00 ET. I could not prove that, and I am not asserting it.
What is established: **the skip branch has never been observed to execute in production,
and on the evidence available it is indistinguishable from a gate that always passes.**

`[HAND-EXERCISED]` One latent defect found while exercising the wrapper. It resolves its
interpreter as `PY="${PY:-${TRADEAI_PYTHON:-$ROOT/.venv/bin/python}}"` where `$ROOT` is the
wrapper's own parent — `~/.config/tradeai`. That fallback path does not exist:

```
$ bash ~/.config/tradeai/bin/run_with_deepseek_offpeak.sh --official -- echo PROCEEDED
.../run_with_deepseek_offpeak.sh: line 33: /home/johnclaw/.config/tradeai/.venv/bin/python: No such file or directory
deepseek offpeak gate failed rc=127
```

It works under cron only because the crontab happens to set `PY` at file scope. Any caller
that does not export `PY` — a systemd unit, a manual invocation, a future crontab
rewrite — gets rc=127 and **the wrapped command silently never runs**. With `PY` set it
behaves correctly (`OFFPEAK` / `PROCEEDED` / exit 0). Proposal only, no change made:
default `$ROOT` to the canonical project tree, or fail loudly if the interpreter is absent.

### 2.7 A `cd` that isn't there: the intraday reconciler has never run

Two crontab lines invoke the same script. One works; one never has.

```
L378: */15 9-16 * * 1-5 bash scripts/safe_flock.sh ... --json-out logs/.../latest.json >> logs/.../cron.log 2>&1
L379: 45 16 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && bash scripts/safe_flock.sh ...
```

L379 has `cd $PROJ`. **L378 does not.** Cron starts jobs in `$HOME`, so L378's relative
paths resolve against `/home/johnclaw`:

- `[VERIFIED]` `/home/johnclaw/scripts/safe_flock.sh` — `No such file or directory`.
- `[VERIFIED]` `/home/johnclaw/logs/atm_position_reconciliation/` — does not exist, so even
  the `>>` redirect fails before the command is reached. There is no log to notice.
- `[VERIFIED]` `latest.json`, L378's sole artifact, **does not exist anywhere**.
- `[VERIFIED]` L379's artifacts are all present: `eod_20260828.json`, `eod_20260827.json`,
  `eod_20260826.json`.

L378 is scheduled every 15 minutes across market hours — roughly 32 invocations per
weekday — and has produced nothing, ever. It is a clean paired control: same script, same
schedule file, and the only difference is the missing `cd`. Proposal only: add
`cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild &&` to L378.

### 2.8 A unit edited after its last run

`[VERIFIED]` `tradeai-portfolio-backup-cadence.service` has unit-file mtime
**2026-08-30 10:59:44**, while `LastTriggerUSec=Sun 2026-08-30 02:30:05`. The timer last
fired eight and a half hours *before* the file was edited. `ExecMainStartTimestamp=11:06:52`
with `Result=success` shows the new definition has executed once — but at 11:06, which is
not a timer instant (next elapse is Mon 02:30). That execution was driven by something
other than the timer, presumably whoever made the edit. **The current definition has never
been exercised on its own schedule.** First scheduled proof: Mon 2026-08-31 02:30.

### 2.9 A service maintained as if live, behind a disabled timer

`[VERIFIED]` `hermes-autonomous-loop.timer` is `disabled` and `inactive`, with
`LastTriggerUSec=` empty and no entry in `systemctl --user list-timers --all`. It has
never fired.

What makes this worth flagging is that the unit has been **actively maintained** since:
`hermes-autonomous-loop.timer` mtime 2026-08-18 18:31, `hermes-autonomous-loop.service`
2026-08-23 13:16, and a drop-in directory `hermes-autonomous-loop.service.d` at
2026-08-23 13:31. Three edits across five days to a unit that cannot run. The wrapper
script's own header comment even reassures the reader that it "does not retune
hermes-autonomous-loop.timer" `[CODE]` — a live-sounding reference to a dead timer.

### 2.10 Two timers enabled, active, and permanently incapable of firing

`[VERIFIED]` `at-observation-01.timer` and `at-observation-01-closeout.timer` both report
`UnitFileState=enabled`, `ActiveState=active`, and `LastTriggerUSec=` empty. In
`list-timers` both show `-` for NEXT and `-` for LAST. `[CODE]` The reason:

```ini
[Timer]
OnCalendar=2026-07-27 06:55:00
AccuracySec=1s
Persistent=false
```

A one-shot calendar date **five weeks in the past**, with `Persistent=false` so a missed
occurrence is never made up. They are loaded and enabled and will never fire. Any status
check that asks only "is it enabled and active?" reports these two as healthy.

---

## 3. Where the brief and reality diverge

Per instruction — when a finding contradicts the prompt, the finding wins.

**3.1 `tradeai-reprice.timer` was not installed or changed during this programme.**
The brief lists it among jobs "installed during this programme". `[VERIFIED]` It is a
**system** unit (`/etc/systemd/system/`, not `--user`) with mtime **2026-04-14 16:37**,
alongside `tradeai-reprice.service`. Four and a half months old and untouched. It is
healthy — last ran 2026-08-28 15:45:00, `ExecMainStatus=0`, next Mon 09:00 — but it falls
outside the two-week scope and I have marked it so rather than padding the in-scope list.
It is also the only in-brief job living in the system manager rather than the user one.

**3.2 `PEAK_SKIP` is not a searchable string in the crontab.** Zero occurrences. The gate
is real and covers 24 jobs, but is reachable only via the wrapper filename. Searching for
the concept by name finds nothing and would support a false "not installed" conclusion.

**3.3 The count is 24, not ~25** active wrapped lines (a 25th is commented out) — the
brief's "~25" is fair, recorded for precision.

**3.4 The hourly Drive sync is not the script the brief implies.** The live job runs
`sync-docs-to-drive.sh`; the `.py` of the same name is the paused line (§2.5).

---

## 4. Gates that are, on this evidence, indistinguishable from gates that passed

Ordered by how much confidence they are currently borrowing without earning.

1. **`tests/test_every_script_compiles.py`** — added today specifically to catch the break
   that had just cost ten hours, and collected by no workflow, no runner and no pytest
   config. It has never executed in CI. It passes by hand, which is exactly what makes it
   dangerous: the repo now looks protected against a class of failure it is not protected
   against.
2. **The PEAK_SKIP gate across 24 LLM jobs** — exits 0 when it skips, so a skip is
   invisible to cron, and no `PEAK_SKIP gate=` line has ever been written. On five weekday
   runs where the gate logic (hand-evaluated) says it should have skipped, the jobs ran to
   completion instead. Its skip branch has zero production evidence. Its `PY` fallback
   additionally resolves to a non-existent interpreter, which would silently suppress the
   wrapped command for any caller that does not export `PY`.
3. **`atm_position_reconciler` intraday, cron L378** — scheduled ~32×/weekday since
   installation, has never produced its artifact, and fails before it can write a log, so
   the failure leaves no trace at all. Only the existence of the working sibling line L379
   makes it visible.
4. **`at-observation-01.timer` and `at-observation-01-closeout.timer`** — enabled, active,
   and pinned to a one-shot date five weeks past with `Persistent=false`. They pass every
   "is it enabled?" check and can never run.
5. **`hermes-autonomous-loop.timer`** — never triggered, disabled, absent from
   `list-timers`, yet edited three times in the last two weeks and referenced in live
   tooling comments as though it were running.
6. **`tradeai-portfolio-backup-cadence`** — the definition currently on disk has never been
   validated by its own schedule; its last timer-driven run tested a file that no longer
   exists.
7. **`cio-truth-gates-ui-validation`** — its last run is honest and its guarded content is
   unchanged, but it has no `push` trigger, so `main` itself is never directly validated by
   it. Sound today; silently blind to any change that reaches main other than through a
   path-matching PR.

**A cross-cutting note on all 34 user units that execute from `CURRENT`.** They run release
`66f97259`, one commit behind `origin/main`. That one commit is the compile fix, so the
live release still contains the broken script:

```
$ .venv/bin/python -m py_compile $CURRENT/scripts/cio_event_lifecycle_census.py
  File ".../scripts/cio_event_lifecycle_census.py", line 26
    from __future__ import annotations
SyntaxError: from __future__ imports must occur at the beginning of the file
```

`[VERIFIED]` No cron entry and no systemd unit invokes that script, so nothing is currently
failing because of it. The point is narrower and worth keeping: **green CI on `main` is not
a statement about what the machine is running.** Every scheduled job on this host is
validating a tree that CI has moved past.

---

## 5. Proposals (advisory only — nothing was changed)

1. Wire `tests/test_every_script_compiles.py` into a workflow that runs on `push` to
   `main`, unfiltered by path. It is worth little where it sits.
2. Add `cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild &&` to crontab L378.
3. Make the PEAK_SKIP gate leave evidence when it *proceeds*, not only when it skips — a
   one-line `OFFPEAK proceed` marker would convert "no evidence" into a positive record.
4. Fix the wrapper's `PY` fallback to point at the canonical tree, or fail loudly instead
   of returning rc=127 into a `set -e` caller.
5. Disable or delete `at-observation-01{,-closeout}.timer` and either enable or remove
   `hermes-autonomous-loop.timer`; a maintained unit that cannot fire is worse than an
   absent one.
6. Consider a periodic reconciliation that asserts `CURRENT`'s sha equals `origin/main`, or
   surfaces the gap where operators see it.

---

## 6. Method and limits

- Both schedulers enumerated: `crontab -l` (997 lines), `systemctl --user list-timers --all`
  (75 timers), `systemctl list-timers --all` (21 timers).
- Execution evidence taken from log mtimes and contents, written artifacts, systemd
  `LastTriggerUSec` / `ExecMainStatus` / `Result`, and the journal. `[VERIFIED]`
  `/var/log/journal` exists and journald `Storage` defaults to `auto`, so journal evidence
  on this host is persistent rather than volatile.
- Sha comparison via `gh run list --json headSha` against `git rev-parse origin/main`, plus
  blob-level comparison where a stale sha needed disambiguating from stale content.
- **Limits.** `/var/spool/cron/crontabs/johnclaw` is unreadable, so no crontab edit history
  was available and §2.6's install-date question is left open rather than guessed. I did not
  audit the nine workflows unchanged in the window, nor the ~50 user timers outside the
  two-week scope. The `journalctl` retention window was not measured, so "durable" here
  means "present now and persistently stored", not "retained for N days".
- Two hand-exercises, both labelled inline and neither counted as a scheduled run:
  `run_with_deepseek_offpeak.sh --official -- echo PROCEEDED`, and
  `pytest tests/test_every_script_compiles.py`. Both are read-only; neither touches broker,
  Telegram, or vendor paths.
