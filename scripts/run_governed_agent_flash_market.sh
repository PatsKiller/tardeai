#!/usr/bin/env bash
# Governed market-hours agent Flash wrapper (recurring, one call per interval).
#
# Designed for crontab with NO percent characters and NO multi-command shell:
#
#   */15 6-19 * * 1-5 /ABS/scripts/run_governed_agent_flash_market.sh >> /ABS/logs/governed_agent_flash_market.log 2>&1 # TRADEAI_GOVERNED_WORKER market-15m-v2
#
# Guarantees:
#   - Canonical host containment flag remains on disk (never cleared)
#   - Process-scoped containment override only for this process
#   - Exactly one FAST deepseek-v4-flash request via --scheduled-canary
#   - Production flock /tmp/tradeai_watchlist_agent_jobs.lock
#   - Hard timeout <= 180s
#   - Fail closed on missing env / cap / lock / flag
#
set -euo pipefail

PROJ="${PROJ:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
PY="${PY:-$PROJ/.venv/bin/python}"
LOG="${TRADEAI_GOVERNED_MARKET_LOG:-$PROJ/logs/governed_agent_flash_market.log}"
LOCK="${AGENT_JOBS_LOCK_PATH:-/tmp/tradeai_watchlist_agent_jobs.lock}"
FLAG_HOST="${HOME}/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED"
TIMEOUT_SEC="${TRADEAI_GOVERNED_MARKET_TIMEOUT_SEC:-180}"
DRY_RUN="${TRADEAI_GOVERNED_MARKET_DRY_RUN:-0}"
MARKER_HINT="TRADEAI_GOVERNED_WORKER market-15m-v2"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

log() {
  # All timestamps generated inside the wrapper (never in crontab).
  echo "$(ts) $*" >>"$LOG"
}

mkdir -p "$(dirname "$LOG")" "$PROJ/logs" 2>/dev/null || true

log "=== start pid=$$ marker=${MARKER_HINT} dry_run=${DRY_RUN} ==="
log "PROJ=${PROJ}"
log "host_flag_present=$( [[ -f "$FLAG_HOST" ]] && echo yes || echo no )"

# --- Fail closed: canonical containment flag must be present (and stays active) ---
if [[ ! -f "$FLAG_HOST" ]]; then
  log "failure: containment flag missing path=${FLAG_HOST}"
  log "exit=78"
  exit 78
fi
log "host_flag_content=$(tr '\n' ' ' <"$FLAG_HOST" | head -c 200)"

# --- Validate timeout bound ---
if ! [[ "$TIMEOUT_SEC" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT_SEC" -lt 1 ]] || [[ "$TIMEOUT_SEC" -gt 180 ]]; then
  log "failure: timeout invalid or >180 (${TIMEOUT_SEC})"
  log "exit=2"
  exit 2
fi

# --- Process-scoped containment override only (host flag untouched) ---
OVERRIDE_FLAG="/tmp/tradeai_agent_jobs_p0_market_absent_$$"
if [[ -e "$OVERRIDE_FLAG" ]]; then
  log "failure: containment override path already exists (cannot isolate) path=${OVERRIDE_FLAG}"
  log "exit=78"
  exit 78
fi
# Ensure path stays absent so evaluate_containment treats process as not flagged.
export AGENT_JOBS_P0_CONTAINED=0
export AGENT_JOBS_P0_CONTAINMENT_FLAG="$OVERRIDE_FLAG"
if [[ -e "$AGENT_JOBS_P0_CONTAINMENT_FLAG" ]]; then
  log "failure: override flag path still present after export"
  log "exit=78"
  exit 78
fi
log "containment_override=process-scoped flag_path=${OVERRIDE_FLAG} (absent)"

# --- Load approved environment files safely (never print secret values) ---
if [[ -f "${HOME}/.config/tradeai/agent-operator.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.config/tradeai/agent-operator.env"
  set +a
  log "env_loaded=agent-operator.env"
fi

# Default production runtime env; tests may set TRADEAI_RUN_ENV_PATH to a missing path.
RUN_ENV="${TRADEAI_RUN_ENV_PATH:-/run/user/$(id -u)/tradeai/env}"
if [[ -f "$RUN_ENV" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$RUN_ENV"
  set +a
  log "env_loaded=${RUN_ENV}"
fi

# Require deepseek_tradeai by name without printing its value
if [[ -z "${deepseek_tradeai:-}" ]]; then
  log "failure: deepseek_tradeai missing after env load"
  log "exit=2"
  exit 2
fi
log "deepseek_tradeai=present"

# Require and numerically validate LLM_GLOBAL_DAILY_USD_CAP (no silent default)
if [[ -z "${LLM_GLOBAL_DAILY_USD_CAP:-}" ]]; then
  log "failure: LLM_GLOBAL_DAILY_USD_CAP missing"
  log "exit=2"
  exit 2
fi
if ! "$PY" -c 'import os,sys; v=float(os.environ["LLM_GLOBAL_DAILY_USD_CAP"]); sys.exit(0 if v>0 else 1)' 2>/dev/null; then
  log "failure: LLM_GLOBAL_DAILY_USD_CAP not a positive number"
  log "exit=2"
  exit 2
fi
log "LLM_GLOBAL_DAILY_USD_CAP_ok=yes"

# Hard one-call caps for this invocation
export AGENT_FLASH_MAX_CALLS_PER_RUN_TOTAL=1
export AGENT_FLASH_MAX_CALLS_PER_PROCESS=1
export AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN="${AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN:-0.05}"
# Wrapper holds production flock; worker must not double-lock
export AGENT_JOBS_LOCK_HELD_EXTERNALLY=1

cd "$PROJ"
export PYTHONPATH="${PROJ}/scripts${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$PY" ]]; then
  log "failure: PY not executable path=${PY}"
  log "exit=2"
  exit 2
fi

# --- Dry-run / contained probe: no provider work ---
if [[ "$DRY_RUN" == "1" ]] || [[ "$DRY_RUN" == "true" ]] || [[ "$DRY_RUN" == "yes" ]]; then
  log "mode=dry_run: env+lock+containment probe only (no provider)"
  # Re-verify host flag still present
  if [[ ! -f "$FLAG_HOST" ]]; then
    log "failure: host flag disappeared during dry_run"
    log "exit=78"
    exit 78
  fi
  # Acquire lock briefly then release; prove overlap path exists
  if ! flock -n -E 99 "$LOCK" bash -c 'echo held > /dev/null'; then
    log "lock-skip: could not acquire ${LOCK} during dry_run"
    log "exit=99"
    exit 99
  fi
  log "lock_ok=${LOCK}"
  log "host_flag_still_present=yes"
  log "success: dry_run complete (no provider)"
  log "exit=0"
  exit 0
fi

# Contained probe mode: do not use process override — prove fail-closed exit 78
if [[ "${TRADEAI_GOVERNED_MARKET_CONTAINED_PROBE:-0}" == "1" ]]; then
  log "mode=contained_probe: dropping process override; expect exit 78"
  unset AGENT_JOBS_P0_CONTAINED || true
  export AGENT_JOBS_P0_CONTAINMENT_FLAG="$FLAG_HOST"
  unset AGENT_JOBS_LOCK_HELD_EXTERNALLY || true
  set +e
  flock -n -E 99 "$LOCK" timeout "$TIMEOUT_SEC" "$PY" scripts/process_watchlist_agent_jobs.py \
    --scheduled-canary \
    --limit 1 \
    --max-provider-calls 1 \
    --process-id watchlist_maria_flash_narrative \
    >>"$LOG" 2>&1
  rc=$?
  set -e
  log "contained_probe_exit=${rc}"
  if [[ -f "$FLAG_HOST" ]]; then
    log "host_flag_still_present=yes"
  else
    log "host_flag_still_present=no"
  fi
  log "exit=${rc}"
  exit "$rc"
fi

# --- Paid path: flock then one-call scheduled-canary ---
log "mode=scheduled_canary process_id=watchlist_maria_flash_narrative policy=FAST model=deepseek-v4-flash max_jobs=1 max_calls=1"

set +e
flock -n -E 99 "$LOCK" timeout "$TIMEOUT_SEC" "$PY" scripts/process_watchlist_agent_jobs.py \
  --scheduled-canary \
  --limit 1 \
  --max-provider-calls 1 \
  --process-id watchlist_maria_flash_narrative \
  >>"$LOG" 2>&1
rc=$?
set -e

case "$rc" in
  0)
    log "success: scheduled_canary completed"
    ;;
  99)
    log "lock-skip: another worker holds ${LOCK} (no provider call from this invocation)"
    ;;
  78)
    log "failure: contained or containment check failed"
    ;;
  124)
    log "failure: timeout after ${TIMEOUT_SEC}s"
    ;;
  *)
    log "failure: worker exit=${rc}"
    ;;
esac

if [[ -f "$FLAG_HOST" ]]; then
  log "host_flag_still_present=yes"
else
  log "host_flag_still_present=no CRITICAL"
fi

log "exit=${rc}"
exit "$rc"
