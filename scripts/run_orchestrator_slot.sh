#!/usr/bin/env bash
# run_orchestrator_slot.sh — derive the orchestrator --run-label from the clock
# (cron consolidation tranche C, rank 14).
#
# Today six crontab lines differ only in the hour field and the label it hardcodes:
#
#   0 9  * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 0900 --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
#   0 10 … --run-label 1000 …   0 12 … --run-label 1200 …   0 14 … --run-label 1400 …   0 16 … --run-label 1600 …
#   30 17 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/screener_pm.lock $PY scripts/trade_ai_orchestrator.py --run-label 1730 --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
#
# This wrapper rounds local HHMM to the nearest slot of the schedule table (assets/screeners.yaml
# run_windows is the source of those labels) and execs EXACTLY the crontab command with that label.
# Everything else on the line (flags, lock, log) is passed through untouched. The orchestrator itself
# is not modified: its --run-label stays a required literal, so a manual run still has to say which
# window it is.
#
# Proposed replacement (two lines, NOT installed by this PR — see
# docs/implementation/n8n-parallel/proposals/cron-tranche-c-lowrisk.md):
#
#   0 9,10,12,14,16 * * 1-5 cd $PROJ && bash $PROJ/scripts/run_orchestrator_slot.sh --no-llm --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
#   30 17 * * 1-5 cd $PROJ && bash $PROJ/scripts/run_orchestrator_slot.sh --no-alerts --allow-underfilled >> logs/screener_pm.log 2>&1
#
# Usage:
#   bash scripts/run_orchestrator_slot.sh [--now HHMM] [--print-label] [--dry-run] [--run-label L] [orchestrator flags…]
#     --now HHMM        use this local time instead of `date +%H%M` (tests, manual replay)
#     --print-label     print the derived label and exit 0
#     --dry-run         print the command that would run and exit 0 (runs nothing)
#     --run-label L     explicit label passthrough (skips derivation)
#   Env: ORCH_SLOTS (default 0900,1000,1200,1400,1600,1730), ORCH_SLOT_TOLERANCE_MIN (default 20),
#        ORCH_LOCK (default /tmp/screener_pm.lock), PY (interpreter; default python3), PROJECT_ROOT.
#   Exit 2 when no slot is within the tolerance: a run outside a known window is refused rather than
#   labelled with a guess (the label keys reports/<date>/<label> and screener_run_health).
set -euo pipefail

PROJ_DIR="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY_BIN="${PY:-python3}"
SLOTS="${ORCH_SLOTS:-0900,1000,1200,1400,1600,1730}"
TOL="${ORCH_SLOT_TOLERANCE_MIN:-20}"
LOCK="${ORCH_LOCK:-/tmp/screener_pm.lock}"

NOW=""; DRY=0; PRINT=0; LABEL=""
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --now)         NOW="${2:-}"; shift 2 ;;
    --print-label) PRINT=1; shift ;;
    --dry-run)     DRY=1; shift ;;
    --run-label)   LABEL="${2:-}"; shift 2 ;;
    *)             PASS+=("$1"); shift ;;
  esac
done

if [ -z "$LABEL" ]; then
  [ -n "$NOW" ] || NOW="$(date +%H%M)"
  if ! [[ "$NOW" =~ ^[0-9]{4}$ ]]; then
    echo "run_orchestrator_slot: --now must be HHMM, got '$NOW'" >&2
    exit 2
  fi
  now_min=$(( 10#${NOW:0:2} * 60 + 10#${NOW:2:2} ))
  best=""; best_diff=100000
  IFS=',' read -r -a slot_list <<< "$SLOTS"
  for s in "${slot_list[@]}"; do
    [[ "$s" =~ ^[0-9]{4}$ ]] || { echo "run_orchestrator_slot: bad slot '$s' in ORCH_SLOTS" >&2; exit 2; }
    s_min=$(( 10#${s:0:2} * 60 + 10#${s:2:2} ))
    d=$(( now_min - s_min )); [ "$d" -lt 0 ] && d=$(( -d ))
    if [ "$d" -lt "$best_diff" ]; then best="$s"; best_diff="$d"; fi
  done
  if [ -z "$best" ] || [ "$best_diff" -gt "$TOL" ]; then
    echo "run_orchestrator_slot: no slot in {$SLOTS} within ${TOL} min of $NOW — refusing to guess a --run-label" >&2
    exit 2
  fi
  LABEL="$best"
fi

if [ "$PRINT" = 1 ]; then
  echo "$LABEL"
  exit 0
fi

CMD=(bash "$PROJ_DIR/scripts/safe_flock.sh" "$LOCK" "$PY_BIN" scripts/trade_ai_orchestrator.py --run-label "$LABEL")
if [ "${#PASS[@]}" -gt 0 ]; then CMD+=("${PASS[@]}"); fi

if [ "$DRY" = 1 ]; then
  printf 'run_orchestrator_slot: DRY RUN (cwd=%s): ' "$PROJ_DIR"
  printf '%q ' "${CMD[@]}"
  printf '\n'
  exit 0
fi

cd "$PROJ_DIR"
exec "${CMD[@]}"
