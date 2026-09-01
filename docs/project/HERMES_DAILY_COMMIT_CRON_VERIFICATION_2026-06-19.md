# Hermes Daily Commit Cron — Verification (2026-06-19)

Status:      HISTORICAL
as_of:       2026-06-19T17:12:22-04:00
Measured at: efcc51365 / not measured

## Purpose
`scripts/verify_hermes_daily_commit_cron.sh` is a **read-only** verifier that confirms the Hermes daily
report auto-commit path is **installed, safe, and observable**. It does NOT stage, commit, push, sync
Drive, edit crontab, or run the auto-commit job — it only inspects. Use it to confirm the automation is
healthy before/after changes, or to triage a missed nightly commit.

The thing it verifies:
- Cron: `13 23 * * * cd $PROJ && bash scripts/commit_hermes_daily.sh >> logs/commit_hermes_daily.log 2>&1`
- Script: `scripts/commit_hermes_daily.sh` (stages only `docs/hermes/`, IRON holdings guard, refuses
  paths outside `docs/hermes/`, relies on the pre-commit secret hook, pushes `origin/main`, mirrors docs
  to Drive, logs to `logs/commit_hermes_daily.log`).

## Checks performed
| Check | What it confirms |
|---|---|
| `project_root` | the project directory exists |
| `commit_script_exists` / `commit_script_executable` | the commit script is present (executable bit is a WARN — cron invokes via `bash`) |
| `cron_installed` / `cron_schedule` / `cron_log_path` | the crontab entry exists, is `13 23 * * *`, and logs to `logs/commit_hermes_daily.log` |
| `cron_no_dangerous_staging` | the cron line has no broad staging (`git add -A/.`, `git commit -a`, `rm -rf`) |
| `script_scope_docs_hermes_only` | script stages only `docs/hermes/` |
| `script_iron_guard` | the IRON holdings guard (`portfolio_totals`/`total_value`/`1000000`) is present |
| `script_outside_stage_refusal` | refuses + `git reset -q` if anything outside `docs/hermes/` is staged |
| `script_push_origin` | pushes `origin/main` |
| `drive_sync_script_exists` | `scripts/sync-docs-to-drive.sh` exists and is referenced |
| `log_path` | `logs/` writable; log file exists (WARN if not yet created — expected before first run) |
| `git_remote_origin` | `origin` is a GitHub URL |
| `staged_files_safe` | no staged files outside `docs/hermes/` (blocker if any; never unstages) |
| `docs_hermes_exists` / `recent_hermes_reports` | the report dir + recent artifacts exist |

## How to run
```bash
scripts/verify_hermes_daily_commit_cron.sh            # human-readable report
scripts/verify_hermes_daily_commit_cron.sh --json     # JSON ({ok, warnings, blockers, checks})
```

## Expected result
`RESULT: PASS` with exit `0`. A single WARN on `log_path` is normal until the cron's first scheduled run
creates `logs/commit_hermes_daily.log`. Exit codes: `0` = pass (warnings allowed), `1` = blocker, `2` =
verifier error.

## If the log says "commit blocked"
The commit script leaves the change staged (it does not push a bad commit) when the **pre-commit secret
hook** finds something or git errors. To triage:
1. `tail -20 logs/commit_hermes_daily.log` — read the blocked-commit line.
2. `git diff --cached -- docs/hermes/` — inspect what was staged.
3. Resolve the flagged content (or confirm it's a false positive), then commit manually or let the next
   nightly run retry. Do **not** force-push or bypass the hook.

## Reminder
This verifier is **read-only** and **does not run the auto-commit job**. Running it has no side effects
on git, crontab, Drive, or the Hermes reports.
