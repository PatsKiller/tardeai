# Hermes Research-Graph Kill-Switch Repoint — 2026-06-06

Status:      ACTIVE
as_of:       2026-06-07T00:03:46-04:00
Measured at: efcc51365 / not measured

## Summary
Repointed the live Hermes Research Agent Graph / Coordinator emergency kill-switch from the retired
sidecar path to a live, non-retired runtime path. All live readers, the Command Center API/UI, and the
coordinator cron comment now use the single canonical path.

## Reason for change
`hermes_sidecar/.hermes` was rename-retired during Hermes global-profile migration v1.8, so
`hermes_sidecar/.hermes/DISABLED` is a stale, non-functional halt path. The research fleet still runs
LIVE every ~15 min (Coordinator cron `*/15`), so the emergency halt must point to a valid live path.
A second drift was also found: the API status reader used `~/.hermes/DISABLED` (global home) — also
non-canonical. Everything is now unified.

## Old stale paths (retired / non-canonical)
- `hermes_sidecar/.hermes/DISABLED` (retired sidecar — used by the live reader scripts)
- `hermes_sidecar/.hermes/COORDINATOR_DISABLED` (coordinator override)
- `~/.hermes/DISABLED` (global home — used by the API status reader)

## New canonical path
```
data/runtime/HERMES_DISABLED
```
(coordinator override: `data/runtime/COORDINATOR_DISABLED`; librarian override: `data/runtime/LIBRARIAN_DISABLED`)

## Files changed (live code)
- `scripts/hermes_coordinator.py` — `KILL_FILES` → `data/runtime/{HERMES_DISABLED,COORDINATOR_DISABLED}`
- `scripts/hermes_autonomous_loop.py` — `KILL_FILE` → `data/runtime/HERMES_DISABLED`
- `scripts/hermes_autonomous_librarian_backlog_loop.py` — checks `data/runtime/{HERMES_DISABLED,LIBRARIAN_DISABLED}`
- `scripts/hermes_observation_check.py` — `kill_path` → `data/runtime/HERMES_DISABLED`
- `scripts/hermes_youtube_discovery.py` — `KILL` → `data/runtime/HERMES_DISABLED`
- `scripts/hermes_rss_ingest.py` — `KILL` → `data/runtime/HERMES_DISABLED`
- `scripts/catalyst_momentum_engine.py` — `KILL` → `data/runtime/HERMES_DISABLED`
- `scripts/api_v2.py` — `_hermes_health` kill_file → `data/runtime/HERMES_DISABLED`; added `kill_switch_path`
- `apps/command-center-v3/src/pages/HermesHub.tsx` — banner path → `data/runtime/HERMES_DISABLED`; corrected
  wording (touch = HALT, not "re-arm"; rm = resume)
- Coordinator crontab **comment** corrected to the new halt path (schedule/command unchanged)

## Legacy note
The legacy kill-switch paths `hermes_sidecar/.hermes/DISABLED` and `~/.hermes/DISABLED` are retired and
**ignored**. Retired `hermes_sidecar/.hermes.RETIRED_*` flags are never read as live state.

## Validation performed
- `python3 -m py_compile` on all 8 patched Python files → OK
- `bash -n scripts/check_system_versions.sh` → OK
- `npm run build` (v3) → OK
- OFF/ON/OFF live test via `GET /api/v2/hermes/health`:
  - OFF (file absent): `kill_switch_active=false`, `kill_switch_path=data/runtime/HERMES_DISABLED`
  - ON (`touch data/runtime/HERMES_DISABLED`): `kill_switch_active=true`
  - OFF restored (`rm`): `kill_switch_active=false`
- No live code references `hermes_sidecar/.hermes/DISABLED` (scripts + v3 src).

## Old sidecar not recreated
At Step 7 an **empty** `hermes_sidecar/.hermes/sandboxes/singularity` scaffolding was found (created
~23:48 by an autonomous hermes process — **not** by this repoint; no kill-switch code references it). It
held no files and no process held it (verified via `lsof`); it was removed. The retired
`.hermes.RETIRED_*` / `install.RETIRED_*` directories were left untouched. The operator's live global
`hermes -p tradeai12b chat` session was not affected (it uses `~/.hermes`, not the sidecar).

## Operator usage
```bash
# Halt research fleet:
touch data/runtime/HERMES_DISABLED

# Re-enable research fleet:
rm -f data/runtime/HERMES_DISABLED

# Check state:
ls -l data/runtime/HERMES_DISABLED 2>/dev/null || echo "Research fleet enabled"
```

## Safety
No services restarted/enabled; no gateway/Telegram/Discord/Codex/cron-or-timer enablement (cron comment
edited only); no `hermes claw` cleanup/migrate; no retired dirs deleted; no broker/order/stop/proposal/
holdings logic touched; no secrets/.env touched; fleet restored to OFF (live), not halted.
