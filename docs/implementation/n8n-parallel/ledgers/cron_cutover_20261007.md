# Cron cutover ledger — 2026-10-07 (ranks 3–4 + tranche C install)

Served release: `16506e19e` (promoted 19:53Z). Grants: config-write `b4d4c9b070c87d4f`, cron `20d1d2c9dec32d5a` (approved in Telegram 19:55Z). Every write below was preceded by a crontab backup under `~/.local/state/tradeai/backups/`.

## Step 1 — ranks 3–4 (19:56Z)

| Action | Evidence |
|---|---|
| Backup | `crontab-20261007T195625Z-pre-ranks34.txt` (477 job lines) |
| `systemctl --user enable --now tradeai-health-tick.timer` | `list-timers`: next 16:00 EDT; first receipt `data/runtime/health_tick_last.json` as_of 19:56:05Z, due 3 ran 3, served_sha 16506e19e |
| `enable --now tradeai-platform-maintenance-{nightly,weekly,monthly}.timer` | next 2026-10-08 01:15 / 2026-10-11 03:00 / 2026-11-01 06:00 ET; `run_platform_maintenance_pipeline.sh --cadence nightly --dry-run` listed 11 steps with their locks |
| Crontab install | 477 → 447 job lines; 30 lines removed (17 health-tick, 13 maintenance; `db_retention.py` 04:10 line kept until the first nightly summary) |
| Registry | this PR: `health-tick` ACTIVE; `platform-maintenance-*` systemd/ACTIVE; 9 absorbed lanes RETIRED with `superseded_by`; 15 baseline entries pruned (the 9 absorbed lines in the 2026-09-28 inherited tranche stay in that pinned record) |

First receipt finding: step `system-health-agent` rc=1 — a pre-existing `UnboundLocalError` in `system_health_agent.py` (1,082 tracebacks under the old cron line). Fix: PR #1489. Until it is served the tick's `ok` stays false by design (the receipt names the failing step).

## Step 2 — tranche C install, old lines kept (19:58Z)

Backup `crontab-20261007T195826Z-pre-tranche-c.txt`; 454 → 459 non-comment lines; the 17 old lines stay until two observed cycles. Plan-only dry runs from the served tree before the write: `options_tick.py --tick-minute 7|52`, `hermes_subject_enhance_dispatch.py --stats` / `--now`, `run_orchestrator_slot.sh --now 0900|1730 --dry-run`, `run_drive_syncs.sh --dry-run` — all rc=0, nothing executed.

First cycle receipts (all `served_sha 16506e19e`):

| Lane | Receipt | Result |
|---|---|---|
| hermes-subject-enhance-dispatch | `hermes_subject_enhance_dispatch_last.json` 20:00:02Z | OK; scalp + proposal RAN sequentially (started 20:00:02.10 / 20:00:02.94, no overlap) |
| drive-syncs-hourly | `drive_syncs_last.json` 20:05:02Z | OK; docs RAN, code_mirror RAN (105 s) |
| options-tick | `options_tick_last.json` 20:07:02Z | OK; lifecycle LOCK_HELD (old line won the lock — expected overlap), projector RAN, export NOT_DUE |
| orchestrator-slot | `reports/2026-10-07/1600/` present; `screener_pm.log`: `safe_flock: skipped screener_pm; PID 2461108 still running` | one of the two coincident 16:00 invocations ran, the other recorded the skip — lock-safe by construction |

## Step 3 — pending (follow-up PR after the second cycle)

Delete the 17 old lines (3 options, 6 orchestrator, 2 drive, 6 H-enh) plus the duplicate `db_retention.py` 04:10 line once `platform_maintenance_nightly_last.json` shows the step; flip `options-thesis-lifecycle`, `options-memory-projector`, `options-runtime-export`, `code-mirror-drive-sync` (and the orchestrator/H-enh baseline strings) to RETIRED / `superseded_by`; prune their baseline entries. Rollback per rank: restore the backup above and disable the unit.

## Host note

`journalctl --user -u tradeai-health-tick`: "Failed to add control inotify watch descriptor … No space left on device" at unit start — the user manager is at the inotify instance limit (`fs.inotify.max_user_instances` = 128). The unit still ran; the limit is a host setting, not a tick defect.
