#!/usr/bin/env bash
# DeepSeek OFF-PEAK watchlist agent-jobs drain (overnight soak, not canary).
#
# Intended crontab (do not paste API keys; source env inside this wrapper).
# Host local time is America/New_York; hours 0-1 are 00:00–01:59 ET
# (04:00–05:59 UTC in EDT — between official DeepSeek peak windows).
# Wrapper also PEAK_SKIPs 01:00-04:00 and 06:00-10:00 UTC if invoked then.
#
#   */15 0-1 * * 1-6 $PROJ/scripts/run_watchlist_agent_jobs_offpeak.sh >> $PROJ/logs/watchlist_agent_jobs_offpeak.log 2>&1
#
# Optional Sunday off-peak (same hours; do not use overlapping */5 0-5):
#   */15 0-1 * * 0 $PROJ/scripts/run_watchlist_agent_jobs_offpeak.sh >> $PROJ/logs/watchlist_agent_jobs_offpeak.log 2>&1
#
# Guarantees:
#   - Source ~/.config/tradeai/agent-operator.env then /run/user/$(id -u)/tradeai/env
#   - Never print secret values
#   - Overnight-only soak default LLM_GLOBAL_DAILY_USD_CAP=2.00 if unset/non-positive
#   - Fail closed on malformed cap
#   - Not --scheduled-canary; worker --limit 8; singleton flock
#   - Never unlink a held lock
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ="${PROJ:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PY="${PY:-$PROJ/.venv/bin/python}"
LOG="${TRADEAI_OFFPEAK_LOG:-$PROJ/logs/watchlist_agent_jobs_offpeak.log}"
LOCK="${AGENT_JOBS_LOCK_PATH:-/tmp/tradeai_watchlist_agent_jobs.lock}"
# Default hard cap is 20m; tests may set TRADEAI_OFFPEAK_TIMEOUT_SEC (seconds).
TIMEOUT_SPEC="${TRADEAI_OFFPEAK_TIMEOUT_SEC:-20m}"
DRY_RUN="${TRADEAI_OFFPEAK_DRY_RUN:-0}"
SOAK_DEFAULT="2.00"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

log() {
  echo "$(ts) $*" >>"$LOG"
}

mkdir -p "$(dirname "$LOG")" "$PROJ/logs" 2>/dev/null || true

log "=== start pid=$$ lane=watchlist_agent_jobs_offpeak dry_run=${DRY_RUN} ==="
log "PROJ=${PROJ}"

# --- Load approved environment files safely (never print secret values) ---
if [[ -f "${HOME}/.config/tradeai/agent-operator.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.config/tradeai/agent-operator.env"
  set +a
  log "env_loaded=agent-operator.env"
fi

RUN_ENV="${TRADEAI_RUN_ENV_PATH:-/run/user/$(id -u)/tradeai/env}"
if [[ -f "$RUN_ENV" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$RUN_ENV"
  set +a
  log "env_loaded=${RUN_ENV}"
fi

cd "$PROJ"
export PYTHONPATH="${PROJ}/scripts${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$PY" ]]; then
  log "failure: PY not executable path=${PY}"
  log "exit=2"
  exit 2
fi

# --- Overnight soak cap (this wrapper only; do not skip require_global globally) ---
set +e
CAP_OUT="$("$PY" "$PROJ/scripts/lib/deepseek_offpeak.py" --resolve-cap 2>/dev/null)"
CAP_RC=$?
set -e
if [[ "$CAP_RC" -ne 0 ]]; then
  log "failure: LLM_GLOBAL_DAILY_USD_CAP malformed (fail-closed)"
  log "exit=2"
  exit 2
fi
if [[ "$CAP_OUT" == origin=soak* ]]; then
  export LLM_GLOBAL_DAILY_USD_CAP="$SOAK_DEFAULT"
  log "SOAK_CAP=2.00 (not measured; overnight lane only)"
else
  log "LLM_GLOBAL_DAILY_USD_CAP_ok=yes (kept)"
fi
# Fail closed if cap still invalid after soak/keep
if ! "$PY" -c 'import math,os,sys; v=float(os.environ["LLM_GLOBAL_DAILY_USD_CAP"]); sys.exit(0 if math.isfinite(v) and v>0 else 1)' 2>/dev/null; then
  log "failure: LLM_GLOBAL_DAILY_USD_CAP still invalid after soak default"
  log "exit=2"
  exit 2
fi

# Require deepseek_tradeai by name without printing its value
if [[ -z "${deepseek_tradeai:-}" ]]; then
  log "failure: deepseek_tradeai missing after env load"
  log "exit=2"
  exit 2
fi
log "deepseek_tradeai=present"

# --- Peak skip (official DeepSeek 01:00-04:00 and 06:00-10:00 UTC) ---
set +e
GATE_OUT="$("$PY" "$PROJ/scripts/lib/deepseek_offpeak.py" --gate 2>/dev/null)"
GATE_RC=$?
set -e
if [[ "$GATE_RC" -eq 10 ]]; then
  log "PEAK_SKIP window=official_deepseek_utc gate=${GATE_OUT}"
  log "exit=0"
  exit 0
fi
if [[ "$GATE_RC" -ne 0 ]]; then
  log "failure: peak gate error rc=${GATE_RC}"
  log "exit=2"
  exit 2
fi
log "window=off-peak gate=${GATE_OUT}"

# Wrapper holds production flock; worker must not double-lock
export AGENT_JOBS_LOCK_HELD_EXTERNALLY=1

if [[ "$TIMEOUT_SPEC" =~ ^[0-9]+$ ]]; then
  if [[ "$TIMEOUT_SPEC" -lt 1 ]]; then
    log "failure: timeout invalid (${TIMEOUT_SPEC})"
    log "exit=2"
    exit 2
  fi
elif [[ "$TIMEOUT_SPEC" != "20m" ]]; then
  log "failure: timeout invalid (${TIMEOUT_SPEC})"
  log "exit=2"
  exit 2
fi

# --- Dry-run: env + peak + lock probe; do not call the real worker ---
if [[ "$DRY_RUN" == "1" ]] || [[ "$DRY_RUN" == "true" ]] || [[ "$DRY_RUN" == "yes" ]]; then
  log "mode=dry_run: env+peak+lock probe only (no worker)"
  set +e
  flock -n -E 99 "$LOCK" "$PY" -c 'import os,sys; sys.exit(0 if os.environ.get("AGENT_JOBS_LOCK_HELD_EXTERNALLY")=="1" else 3)'
  rc=$?
  set -e
  case "$rc" in
    0)
      log "lock_ok=${LOCK}"
      log "lock_held_externally=1"
      log "success: dry_run complete (no worker)"
      ;;
    99)
      log "lock-skip: could not acquire ${LOCK} during dry_run"
      ;;
    3)
      log "failure: AGENT_JOBS_LOCK_HELD_EXTERNALLY not exported to child"
      ;;
    *)
      log "failure: dry_run lock probe exit=${rc}"
      ;;
  esac
  log "exit=${rc}"
  exit "$rc"
fi

# --- Paid path: flock then bounded drain (NOT scheduled-canary) ---
log "mode=offpeak_drain lock=${LOCK} timeout=${TIMEOUT_SPEC} limit=8"

set +e
flock -n -E 99 "$LOCK" timeout "$TIMEOUT_SPEC" "$PY" scripts/process_watchlist_agent_jobs.py --limit 8 \
  >>"$LOG" 2>&1
rc=$?
set -e

case "$rc" in
  0)
    log "success: offpeak drain completed"
    ;;
  99)
    log "lock-skip: another worker holds ${LOCK} (no provider call from this invocation)"
    ;;
  124)
    log "failure: timeout after ${TIMEOUT_SPEC}"
    ;;
  *)
    log "failure: worker exit=${rc}"
    ;;
esac

log "exit=${rc}"
exit "$rc"
