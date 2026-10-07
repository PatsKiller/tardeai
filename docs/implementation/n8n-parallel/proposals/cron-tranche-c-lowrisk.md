# Cron consolidation — tranche C, low-risk part (ranks 13, 14, 18, 9), 2026-10-07

**Status: PROPOSAL. Nothing in this document is installed.** The four runners exist in the repo, are
covered by hermetic tests, and have been dry-run from the worktree (plans only). Every crontab change
below is an operator action under a cron grant (AGENTS.md §9.3 / §17); the registry rows for the new
lanes are `NEVER_SCHEDULED` and flip to `ACTIVE` only at cutover.

Source of truth for "today": `crontab -l` on ms01 read 2026-10-07 (line numbers are from that read and
will shift as other lines are added — grep by script basename before editing). `$PROJ` and `$PY` are the
crontab's own variables (`PROJ=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`,
`PY=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python`).

| Rank | Today | Proposed | Runner | Registry lane (NEVER_SCHEDULED) |
|---|---|---|---|---|
| 13 options tick | 3 lines, 216 firings/day | 1 line, 96 firings/day (same 216 step runs) | `scripts/options_tick.py` | `options-tick` |
| 14 orchestrator | 6 lines, 30 firings/week | 2 lines, 30 firings/week | `scripts/run_orchestrator_slot.sh` | `orchestrator-slot` |
| 18 Drive syncs | 2 lines, 48 firings/day | 1 line, 24 firings/day (same 48 sync runs) | `scripts/run_drive_syncs.sh` | `drive-syncs-hourly` |
| 9 hermes enhance | 6 lines, 313 subject firings/week, **65 same-minute collisions/week** | 1 line, 840 cheap dispatcher firings/week, 313 subject runs, **0 collisions** | `scripts/hermes_subject_enhance_dispatch.py` | `hermes-subject-enhance-dispatch` |
| **Total** | **17 lines** | **5 lines (−12)** | | |

Firings are counted as cron process starts. Rank 9's dispatcher fires more often than the six lines it
replaces because the union of their minute phases (0, 20, 25, 30, 40) has to be covered every hour
(position runs at :20 of every even hour, round the clock); a firing with nothing due exits in
milliseconds with a `NOTHING_DUE` receipt and calls no LLM. The alternative two-line form that halves
that is given under rank 9.

---

## Rank 13 — options tick (`scripts/options_tick.py`)

### Today (crontab lines 1036, 1038, 1040 — verbatim)

```
7,22,37,52 * * * * cd $PROJ && flock -n /tmp/options_thesis_lifecycle.lock bash -c 'set -a; . /run/user/$(id -u)/tradeai/env; set +a; M2_DSN="$M2_AGENT_DSN" $PY scripts/options_thesis_lifecycle.py --apply' >> logs/options_thesis_lifecycle.log 2>&1  # TRADEAI_LANE options-thesis-lifecycle (M2 read creds 2026-09-26)
9,24,39,54 * * * * cd $PROJ && flock -n /tmp/options_memory_projector.lock bash -c 'set -a; . /run/user/$(id -u)/tradeai/env; set +a; M2_DSN="$M2_AGENT_DSN" TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1 $PY scripts/options_memory_projector.py --apply' >> logs/options_memory_projector.log 2>&1  # TRADEAI_LANE options-memory-projector
3 * * * * cd $PROJ && flock -n /tmp/options_runtime_export.lock $PY scripts/export_options_runtime_snapshot.py --apply >> logs/options_runtime_export.log 2>&1  # TRADEAI_LANE options-runtime-export
```

### Proposed (one line)

```
7,22,37,52 * * * * cd $PROJ && $PY scripts/options_tick.py --apply >> logs/options_tick.log 2>&1  # TRADEAI_LANE options-tick (replaces options-thesis-lifecycle, options-memory-projector, options-runtime-export)
```

### What the runner does, per tick

| Step | Due | Lock (unchanged) | Command body (unchanged) | Log (unchanged) |
|---|---|---|---|---|
| 1 lifecycle | every tick | `flock -n /tmp/options_thesis_lifecycle.lock` | `bash -c 'set -a; . /run/user/$(id -u)/tradeai/env; set +a; M2_DSN="$M2_AGENT_DSN" $PY scripts/options_thesis_lifecycle.py --apply'` | `logs/options_thesis_lifecycle.log` |
| 2 projector | every tick, after 1 | `flock -n /tmp/options_memory_projector.lock` | `bash -c 'set -a; . /run/user/$(id -u)/tradeai/env; set +a; M2_DSN="$M2_AGENT_DSN" TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1 $PY scripts/options_memory_projector.py --apply'` | `logs/options_memory_projector.log` |
| 3 export | the tick whose 15-min window contains :03 → **the :52 tick** | `flock -n /tmp/options_runtime_export.lock` | `bash -c '$PY scripts/export_options_runtime_snapshot.py --apply'` | `logs/options_runtime_export.log` |

- The lifecycle's lock race with manual runs (`acquire_lifecycle_lock`, 2026-09-27/28) is preserved
  exactly: the lock is still taken by a `flock` parent of the python process, so the script sees it in
  `/proc/self/fd` and inherits it. The runner never takes a step lock itself.
- Additions: `flock -E 75` so a held step lock is reported as `LOCK_HELD` (not `FAILED`); continue on
  error; the runner's own non-blocking lock `/tmp/options_tick.lock` (an overlapping tick writes a
  `SKIPPED_TICK_LOCK_HELD` receipt); optional `--step-timeout-s` (default **0 = none**, which is what
  the crontab lines have); receipt `data/runtime/options_tick_last.json` (`OptionsTickReceipt@v1`,
  under `$TRADEAI_STATE_ROOT`, default `~/trade-ai-releases/persistent-state`).
- Per-step logs are unchanged on purpose: the three ACTIVE lanes' `output_signal` (file_mtime on those
  logs) keeps proving each step ran during the overlap window.

### Timing deltas (deliberate, small)

- Projector runs immediately after the lifecycle instead of 2 minutes later (it tails the lifecycle's
  store after a watermark, so "after" is what matters, not "2 minutes").
- Export moves from :03 to the :52 tick — 13 minutes before the :05 Drive sync instead of 2. It still
  precedes the sync; the snapshot it mirrors is at most 13 minutes older than today's.
- If the lifecycle hangs, the projector does not run that tick (today it would, independently). With no
  default timeout this is bounded only by the next tick's `SKIPPED_TICK_LOCK_HELD`; the receipt records
  per-step `duration_s` so the operator can set `--step-timeout-s` after observing two cycles.

### Registry

`options-tick` added as `NEVER_SCHEDULED` (output_signal `data/runtime/options_tick_last.json`). The
three existing lanes stay `ACTIVE`. Their `scheduler.match` values (`options_thesis_lifecycle.py` etc.)
will NOT match the new line, so at cutover they must flip to `RETIRED` (state_reason "superseded by
options-tick", `state_since`, evidence = two receipts) in the same commit that flips `options-tick` to
`ACTIVE` — otherwise `check_lane_registry.py --state-drift` reports them `ORPHANED`.

---

## Rank 14 — orchestrator slots (`scripts/run_orchestrator_slot.sh`)

### Today (crontab lines 142, 144, 145, 147, 148, 205 — verbatim)

```
0 9 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 0900 --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1  # RESTORED 2026-06-12: retirement failed — continuous_runner does not emit 0900 run artifacts
0 10 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 1000 --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1  # RESTORED 2026-06-12
0 12 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 1200 --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
0 14 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 1400 --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
0 16 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 1600 --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
30 17 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 1730 --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
```

Note the 17:30 line has no `--no-llm`; the five hourly lines do. Hours 11, 13 and 15 are deliberately
absent (13:00 is `finviz_enrichment.py`).

### Proposed (two lines)

```
0 9,10,12,14,16 * * 1-5 cd $PROJ && bash $PROJ/scripts/run_orchestrator_slot.sh --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1  # TRADEAI_LANE orchestrator-slot (replaces the 0900/1000/1200/1400/1600 lines)
30 17 * * 1-5 cd $PROJ && bash $PROJ/scripts/run_orchestrator_slot.sh --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1  # TRADEAI_LANE orchestrator-slot (replaces the 1730 line)
```

### Why a wrapper, not `--run-label auto`

`scripts/trade_ai_orchestrator.py` is a 1,200-line pipeline whose `--run-label` is `required=True` and
is used as a literal key in ~20 places (`reports/<date>/<label>`, `screener_run_health`,
`assets/screeners.yaml run_windows.<label>`, strategy-signal sync, plan backfill, auto-proposals). The
wrapper leaves it untouched. It rounds local `HHMM` to the nearest slot of `ORCH_SLOTS` (default
`0900,1000,1200,1400,1600,1730`, the labels of the six lines; the yaml also knows 0400/0700 which other
jobs own) within `ORCH_SLOT_TOLERANCE_MIN` (default 20) and then `exec`s exactly the crontab command:
`bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label <L> <flags…>`
from `cd $PROJ`. Outside any window it exits 2 and runs nothing (a label is never guessed — 13:00 or
11:00 would otherwise be mislabelled 1200/1000). `--run-label L` passes through for manual replays;
`--dry-run` prints the command; `--now HHMM --print-label` is the test hook.

### Registry

`orchestrator-slot` added as `NEVER_SCHEDULED` (output_signal `logs/screener_pm.log`, the log both new
lines append to, same as today). The six old lines are in `undeclared_baseline` (inherited debt); when
they are deleted at cutover, remove those six strings from the baseline — the baseline only shrinks.

---

## Rank 18 — hourly Drive syncs (`scripts/run_drive_syncs.sh`)

### Today (crontab lines 405 and 1026 — verbatim)

```
5 * * * * bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/safe_flock.sh /tmp/drive_sync.lock bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/sync-docs-to-drive.sh >> /home/johnclaw/logs/drive-sync.log 2>&1
35 * * * * bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/safe_flock.sh /tmp/code_mirror_drive_sync.lock bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/sync_code_mirror_to_drive.sh --apply >> /home/johnclaw/logs/code-mirror-drive-sync.log 2>&1
```

What each syncs (read from the scripts, **not changed by this PR**): `sync-docs-to-drive.sh` pushes
`$TRADEAI_DOCS_SRC/docs` (default `$HOME/trade-ai-releases/portfolio-server/CURRENT`);
`sync_code_mirror_to_drive.sh` archives `TRADEAI_CODE_MIRROR_HUB` (default the DEV hub checkout
`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`) plus `TRADEAI_CODE_MIRROR_CURRENT`
(default CURRENT). The dev-tree default in the code mirror is by design (it archives the hub); whether
the docs sync should ever point at a worktree is a separate question and stays out of scope here. The
03:10 `~/.claude/sync-memory-to-drive.sh` line (645) is a different job and stays separate.

### Proposed (one line)

```
5 * * * * bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/run_drive_syncs.sh --apply >> /home/johnclaw/logs/drive-syncs.log 2>&1  # TRADEAI_LANE drive-syncs-hourly (replaces the :05 docs sync and :35 code-mirror lines)
```

The runner executes the two commands above in order — same `safe_flock.sh`, same lock paths, same
scripts from CURRENT, same argv, same per-step logs — and adds `timeout --foreground -k 30
$DRIVE_SYNCS_STEP_TIMEOUT_S` per step (**default 1500 s; the old lines had none** — set `0` to
remove), continue on error, and the receipt `data/runtime/drive_syncs_last.json`
(`DriveSyncsReceipt@v1`). `--dry-run` prints the two commands and writes nothing.

Timing delta: the code mirror moves from :35 to immediately after the docs sync (≈ :05 + docs
duration). Both still run once an hour.

### Registry

`drive-syncs-hourly` added as `NEVER_SCHEDULED`. The existing `code-mirror-drive-sync` lane
(`match: sync_code_mirror_to_drive.sh`) will not match the new line → flip it to `RETIRED` (superseded
by drive-syncs-hourly) at cutover; its own `output_signal` (`code-mirror-drive-sync-last.json`
`finished_utc`) keeps working because the script is unchanged. The docs-sync line is in the 2026-09-28
inherited tranche of the registry — remove that string when the line is deleted.

---

## Rank 9 — hermes subject enhance (`scripts/hermes_subject_enhance_dispatch.py`)

### Today (crontab lines 477–482 — verbatim)

```
*/30 9-16 * * 1-5 cd $PROJ && flock -n /tmp/enh_scalp.lock $PY scripts/hermes_subject_enhance.py --type scalp --lanes grok,chatgpt --apply --limit 10 >> logs/hermes_enh.log 2>&1  # H-enh scalp (Grok+ChatGPT)
*/20 9-16 * * 1-5 cd $PROJ && flock -n /tmp/enh_prop.lock $PY scripts/hermes_subject_enhance.py --type proposal --lanes grok,chatgpt --apply >> logs/hermes_enh.log 2>&1  # H-enh proposal (Grok+ChatGPT)
20 */2 * * * cd $PROJ && bash $PROJ/scripts/llm_priority_guard.sh && flock -n /tmp/enh_pos.lock $PY scripts/hermes_subject_enhance.py --type position --lanes grok,chatgpt --apply >> logs/hermes_enh.log 2>&1  # H-enh position (Grok+ChatGPT)
25 11,14 * * 1-5 cd $PROJ && bash $PROJ/scripts/llm_priority_guard.sh && flock -n /tmp/enh_sec.lock $PY scripts/hermes_subject_enhance.py --type sector --lanes grok,chatgpt --apply --limit 11 >> logs/hermes_enh.log 2>&1  # H-enh sector (Grok+ChatGPT)
40 16 * * 1-5 cd $PROJ && flock -n /tmp/enh_ct.lock $PY scripts/hermes_subject_enhance.py --type closed_trade --lanes grok,chatgpt --apply --limit 12 >> logs/hermes_enh.log 2>&1  # H-enh closed_trade (Grok+ChatGPT)
0 8,20 * * * cd $PROJ && bash $PROJ/scripts/llm_priority_guard.sh && flock -n /tmp/enh_report.lock $PY scripts/hermes_subject_enhance.py --type report --lanes grok,chatgpt --apply --limit 1 >> logs/hermes_enh.log 2>&1  # H-enh report (Grok+ChatGPT) — daily second-read of the morning brief
```

Measured same-minute collisions (`python3 scripts/hermes_subject_enhance_dispatch.py --stats`): **65
per week** — 40 at :00 in 09–16 (scalp + proposal), 20 at :20 of even hours (proposal + position), 5
at 16:40 (proposal + closed_trade). Each is two processes calling the same two OAuth lanes at once.
(The tranche brief said 40; that count covers only the :00 pair.)

### Proposed (one line)

```
0,20,25,30,40 * * * * cd $PROJ && $PY scripts/hermes_subject_enhance_dispatch.py --apply >> logs/hermes_subject_enhance_dispatch.log 2>&1  # TRADEAI_LANE hermes-subject-enhance-dispatch (replaces the six H-enh lines)
```

Alternative with fewer firings (two lines, 490/week instead of 840) if the operator prefers:
`0,20,25,30,40 8-20 * * *` plus `20 0,2,4,6,22 * * *` with the same command.

### Due table (minute phase, window, lock, guard and argv preserved)

| Subject | Today | Minutes | Hours | Days | Guard | Lock | argv |
|---|---|---|---|---|---|---|---|
| scalp | `*/30 9-16 * * 1-5` | 0,30 | 9–16 | Mon–Fri | — | `/tmp/enh_scalp.lock` | `--type scalp --lanes grok,chatgpt --apply --limit 10` |
| proposal | `*/20 9-16 * * 1-5` | 0,20,40 | 9–16 | Mon–Fri | — | `/tmp/enh_prop.lock` | `--type proposal --lanes grok,chatgpt --apply` |
| position | `20 */2 * * *` | 20 | even | every day | `llm_priority_guard.sh` | `/tmp/enh_pos.lock` | `--type position --lanes grok,chatgpt --apply` |
| sector | `25 11,14 * * 1-5` | 25 | 11,14 | Mon–Fri | `llm_priority_guard.sh` | `/tmp/enh_sec.lock` | `--type sector --lanes grok,chatgpt --apply --limit 11` |
| closed_trade | `40 16 * * 1-5` | 40 | 16 | Mon–Fri | — | `/tmp/enh_ct.lock` | `--type closed_trade --lanes grok,chatgpt --apply --limit 12` |
| report | `0 8,20 * * *` | 0 | 8,20 | every day | `llm_priority_guard.sh` | `/tmp/enh_report.lock` | `--type report --lanes grok,chatgpt --apply --limit 1` |

Run order at a shared minute is table order (scalp, proposal, position, sector, closed_trade, report).
Each subject still runs as `flock -n -E 75 <its lock> $PY scripts/hermes_subject_enhance.py <argv>`
from `cd $PROJ`, output appended to `logs/hermes_enh.log`; a guarded subject first runs
`bash $PROJ/scripts/llm_priority_guard.sh` and is `DEFERRED_GUARD` when it says so (identical to the
crontab's `guard && job`).

### Sequencing semantics

- Due = subjects with a scheduled minute in `(watermark, now]`, where the watermark is the previous
  apply receipt's `window_end` (capped by `--max-lookback-min`, default 60). A subject runs at most once
  per firing however many of its minutes fell in the window; `hermes_subject_enhance.py`'s own
  freshness check dedupes at the subject level.
- Dispatcher lock `/tmp/hermes_subject_enhance_dispatch.lock` is **blocking with a bound**
  (`--lock-wait-s`, default 900): the :25 firing waits for a long :20 proposal run instead of dropping
  sector. If the wait times out, the receipt is `LOCK_WAIT_TIMEOUT` and the watermark is NOT advanced,
  so the next firing's window still covers the missed minutes.
- `--subject-timeout-s` default **1800 s — NEW; the crontab lines have none.** Rationale: under
  sequencing a hung subject would hold every later subject, which today it cannot. Set `0` to remove.
- Receipt `data/runtime/hermes_subject_enhance_dispatch_last.json`
  (`HermesSubjectEnhanceDispatchReceipt@v1`): window, due list with matched minutes, one row per run
  (`RAN | LOCK_HELD | DEFERRED_GUARD | TIMEOUT | FAILED`, rc, duration), outcome
  `OK | NOTHING_DUE | SUBJECT_FAILED | LOCK_WAIT_TIMEOUT`.

Timing delta: a subject that shares a minute with an earlier one in table order now starts after it
finishes (today both start at :00). Weekly subject runs are unchanged (313).

### Registry

`hermes-subject-enhance-dispatch` added as `NEVER_SCHEDULED`. The six old lines are in
`undeclared_baseline`; remove those six strings when the lines are deleted.

---

## Install / cutover order (operator, cron grant)

Per rank, independently; a rank can be cut over or rolled back without touching the others.

1. **Install the new line(s)** from the blocks above (`crontab -l > backup; (crontab -l; cat lines) | crontab -`).
   Do NOT delete the old lines yet. Overlap is safe by construction: every step keeps its original
   `flock -n` / `safe_flock` lock, so when the new runner and an old line coincide one of them records
   `LOCK_HELD` / a safe_flock skip and the other does the work — never two writers.
2. **Observe two cycles with receipts** — the durable artifact, not the exit code:
   - rank 13: `data/runtime/options_tick_last.json` twice with `outcome: OK` and three/two `RAN` rows
     (`LOCK_HELD` rows are the overlap with the old lines and are expected until step 3); the three
     per-step logs still advancing.
   - rank 14: two `reports/<date>/<label>/` sets plus `screener_run_health` rows for labels derived by the
     wrapper (grep `run_orchestrator_slot` in `logs/screener_pm.log`).
   - rank 18: `data/runtime/drive_syncs_last.json` twice with both steps `RAN`;
     `~/.local/state/drive-sync-last-result.json` and `code-mirror-drive-sync-last.json` advancing.
   - rank 9: two apply receipts with `outcome: OK` or `NOTHING_DUE`, including at least one firing where
     ≥2 subjects were due and their `started_at` do not overlap; `hermes_external_research` rows with
     `trigger_reason enh_*` continuing to arrive.
3. **Delete the old lines** (3 / 6 / 2 / 6) and in the same change flip the registry: new lane → `ACTIVE`
   (`state_since`, evidence = the two receipts); superseded lanes (`options-thesis-lifecycle`,
   `options-memory-projector`, `options-runtime-export`, `code-mirror-drive-sync`) → `RETIRED` with
   `state_reason` "superseded by <new lane>"; remove the deleted lines' strings from
   `undeclared_baseline` / `inherited_tranches`. Run `python3 scripts/check_lane_registry.py --fail-on-new --state-drift`.
4. Add the new receipts to the job-coverage monitor's expectations if it keys on lane rows (it reads
   `config/lane_registry.json`, so step 3 covers it — verify in the next monitor run).

## Rollback

Per rank: re-add the deleted old lines from the backup taken in step 1 and comment out the new line
(with a dated `RETIRED <date>` tag so `discover_commented_cron` records why). Nothing else changes —
the old scripts, locks and logs are untouched by this PR, and the new runners write only their own
receipts. Flip the registry rows back (`ACTIVE` ↔ `RETIRED`/`NEVER_SCHEDULED`).

## Expected reduction

| | Lines | Process firings | Work items |
|---|---|---|---|
| Rank 13 | 3 → 1 | 216/day → 96/day | 216 step runs/day, unchanged |
| Rank 14 | 6 → 2 | 30/week, unchanged | unchanged |
| Rank 18 | 2 → 1 | 48/day → 24/day | 48 sync runs/day, unchanged |
| Rank 9 | 6 → 1 | 313 subject firings/week → 840 dispatcher firings/week (490 with the two-line variant); 65 → 0 concurrent OAuth-lane collisions | 313 subject runs/week, unchanged |
| **Total** | **17 → 5** | | |

## Verification done in the worktree (2026-10-07)

- `tests/test_cron_tranche_c_lowrisk_20261007.py` — hermetic: fake step commands via `--manifest`,
  stub scripts in `tmp_path`, locks held with `fcntl` to prove `LOCK_HELD`, timestamps to prove
  sequencing; registered in `scripts/run_cio_hardening_ci.py` next to
  `tests/test_n8n_phase1_dispatch_20261007.py`.
- `bash -n` on both shell runners; `check_dark_contracts.py --fail-on-new`, `check_test_coverage.py`,
  `check_line_endings.py --range origin/main...HEAD`, `check_lane_registry.py --fail-on-new`.
- Plan-only dry runs from the worktree: `options_tick.py --tick-minute 52|7`,
  `hermes_subject_enhance_dispatch.py --now …` and `--stats`, `run_orchestrator_slot.sh --now … --dry-run`,
  `run_drive_syncs.sh --dry-run`. No step was executed, no receipt written, no lock under `/tmp` touched.

## NOT VERIFIED (needs a live run under a grant)

- That `flock -E 75` behaves identically on the served host (worktree: util-linux 2.41.3; the served
  CURRENT runs from the same host, so this should hold, but it was not run there).
- Real durations of each step/subject — the timeouts above are defaults chosen without measurement;
  the receipts exist to measure them.
- That the lifecycle's `/proc/self/fd` inheritance works when `flock` is spawned by Python rather than
  by cron's `sh -c` (same process tree shape; not exercised against the real script).
- `llm_priority_guard.sh` deferral timing under the dispatcher (the guard checks America/New_York;
  the dispatcher's due table uses the host's local time like cron does — identical only while the host
  TZ is America/New_York, which it is today).
- Hermes `--stats` counts assume every scheduled minute fires; cron skips during host downtime are not
  modelled.
