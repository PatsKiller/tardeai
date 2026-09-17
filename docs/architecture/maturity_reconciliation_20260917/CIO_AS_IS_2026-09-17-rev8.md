Status: ACTIVE
as_of: 2026-09-17 (each figure carries its own measurement timestamp, UTC)
Measured at: served pin `ede0698a5` — equal to `origin/main` `ede0698a5` `[VERIFIED]`
Canonical repo path: docs/architecture/maturity_reconciliation_20260917/CIO_AS_IS_2026-09-17-rev8.md
Authority: dated reading of what is deployed and running. READ_ONLY_ADVISORY, `MBI_BEHAVIOR=0`. Not a behaviour spec.
Revision: 8
Supersedes: Revision 7 (`2026-09-16-1759`), Revision 6 (`2026-09-16_1719ET`), Revisions 4–5 — see REVISION_LEDGER_2026-09-17-rev8.md for which of those remain published
See also: docs/architecture/maturity_reconciliation_20260917/HONEST_MATURITY_ASSESSMENT_2026-09-17-rev8.md
 docs/architecture/maturity_reconciliation_20260917/REVISION_LEDGER_2026-09-17-rev8.md

# CIO / goal-loop AS-IS — Revision 8 (2026-09-17)

**Why this revision exists.** Revision 7 was declared canonical by email on
2026-09-16T22:05:52Z ("This package supersedes Revision 6") while its source PR
**#1055 is still OPEN and CONFLICTING** — a revision was published before it was
merged. Its own release figures went stale within hours, and nothing published
anywhere reflects the last 24 hours of merged work. This document is the
re-measured replacement. Every number below was produced by running the command
named next to it on 2026-09-17.

```
LEGEND
 █ OBSERVED_LIVE   scheduled, ran, and left a durable artifact that proves it ran
 ◈ INTEGRATED      producer → store → consumer wired on the served pin
 ▓ PARTIAL         runs, but incomplete, degraded, or its consumer is unproven
 ░ UNWIRED         code exists and is correct; nothing calls it
 ✗ ABSENT          never executed, or produces nothing in recorded history
 ⚠ CONTRADICTED    a written claim that the live system disagrees with
```

---

## 1 · Release truth — `origin/main` and the served pin AGREE

| Field | Value | Source |
|---|---|---|
| `origin/main` | `ede0698a57809f8d667007a2af50b7f5c3b9a920` | `git fetch origin && git rev-parse origin/main` |
| `CURRENT` symlink | → `ede0698a5-main-exact-phase2-20260916-202534` | `readlink -f .../portfolio-server/CURRENT` |
| Served `BUILD_SHA` | `ede0698a57809f8d667007a2af50b7f5c3b9a920` | `cat CURRENT/BUILD_SHA` |
| Served `GIT_SHA` | `ede0698a57809f8d667007a2af50b7f5c3b9a920` | `cat CURRENT/GIT_SHA` |
| Served `SOURCE_COMMIT` | `ede0698a57809f8d667007a2af50b7f5c3b9a920` | `cat CURRENT/SOURCE_COMMIT` |
| `BUILD_STAMP.json` | `branch: main`, `label: main-exact-phase2`, `stamped_at: 2026-09-17T00:26:22Z` | `cat CURRENT/BUILD_STAMP.json` |
| `EXPECTED_RELEASE` | `.../ede0698a5-main-exact-phase2-20260916-202534` | `cat EXPECTED_RELEASE` |
| Deploy receipt | `ok: true`, `mode: promote`, `health: ok`, `rolled_back: false`, `deployed_sha: ede0698a5…`, `prev_release: 55032b25d…`, `at: 2026-09-17T00:26:34Z` | `cat ~/.local/state/cio-phase2-exact-main/deploy_receipt.json` |

**█ They match.** Source, build stamp, served tree and deploy receipt all name
the same commit. This is the fact Revision 7 got wrong by being written too
early: it cites served pin `61d67f635` and `origin/main` `03b8ce9e7`. Both are
now `ede0698a5`; `61d67f635` and `03b8ce9e7` are two of the nine release
directories that have since been superseded.

### ⚠ One release marker disagrees — `ACTIVE_RELEASE`

```
$ cat /home/johnclaw/trade-ai-releases/portfolio-server/ACTIVE_RELEASE
890e3aef feature/advisory-desk-v1 20260811-094957
```

`ACTIVE_RELEASE` still names an **advisory-desk branch build from 2026-08-11**,
while `CURRENT` and `EXPECTED_RELEASE` both name `ede0698a5`. This is not
cosmetic: `scripts/check_file_integrity.py` Step 5 ("DEPLOYMENT CONVERGENCE —
CURRENT / ACTIVE_RELEASE agreement") compares exactly these two and emits
`ACTIVE_RELEASE (…) != CURRENT symlink (…)`. The file has been stale across at
least nine promotions. **Finding, not a fix — nothing here was changed.**

---

## 2 · The armed hourly schedules — there are FOUR, not three

PR #1059's description says "Three crons were armed on 2026-09-16." The live
crontab carries **four** goal-loop lines, at `:20`, `:35`, `:40` and `:50`
(`crontab -l` lines 1032–1035 of 1035; 519 of those lines are comments). All
four run from the **dev tree** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`,
each sourcing `/run/user/$UID/tradeai/env` and
`~/.config/tradeai/agent_runtime_overrides.env`.

| Min | Script | Lane (`config/lane_registry.json`) | Declared arming | Verdict |
|---|---|---|---|---|
| `:20` | `report_goal_loop_baseline.py --json` | `goal-loop-baseline` | "INSTALLED crontab `20 * * * *` … (E7 2026-09-16)" | █ LIVE |
| `:35` | `cio_gate_measurement_bridge.py` | `goal-gate-bridge` | "Armed 2026-09-16 operator APPROVE E3" | ▓ measures, writes nothing |
| `:40` | `run_goal_pilot_material_change.py` | `goal-pilot-material-change` | "Armed 2026-09-16 operator APPROVE E4" | ▓ invocation-only |
| `:50` | `run_dormant_lane_consumers.py` | `dormant-lane-consumers` | "Armed 2026-09-16 with full package approval" | ▓ reports, writes nothing |

### `:20` baseline — █ the one that genuinely produces
Appends a `GoalLoopBaseline@v1` receipt per run to
`data/cio/goal_loop_baseline.jsonl` (→ `persistent-state`, via symlink).
**22 receipts**, first `2026-09-16T15:59:35Z`, last `2026-09-17T09:20:01Z`.
It is the source of the control numbers in §3 and the intake stats in §4.

### `:35` gate bridge — ▓ measures hourly, then discards the measurement
Runs, prints a full 12-gate board to `~/logs/goal_gate_bridge.log`, and
**writes no durable artifact**. Two flags exist and neither is on the cron line:

- `--write-measurements` (argparse line 593) writes
  `data/cio/agent_gate_measurements.json` — the file the lane registry declares
  as this lane's `output_signal`. **The file does not exist** at either the
  persistent-state or dev-tree path.
- `--update-catalog` (argparse line 597, applied at line 632) writes every gate
  id into `config/agent_maturity_catalog.json`. It is not on the cron line, so
  **the catalog still contains ZERO gate ids**: `grep -c '"gates"'` → `0`,
  `grep -c 'gate_id'` → `0`, across 17 agent entries.

Adding `--update-catalog` to a crontab line is a cron edit, which is
operator-only (AGENTS.md §17). **Proposed, not done.**

### `:40` pilot — ▓ 15 receipts, all `ok: true`, **zero verdicts**
```
receipts: 15        ok is True: 15        rows containing 'verdict': 0
result.status: ['library_loaded']         paid_calls: ['0']
first: 2026-09-16T20:39:14Z   last: 2026-09-17T09:40:01Z
```
Each receipt records `"note": "No run_shadow/evaluate_live_goals API; armed
schedule proves invocation only until a runner API is added."` The runner probes
`hasattr(pilot, "run_shadow")`, finds nothing, and writes success. **`ok: true`
here means "the wrapper ran", not "the pilot evaluated anything".** PR #1059
(OPEN) adds `run_shadow()` so the probe engages; until it merges every future
receipt is another invocation-only row. PR #1059's body cites **14** such
receipts — that was true when it was written; the 15th landed at
`2026-09-17T09:40:01Z`. The count grows by one per hour and carries no more
meaning at 15 than at 14.

### `:50` dormant-lane consumers — ▓ reports 9/9 ok, applies nothing
Last run `2026-09-17T09:50:01Z`: `lanes ok: 9/9  already wired: 2`,
`applied=False`. `--apply` is not on the cron line and is *refused* for the two
lanes whose write would adjudicate between two candidate truths. The script
**never writes** `data/cio/dormant_lane_consumers.jsonl` — the file the lane
registry names as its `output_signal` — and that file does not exist. Its
console report is the only output.

---

## 3 · The control number — the goal machinery has never been engaged

From the last baseline receipt, `ran_at: 2026-09-17T09:20:01Z`:

| Counter | Value |
|---|---|
| `events_total` | 64,781 |
| `GOAL_WAKE_RECORDED` | **34,912** |
| `GOAL_THESIS_UPDATED` | 29,862 |
| `GOAL_CREATED` | 4 |
| `GOAL_UPDATED` | 3 |
| **`goal_status_changed`** | **0** |
| **`GOAL_PREDICATE_SET`** | **0** |
| `distinct_goals` | 4 |
| `thesis_updates_provider_blocked` | 29,862 (**100.0 %**) |
| window | `2026-08-11T14:21:40Z` → `2026-09-16T20:43:53Z` |

`GOAL_PREDICATE_SET` = 0 is measured directly against the store, not inferred:
`grep -c "GOAL_PREDICATE_SET" data/cio/cio_goals.jsonl` → `0`, and likewise
`grep -c "GOAL_STATUS_CHANGED"` → `0`. The event type is *defined*
(`scripts/lib/cio_goals.py:59`) and emitted by exactly one function,
`set_predicate` (line 555), which **nothing calls**.

**░ The goal machinery is deployed and has never been engaged.** 34,912 wakes
produced zero status changes because no goal has a predicate whose satisfaction
would constitute "done", so there is no condition that could ever close one.
Every one of the 29,862 thesis updates was provider-blocked — 100 %.

Wakes per goal: `goal_f1d5c0a993d0` 21,599 · `goal_f2664540d8c1` 21,597 ·
`goal_695a5dbe2401` 21,584 · `goal_798ce2450f61` **1**. That last is the
Telegram-curation guardian goal Revision 7 registered; Revision 7 recorded
`wake_count = 0` against 34,718 wakes, and it has since taken exactly one wake
against 34,912. Registration is still not progress.

---

## 4 · `AGENT_RUNTIME_DISPATCH_DSN` is now provisioned — ◈ intake reports real numbers

`report_goal_loop_baseline.py`'s own `SCHEDULED_ENTRYPOINT` string still warns
that "the `intake` section records `unavailable` on every scheduled run until"
the DSN is set. It is now set — in
`~/.config/tradeai/agent_runtime_overrides.env`
(`AGENT_RUNTIME_DISPATCH_DSN=postgresql://agentic_runtime_shadow_rw…`), which
every one of the four cron lines sources. It is **not** in
`/run/user/1000/tradeai/env`; the override file is what supplies it.

Real queue stats, `2026-09-17T09:20:01Z`:

| Metric | Value |
|---|---|
| `completed` | 3,900 |
| `failed` | 2,277 |
| `refused_stale` | 4,277 |
| `queued` | 322 |
| `leased` | 0 |
| `oldest_queued_source_at` | `2026-09-09T07:14:41-04:00` |

These are real, and they are not healthy: `failed` + `refused_stale` = 6,554
against 3,900 completed, and the oldest queued item has been waiting **8 days**.
That is a finding this document records, not one it resolves.

Refusals in the same receipt: `receipts_inline` 171, `receipts_spilled_to_null`
**129** — all 129 from `governed_research_producer` under `CALLER_DAILY_CAP` in
a 7-day window.

---

## 5 · ⚠ Two ACTIVE lanes are SILENT and no scheduled surface says so

Evaluated with the system's own evaluator, `scripts/lib/lane_registry.evaluate_lane`:

| Lane | `output_signal` | Exists | Verdict |
|---|---|---|---|
| `goal-loop-baseline` | `data/cio/goal_loop_baseline.jsonl` | yes | **LIVE** |
| `goal-pilot-material-change` | `data/cio/goal_pilot_material_change.jsonl` | yes | **LIVE** |
| `goal-gate-bridge` | `data/cio/agent_gate_measurements.json` | **no** | **SILENT** |
| `dormant-lane-consumers` | `data/cio/dormant_lane_consumers.jsonl` | **no** | **SILENT** |

Both SILENT lanes are declared `state: ACTIVE` with `expected_cadence_hours: 1`.
The library computes the verdict correctly — but **nothing scheduled reports it**:

- `scripts/check_lane_registry.py` validates *structure* only. Run today it
  prints `structural errors: 0` … `lane registry: clean` and says nothing about
  either SILENT lane. It appears **0 times in the crontab** and is absent from
  `run_cio_hardening_ci.py`; its only caller is `ai_local_acceptance.sh`
  (`--fail-on-new`, which fires on *new undeclared* lanes).
- `scripts/report_store_cadence.py` is the only caller of `evaluate_lane`, and
  it reads `config/operator_surface_stores.json` — **7 store lanes**, none of
  them these four. Its own `NO_CONSUMER_REASON` concedes the point: "Surfacing a
  SILENT verdict to an operator surface is named remaining work: a finding that
  appears only in a log file is the defect this package exists to correct."

So the lane registry declares a durable proof-of-life for each armed lane, two
of those artifacts are never written, and **the resulting SILENT verdict reaches
no operator surface on any schedule.** Per AGENTS.md §0 rule 8, exit 0 is not
evidence — and here exit 0 is all there is.

---

## 6 · Script censuses — corrected figures

The plan's figures were wrong in the direction of alarm and were corrected by
direct re-measurement recorded in
`docs/audits/archive-proposals/ARCHIVE_MANIFEST_PROPOSAL_2026-09-16.json`
(`ArchiveManifest@v1`, `status: PROPOSAL_ONLY_NOT_APPLIED`):

| Census | Plan claimed | Measured 2026-09-16 |
|---|---|---|
| Zero-reference scripts | 288 (17.8 %) | **158** of 1,620 top-level `scripts/*.py` (9.8 %) |
| Test-only scripts | 139 | **76** |

Method, quoted from the manifest: 7,838 repo files scanned, one longest-first
alternation regex over all 1,620 basenames, matches attributed to the containing
file, self-matches excluded. The manifest states 158 is "a floor, not a ceiling"
because substring matching and counting `.md` as a reference both *understate*
the count.

Population today: **1,613** top-level `scripts/*.py` (`ls scripts/*.py | wc -l`);
2,681 `.py` including `scripts/lib/**`. The manifest measured 1,620 top-level a
day earlier.

### ⚠ An independent re-run today does not reproduce 158 / 76

Re-measuring against the same population (1,613 top-level `scripts/*.py`, 7,852
repo files scanned, substring attribution, self-matches excluded, `.md` counted
as a reference):

| Census | Manifest, 2026-09-16 | Independent re-run, 2026-09-17 |
|---|---|---|
| Zero-reference | 158 | **203** |
| Test-only | 76 | **85** |

Of the 203 zero-reference scripts, **0** are named in the live crontab.

The two runs disagree because the matching rules differ — the manifest used "one
longest-first alternation regex over all 1,620 basenames", which credits a
reference to the longest matching name only; this re-run tested each basename
independently, plus the `scripts.<stem>` and `scripts/<stem>` import forms.
Neither is wrong; they answer slightly different questions, and the manifest is
explicit that its figure is "a floor, not a ceiling".

**The finding is that this census is method-sensitive by roughly 25 %.** Both
numbers are floors; neither should be quoted as precise without naming the
method alongside it. What both agree on, and what actually matters: the true
figure is far below the plan's 288/139, and **no script in either census is
reachable from the live crontab** — so nothing in the census is load-bearing for
a scheduled lane.

Related, from `scripts/check_dark_contracts.py` run today: 55 zero-consumer
modules — 26 inherited from the 2026-08-27 baseline, 29 declaring
`NO_CONSUMER_REASON`, **0 NEW unexplained**; 0 uncompilable; 418 versioned-schema
definers; 4 resolved since baseline.

**Nothing has been archived, moved or deleted.** The manifest is a proposal, and
each row carries a blocking dependency that forbids batch archiving.

---

## 7 · What merged in the last 24 hours — and what did not

| PR | State | Merged | Subject |
|---|---|---|---|
| #1048 | MERGED | `2026-09-16T20:26:16Z` | Goal-oriented agents P2–P10 + pilot |
| #1049, #1051, #1052, #1053, #1054, #1056, #1057, #1058 | MERGED | 20:26Z → `2026-09-17T00:24:04Z` | Telegram hardening / ops follow-ups |
| #1050 | **CLOSED** | — | superseded by a follow-up fix |
| **#1055** | **OPEN · CONFLICTING** | — | "Revision 7" docs — *published by email while unmerged* |
| **#1059** | **OPEN · MERGEABLE** | — | goal-loop drivers (adds `run_shadow`, `drivers()`, `set_goal_predicate.py`) |

**Commit volume, measured:** `git log --oneline fc554d44b..ede0698a5 | wc -l`
→ **35** commits, of which **11** are merge commits. The brief's "~74 Telegram-hardening
commits" is **not supported** by the repository: 35 is the measured count of
every commit reachable on `main` since #1048 merged. Recorded here as a
correction rather than repeated.

**#1055's four documents do not exist on `main`.** `docs/architecture/` contains
`maturity_gap_closure_20260909`, `maturity_gap_closure_20260910` and
`maturity_overnight_20260912` — there is **no** `maturity_gap_closure_20260916`
directory. The Revision 7 markdown lives only on that open branch and on Google
Drive. Another agent is resolving #1055; **this document did not touch that branch.**

---

## 8 · Method, and what not to quote without re-measuring

Every figure above was produced by running a command and reading its output.
Where a source could not be read it is named `unavailable` with the reason — per
the brief and this codebase's own history, **a fabricated zero is
indistinguishable from a real one**, and two of the zeros here (`GOAL_PREDICATE_SET`,
catalog gate ids) are real and were confirmed against the underlying store, not
assumed from an absent file.

Exit codes were not trusted. `scripts/run_cio_hardening_ci.py` is documented to
print `CIO HARDENING CI FAILED` while exiting 0; `check_lane_registry.py` exits 0
while two ACTIVE lanes are SILENT. Both were read as text.

**Re-measure before quoting:**
- Pilot receipt count — grows by one every hour at `:40`; 15 as of `09:40:01Z`.
- `GOAL_WAKE_RECORDED` — 34,912 and climbing; `cio_goals.jsonl` was last written
  `2026-09-17T06:06Z` and is 29 MB.
- Gate board — recomputed hourly at `:35`; the `08:35:01Z` run is quoted in the
  companion assessment.
- `origin/main` and the served pin — equal at the time of writing; a promotion
  or merge breaks that equality, which is the exact failure Revision 7 hit.
