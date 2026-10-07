# Cron consolidation RANK 4 — platform maintenance pipeline (PROPOSAL)

```
Status:        PROPOSAL — nothing installed, no crontab line touched
Date:          2026-10-07
Runner:        scripts/pipelines/run_platform_maintenance_pipeline.sh --cadence {nightly|weekly|monthly} [--dry-run|--apply]
Units:         config/systemd/user/tradeai-platform-maintenance-{nightly,weekly,monthly}.{timer,service}  (PROPOSAL ONLY)
Lanes:         platform-maintenance-nightly / -weekly / -monthly  (config/lane_registry.json, NEVER_SCHEDULED)
Output signal: data/runtime/platform_maintenance_<cadence>_last.json  (PlatformMaintenanceRun@v1)
Test:          tests/test_platform_maintenance_pipeline_20261007.py  (registered in run_cio_hardening_ci.py GATES)
Precedent:     scripts/pipelines/run_portfolio_maintenance_pipeline.sh (which EXCLUDES db_retention — this runner is where it goes)
Grant needed:  config-write (install units) + crontab edit (delete the absorbed lines). AGENTS.md §9.3: operator-only.
```

## Why

Fifteen platform-maintenance crontab lines fire between 01:15 and 06:00, spread across the file (lines
162–1077), each with its own log, some with a lock, two with a timeout, none with a run receipt. The
portfolio-maintenance runner already consolidated the portfolio cadences but deliberately excluded
`db_retention`. This runner absorbs the rest into one serial run per cadence with a per-step `timeout`,
the step's original `/tmp` lock, continue-on-error, a tail of each step's output in one pipeline log,
and a summary JSON that is the lane's durable output signal (AGENTS.md §0.8 — exit code is not evidence).

## Mapping — crontab line → step

Line numbers are from `crontab -l` on 2026-10-07 (1077 lines). Args, inline env, lock path and timeout
are preserved verbatim. Order = the clock order of the lines. `$PROJ` in the crontab is already
`/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`; `$PY` is the dev-tree venv (CURRENT has
no `.venv`, so the runner resolves `TRADEAI_PY` → `$PROJ/.venv/bin/python` → the crontab's literal path).

### `--cadence nightly` (timer 01:15 daily)

| # | cron line | clock | step | preserved from the line | timeout |
|---|-----------|-------|------|-------------------------|---------|
| 1 | 713 | 01:15 | `rotate_runtime_logs` | `flock -n /tmp/tradeai_rotate_logs.lock bash scripts/rotate_runtime_logs.sh` → `logs/rotate_runtime_logs.log` | 60m (new) |
| 2 | 207 | 02:30 | `populate_performance_context` | `$PY scripts/populate_performance_context.py --apply` → `logs/perf_context.log` | 60m (new) |
| 3 | 1045 | 02:30 | `report_platform_conformance` | `TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state TRADEAI_RELEASE_SHA=$(cat $PROJ/GIT_SHA) flock -n /tmp/tradeai_platform_conformance.lock $PY scripts/report_platform_conformance.py --write` → `persistent-state/logs/platform_conformance.log` | 60m (new) |
| 4 | 495 | 02:45 | `nightly_integrity_sweep` | `$PY scripts/nightly_integrity_sweep.py --telegram` → `logs/integrity_sweep.log` | 60m (new) |
| 5 | 162 | 03:00 | `strategy_config_sync` | `$PY scripts/strategy_config_loader.py --sync-db` → `logs/strategy_config_sync.log` | 60m (new) |
| 6 | 417 | 03:10 | `siem_retention_purge` | `$PY scripts/siem_retention_purge.py` → `logs/siem_retention_purge.log` | 60m (new) |
| 7 | 1023 | 03:25 | `hermes_universe_history_retention` | `flock -n /tmp/hermes_universe_history_retention.lock $PY scripts/hermes_universe_history_retention.py --apply` → `logs/hermes_universe_history_retention.log` | 60m (new) |
| 8 | 1076 | 03:30 | `n8n_lab_backup` | `bash scripts/n8n_lab_backup.sh --apply` → `persistent-state/logs/n8n_lab_backup.log` | 60m (new) |
| 9 | 961 | 04:10 | `db_retention` | `flock -n /tmp/db_retention.lock timeout 30m $PY scripts/db_retention.py` → `logs/db_retention.log` (internal disk-floor guard untouched) | **30m (cron)** |
| 10 | 957 | 04:40 | `prune_document_mentions` | `flock -n /tmp/document_mentions_prune.lock timeout 20m $PY scripts/prune_document_mentions.py --apply` → `logs/document_mentions_prune.log` | **20m (cron)** |
| 11 | — NEW | 04:50 | `report_db_hygiene` | `$PY scripts/report_db_hygiene.py --write` → `logs/db_hygiene.log`; **guarded** on `scripts/report_db_hygiene.py` existing (lands with `wt/db-retention-durable-20261007`; absent on this base → recorded `skipped_missing`) | 60m (new) |

Kept OUT of nightly: line 645 `~/.claude/sync-memory-to-drive.sh` (03:10 — different tree, `~/.claude`);
lines 405 / 1026 hourly Drive syncs (`sync-docs-to-drive.sh` :05, `sync_code_mirror_to_drive.sh --apply` :35 — rank 18).

### `--cadence weekly` (timer Sun 03:00)

| # | cron line | clock | step | preserved from the line | timeout |
|---|-----------|-------|------|-------------------------|---------|
| 1 | 494 | Sun 03:00 | `docs_retention` | `bash scripts/docs_retention.sh` → `logs/docs_retention.log` | 60m (new) |
| 2 | 1077 | Sun 04:00 | `n8n_lab_restore_drill` | `bash scripts/n8n_lab_restore_drill.sh --apply` → `persistent-state/logs/n8n_lab_restore_drill.log` | 60m (new) |
| 3 | 372 | Sun 06:00 | `check_system_versions` | `/bin/bash scripts/check_system_versions.sh` → `/home/johnclaw/logs/version_check.log` | 60m (new) |

Kept OUT of weekly: line 919 `sweep_schwab_instruments.py --apply` (Sat 03:30 — broker-adjacent; keeps its own line).

### `--cadence monthly` (timer 1st 06:00)

| # | cron line | clock | step | preserved from the line | timeout |
|---|-----------|-------|------|-------------------------|---------|
| 1 | 166 | 1st 06:00 | `backup_verify` | `flock -n /tmp/backup_verify.lock $PY scripts/backup_verify.py` → `logs/backup_verify.log` | 60m (new) |
| 2 | 163 | 1st 03:00 | `youtube_transcript_purge` | the two inline `$PY -c` programs (`transcript_processor.set_purge_dates()`, then `DELETE FROM youtube_transcripts WHERE purge_after IS NOT NULL AND purge_after < CURRENT_DATE`) are now `scripts/purge_youtube_transcripts.py --apply` → `logs/transcript_purge.log`, plus receipt `data/runtime/youtube_transcript_purge_last.json` | 60m (new) |

The wrapper uses `transcript_processor._get_conn()` — the identical localhost `trade_ai` connection the inline
program built by hand from `.env` — so no second credential path exists. Its default is a dry run (counts only).

### Timeouts marked "(new)"

The cron lines carried no timeout; `60m` is `PLATFORM_MAINT_DEFAULT_TIMEOUT` and is NOT VERIFIED against the
real durations of these steps. Before install, read the last few runs in each step's log and raise the default
(or set a per-step value in the table) for anything that has ever run longer. A timeout is recorded as
`rc=124, timed_out=true` and the next step still runs.

## Runner behaviour

- Pipeline lock `/tmp/pipeline_platform-maintenance-<cadence>.lock` (same scheme as `acquire_lock`); a second
  invocation while one runs exits 0 with "already running" and writes nothing.
- Each step: `flock -n -E 75 <cron lock> timeout --kill-after=30s <t> env <cron env> bash -c "cd $PROJ && <cmd>"`.
  rc 75 → `skipped_lock` (a leftover crontab line holding the lock cannot double-run the step); 124/137 →
  `timed_out`. Output goes to `logs/pipelines/platform-maintenance/<cadence>/run_<ts>/<step>.out`, is appended
  to the step's original log (so nothing that read it goes dark), and its last 40 lines are tailed into the
  pipeline log `logs/pipelines/platform-maintenance/<cadence>/platform_<cadence>_<ts>.log`.
- Continue on error; summary written once at the end (atomic `.tmp` + `mv`):
  `{schema, as_of, served_sha, cadence, dry_run, pipeline_log, run_dir, steps:[{step, rc, duration_s, timeout,
  timed_out, skipped_lock, skipped_missing, lock, cmd}], ok, failed_steps, skipped_steps}`.
- Exit 0 after a completed run even when `ok=false` (the summary is the signal; a failed unit per degraded
  night is the 2026-09-18 timer-churn trap). `PLATFORM_MAINT_EXIT_ON_FAIL=1` makes it exit 1 instead.
- `--dry-run` (default) prints the resolved plan and writes nothing — no log, no summary, no lock.
- `served_sha` = `$PROJ/GIT_SHA` (CURRENT) or `git rev-parse HEAD` (dev tree).

## Install (operator, under grants — in this order)

```bash
# 0. snapshot today's crontab FIRST (rollback input)
crontab -l > ~/trade-ai-releases/persistent-state/backups/crontab.pre-rank4.$(date +%Y%m%d_%H%M%S)

# 1. dry-run from the served tree, by path, exact timer form (AGENTS.md §9.3)
cd ~/trade-ai-releases/portfolio-server/CURRENT
bash scripts/pipelines/run_platform_maintenance_pipeline.sh --cadence nightly --dry-run
bash scripts/pipelines/run_platform_maintenance_pipeline.sh --cadence weekly  --dry-run
bash scripts/pipelines/run_platform_maintenance_pipeline.sh --cadence monthly --dry-run

# 2. install the units (config-write grant) — they are PROPOSAL files until this step
install -m 0644 config/systemd/user/tradeai-platform-maintenance-*.{timer,service} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-platform-maintenance-nightly.timer \
                               tradeai-platform-maintenance-weekly.timer \
                               tradeai-platform-maintenance-monthly.timer
systemctl --user list-timers 'tradeai-platform-maintenance-*'

# 3. delete the absorbed crontab lines by number (cron grant). NUMBERS ARE FROM 2026-10-07 — re-confirm each
#    with `crontab -l | sed -n 'Np'` before deleting; the file changes. Delete highest-first so numbers hold.
crontab -l | sed -e '1077d;1076d;1045d;1023d;961d;960d;959d;958d;957d;713d;495d;494d;417d;372d;207d;166d;163d;162d' | crontab -
#    (958-960 are the three comment lines above db_retention; keep them if you prefer the history in place.)
crontab -l | grep -cE 'rotate_runtime_logs|populate_performance_context|report_platform_conformance|nightly_integrity_sweep|strategy_config_loader|siem_retention_purge|hermes_universe_history_retention|n8n_lab_backup|db_retention|prune_document_mentions|docs_retention|n8n_lab_restore_drill|check_system_versions|backup_verify|youtube_transcripts'
#    expect 0 (the schwab sweep, memsync and Drive sync lines do not match this pattern and stay)

# 4. registry in the SAME change (AGENTS.md §9.3): flip the three lanes to ACTIVE with scheduler.kind=systemd
#    and the timer name; mark hermes-universe-history-retention, db-retention, document-mentions-prune,
#    platform-conformance-audit, n8n-lab-backup, n8n-lab-restore-drill RETIRED with
#    superseded_by=platform-maintenance-<cadence>; run python3 scripts/check_lane_registry.py --fail-on-new.
```

`crontab - < file` works; `crontab <file>` fails silently (AGENTS.md §7) — the pipe form above is the safe one.

## Verification (after the first natural fire, not a hand-run)

```bash
jq '{as_of, served_sha, ok, failed_steps, skipped_steps, steps: [.steps[] | {step, rc, duration_s, timed_out, skipped_lock}]}' \
   ~/trade-ai-releases/portfolio-server/CURRENT/data/runtime/platform_maintenance_nightly_last.json
systemctl --user status tradeai-platform-maintenance-nightly.service --no-pager | tail -20
ls -t ~/trade-ai-releases/portfolio-server/CURRENT/logs/pipelines/platform-maintenance/nightly/ | head
# each absorbed log still grows (e.g. logs/db_retention.log gets a "platform-maintenance/nightly step=db_retention" header per run)
tail -3 ~/trade-ai-releases/portfolio-server/CURRENT/logs/db_retention.log
python3 scripts/check_lane_registry.py --fail-on-new
```

Expected on night 1: `report_db_hygiene` is `skipped_missing` until `wt/db-retention-durable-20261007` is on the
served tree; every other step `rc=0`; `ok=true`. If a step shows `skipped_lock`, a crontab line was not deleted
(the lock proves the double-run protection worked) — finish step 3.

## Rollback

```bash
systemctl --user disable --now tradeai-platform-maintenance-nightly.timer tradeai-platform-maintenance-weekly.timer tradeai-platform-maintenance-monthly.timer
crontab - < ~/trade-ai-releases/persistent-state/backups/crontab.pre-rank4.<stamp>   # re-adds every absorbed line verbatim
crontab -l | wc -l        # expect the pre-install count (1077 on 2026-10-07)
# registry: revert the lane flips from step 4 in the same change
```

The step scripts are unchanged, so rolling back is purely a scheduler change; nothing in the data path moved.

## Expected line reduction

| | lines |
|---|---|
| crontab lines absorbed (nightly 10 + weekly 3 + monthly 2) | **15** → 0 crontab lines, 3 timers |
| kept out, still their own crontab lines | 4 (645 memsync, 919 schwab sweep, 405 + 1026 Drive syncs) |
| comment lines that may go with 961 | 3 (958–960) |

The task brief estimated 17 → 3; the count against today's crontab is 15 absorbed lines (the brief's figure
may have counted the two sync lines that this rank keeps out). Either way: 3 timers replace them all.

## Not verified here

- Real durations of each step vs the 60m default (see "Timeouts"). NOT VERIFIED — read the logs before install.
- `n8n_lab_backup.sh` / `n8n_lab_restore_drill.sh` were installed 2026-10-07 under grants `99d773a23dbd784c`
  / `113fa7d3b2344284`; absorbing their lines removes those cron lines from the crontab the grant installed —
  confirm the grant owner is content with the move.
- `weekly-disk-cleanup` (systemd, Sun 06:30) ALSO runs `db_retention` via `weekly_disk_cleanup_notify.py`.
  Not a crontab line, not in scope; both runs share `/tmp/db_retention.lock` only if that script takes it —
  NOT VERIFIED.
- The serial nightly chain starting 01:15 ends when it ends; `report_platform_conformance` previously fired at
  a fixed 02:30 and now runs third (~minutes after 01:15 unless rotation is slow). The memory note that the
  conformance nightly writes into CURRENT so the gate reads stale state is untouched by this rank.
- No step was executed for real from this worktree: only `--dry-run` for each cadence and the subprocess
  tests with a fake manifest (`true`/`false`/`sleep 3` under `1s`).
