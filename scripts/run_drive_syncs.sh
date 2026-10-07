#!/usr/bin/env bash
# run_drive_syncs.sh — the two hourly Drive syncs in sequence under one crontab line
# (cron consolidation tranche C, rank 18).
#
# Today (crontab lines 405 and 1026, read 2026-10-07):
#   5  * * * * bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/safe_flock.sh /tmp/drive_sync.lock bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/sync-docs-to-drive.sh >> /home/johnclaw/logs/drive-sync.log 2>&1
#   35 * * * * bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/safe_flock.sh /tmp/code_mirror_drive_sync.lock bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/sync_code_mirror_to_drive.sh --apply >> /home/johnclaw/logs/code-mirror-drive-sync.log 2>&1
#
# This runner executes those two commands one after the other — same safe_flock lock paths, same
# scripts from the same CURRENT tree, same argv, same per-step log files — and adds a per-step
# timeout and a receipt. It does NOT change what either script syncs: sync-docs-to-drive.sh pushes
# $TRADEAI_DOCS_SRC (default CURRENT)/docs and sync_code_mirror_to_drive.sh archives the DEV hub
# checkout plus CURRENT (both source trees are set inside those scripts, not here).
# The 03:10 ~/.claude memory sync is a different job and stays on its own line.
#
# Proposed replacement (one line, NOT installed by this PR — see
# docs/implementation/n8n-parallel/proposals/cron-tranche-c-lowrisk.md):
#   5 * * * * bash /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/scripts/run_drive_syncs.sh --apply >> /home/johnclaw/logs/drive-syncs.log 2>&1
#
# Usage:
#   bash scripts/run_drive_syncs.sh --dry-run    # print the two commands; run nothing; write nothing
#   bash scripts/run_drive_syncs.sh --apply      # run both, in order, continue on error
# Env:
#   DRIVE_SYNCS_CURRENT         tree whose scripts run (default /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT)
#   DRIVE_SYNCS_LOG_DIR         per-step log dir (default /home/johnclaw/logs)
#   DRIVE_SYNCS_STEP_TIMEOUT_S  wall clock per step, 0 = none (default 1500; the old lines had none —
#                               a hung gog was only ever caught by safe_flock's PID skip the next hour)
#   DRIVE_SYNCS_LOCK_DIR        where the two lock files live (default /tmp — the original paths)
#   TRADEAI_STATE_ROOT          receipt root (default ~/trade-ai-releases/persistent-state)
#   DRIVE_SYNCS_RECEIPT         receipt path override
# Receipt: $TRADEAI_STATE_ROOT/data/runtime/drive_syncs_last.json (DriveSyncsReceipt@v1)
# Exit: 0 when both steps exit 0, 1 otherwise (the receipt is written either way).
#
# AUTHORITY: READ_ONLY_ADVISORY. Lane registry: drive-syncs-hourly (NEVER_SCHEDULED).
set -uo pipefail

CUR="${DRIVE_SYNCS_CURRENT:-/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT}"
LOG_DIR="${DRIVE_SYNCS_LOG_DIR:-/home/johnclaw/logs}"
LOCK_DIR="${DRIVE_SYNCS_LOCK_DIR:-/tmp}"
STEP_TIMEOUT="${DRIVE_SYNCS_STEP_TIMEOUT_S:-1500}"
STATE_ROOT="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
RECEIPT="${DRIVE_SYNCS_RECEIPT:-$STATE_ROOT/data/runtime/drive_syncs_last.json}"

MODE=""
for a in "$@"; do
  case "$a" in
    --dry-run) MODE="dry-run" ;;
    --apply)   MODE="apply" ;;
    -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
    *) echo "run_drive_syncs: unknown arg: $a (use --dry-run or --apply)" >&2; exit 2 ;;
  esac
done
if [ -z "$MODE" ]; then
  echo "usage: $0 --dry-run | --apply" >&2
  exit 2
fi

# name | lock | log | script | script args   (order is the run order)
STEPS=(
  "docs|$LOCK_DIR/drive_sync.lock|$LOG_DIR/drive-sync.log|$CUR/scripts/sync-docs-to-drive.sh|"
  "code_mirror|$LOCK_DIR/code_mirror_drive_sync.lock|$LOG_DIR/code-mirror-drive-sync.log|$CUR/scripts/sync_code_mirror_to_drive.sh|--apply"
)

step_cmd() {   # prints the exact argv (one per line) for a step row
  local row="$1" name lock log script sargs
  IFS='|' read -r name lock log script sargs <<< "$row"
  printf '%s\n' bash "$CUR/scripts/safe_flock.sh" "$lock" bash "$script"
  [ -n "$sargs" ] && printf '%s\n' "$sargs"
  return 0
}

if [ "$MODE" = "dry-run" ]; then
  echo "run_drive_syncs: DRY RUN — plan only, nothing executed, no receipt written"
  echo "  current=$CUR log_dir=$LOG_DIR step_timeout_s=$STEP_TIMEOUT receipt_would_be=$RECEIPT"
  i=1
  for row in "${STEPS[@]}"; do
    IFS='|' read -r name lock log script sargs <<< "$row"
    printf '  %d. %s: ' "$i" "$name"
    while IFS= read -r part; do printf '%q ' "$part"; done < <(step_cmd "$row")
    printf '>> %q 2>&1\n' "$log"
    i=$((i+1))
  done
  exit 0
fi

mkdir -p "$LOG_DIR" "$(dirname "$RECEIPT")" 2>/dev/null || true
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ROWS_JSON=""
ALL_OK=1
for row in "${STEPS[@]}"; do
  IFS='|' read -r name lock log script sargs <<< "$row"
  argv=(); while IFS= read -r part; do argv+=("$part"); done < <(step_cmd "$row")
  s_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; t0=$(date +%s)
  echo "[$s_started] run_drive_syncs step=$name start" >> "$log"
  if [ "$STEP_TIMEOUT" != "0" ]; then
    timeout --foreground -k 30 "$STEP_TIMEOUT" "${argv[@]}" >> "$log" 2>&1
  else
    "${argv[@]}" >> "$log" 2>&1
  fi
  rc=$?
  dur=$(( $(date +%s) - t0 ))
  outcome="RAN"
  if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then outcome="TIMEOUT"; fi
  if [ "$rc" != 0 ] && [ "$outcome" = "RAN" ]; then outcome="FAILED"; fi
  [ "$rc" = 0 ] || ALL_OK=0
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] run_drive_syncs step=$name rc=$rc outcome=$outcome duration_s=$dur" >> "$log"
  ROWS_JSON+="${name}|${lock}|${log}|${rc}|${outcome}|${s_started}|${dur}"$'\n'
done
ENDED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - "$RECEIPT" "$STARTED" "$ENDED" "$CUR" "$STEP_TIMEOUT" "$ALL_OK" "$ROWS_JSON" <<'PY'
import json, os, sys, tempfile
path, started, ended, cur, timeout_s, all_ok, rows = sys.argv[1:8]
steps = []
for line in rows.splitlines():
    if not line.strip():
        continue
    name, lock, log, rc, outcome, s_started, dur = line.split("|")
    steps.append({"name": name, "lock": lock, "log": log, "rc": int(rc), "outcome": outcome,
                  "started_at": s_started, "duration_s": int(dur)})
sha = None
try:
    sha = open(os.path.join(cur, "GIT_SHA")).read().strip() or None
except OSError:
    pass
receipt = {"schema": "DriveSyncsReceipt@v1", "authority": "READ_ONLY_ADVISORY", "lane": "drive-syncs-hourly",
           "mode": "apply", "as_of": started, "ended_at": ended, "current": cur, "served_sha": sha,
           "step_timeout_s": None if timeout_s == "0" else int(timeout_s), "steps": steps,
           "ok": all_ok == "1", "outcome": "OK" if all_ok == "1" else "STEP_FAILED"}
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix=".drive_syncs_last.", suffix=".tmp", dir=os.path.dirname(path) or ".")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(receipt, indent=1) + "\n")
    fh.flush(); os.fsync(fh.fileno())
os.replace(tmp, path)
print(json.dumps({"outcome": receipt["outcome"], "steps": [(s["name"], s["outcome"], s["rc"], s["duration_s"]) for s in steps], "receipt": path}))
PY

[ "$ALL_OK" = 1 ] && exit 0 || exit 1
