#!/usr/bin/env bash
# Governed, debt-sensitive symbol-thesis acquisition worker (autonomous, recurring).
#
# Cron-safe (no % chars, no multi-command shell):
#
#   17 3 * * 1-5 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/run_governed_symbol_thesis_acquisition.sh >> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/symbol_thesis_acquisition.log 2>&1 # TRADEAI_GOVERNED_WORKER thesis-acquisition-daily
#
# Guarantees (mirrors run_governed_agent_flash_market.sh):
#   - Canonical host containment flag remains on disk (never cleared)
#   - Process-scoped containment override only for this process
#   - RAG-first → acquire → embed → governed Flash synthesis → reconcile → publish
#   - Bounded LLM spend (LLM_GLOBAL_DAILY_USD_CAP + per-run call cap)
#   - Production flock /tmp/tradeai_symbol_thesis_acquisition.lock
#   - Fail closed on missing env / cap / lock / flag
#
set -euo pipefail

# SRC = checkout holding the runner + symbol_thesis_* modules. Self-locating so
# the wrapper works from any checkout (ephemeral worktree or canonical tree).
SRC="${TRADEAI_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# PROJ = canonical deployment tree (venv, .env, data/, DB creds).
PROJ="${TRADEAI_PROJ:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
PY="${PY:-$PROJ/.venv/bin/python}"
LOG="${TRADEAI_GOVERNED_THESIS_LOG:-$PROJ/logs/symbol_thesis_acquisition.log}"
LOCK="${TRADEAI_THESIS_LOCK_PATH:-/tmp/tradeai_symbol_thesis_acquisition.lock}"
FLAG_HOST="${HOME}/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED"
TIMEOUT_SEC="${TRADEAI_GOVERNED_THESIS_TIMEOUT_SEC:-300}"
MAX_LLM="${TRADEAI_GOVERNED_THESIS_MAX_LLM:-3}"
LIMIT="${TRADEAI_GOVERNED_THESIS_LIMIT:-10}"
SYMBOLS="${TRADEAI_GOVERNED_THESIS_SYMBOLS:-}"
DRY_RUN="${TRADEAI_GOVERNED_THESIS_DRY_RUN:-0}"
MARKER_HINT="TRADEAI_GOVERNED_WORKER thesis-acquisition-daily"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

log() {
  echo "$(ts) $*" >>"$LOG"
}

mkdir -p "$(dirname "$LOG")" "$PROJ/logs" 2>/dev/null || true

log "=== start pid=$$ marker=${MARKER_HINT} dry_run=${DRY_RUN} max_llm=${MAX_LLM} limit=${LIMIT} ==="
log "SRC=${SRC}"
log "PROJ=${PROJ}"
log "host_flag_present=$( [[ -f "$FLAG_HOST" ]] && echo yes || echo no )"

# --- Fail closed: canonical containment flag must be present (and stays active) ---
if [[ ! -f "$FLAG_HOST" ]]; then
  log "failure: containment flag missing path=${FLAG_HOST}"
  log "exit=78"
  exit 78
fi

# --- Validate timeout bound ---
if ! [[ "$TIMEOUT_SEC" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT_SEC" -lt 1 ]] || [[ "$TIMEOUT_SEC" -gt 3600 ]]; then
  log "failure: timeout invalid or >3600 (${TIMEOUT_SEC})"
  log "exit=2"
  exit 2
fi

# --- Process-scoped containment override only (host flag untouched) ---
OVERRIDE_FLAG="/tmp/tradeai_symbol_thesis_p0_absent_$$"
if [[ -e "$OVERRIDE_FLAG" ]]; then
  log "failure: containment override path already exists (cannot isolate) path=${OVERRIDE_FLAG}"
  log "exit=78"
  exit 78
fi
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

# Bound per-run Flash spend + calls
export AGENT_FLASH_MAX_CALLS_PER_RUN_TOTAL="${MAX_LLM}"
export AGENT_FLASH_MAX_CALLS_PER_PROCESS="${MAX_LLM}"
export AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN="${AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN:-0.50}"
# Wrapper holds production flock; worker must not double-lock
export AGENT_JOBS_LOCK_HELD_EXTERNALLY=1

cd "$SRC"
export PYTHONPATH="${SRC}:${SRC}/scripts${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$PY" ]]; then
  log "failure: PY not executable path=${PY}"
  log "exit=2"
  exit 2
fi

RUNNER="${SRC}/scripts/run_symbol_thesis_acquisition.py"
if [[ ! -f "$RUNNER" ]]; then
  log "failure: runner missing path=${RUNNER}"
  log "exit=2"
  exit 2
fi

# --- Dry-run / contained probe: no provider work ---
if [[ "$DRY_RUN" == "1" ]] || [[ "$DRY_RUN" == "true" ]] || [[ "$DRY_RUN" == "yes" ]]; then
  log "mode=dry_run: env+lock+containment probe only (no provider)"
  if [[ ! -f "$FLAG_HOST" ]]; then
    log "failure: host flag disappeared during dry_run"
    log "exit=78"
    exit 78
  fi
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

# --- Autonomous path: flock then debt-ordered acquisition ---
log "mode=autonomous debt_ordered=yes rag_first=yes max_llm=${MAX_LLM} limit=${LIMIT} symbols=${SYMBOLS:-<debt-ordered>}"

SYM_ARGS=()
if [[ -n "$SYMBOLS" ]]; then
  SYM_ARGS+=(--symbols "$SYMBOLS")
fi

set +e
flock -n -E 99 "$LOCK" timeout "$TIMEOUT_SEC" "$PY" "$RUNNER" \
  --root "$PROJ" \
  --limit "$LIMIT" \
  --max-llm "$MAX_LLM" \
  "${SYM_ARGS[@]}" \
  --apply \
  >>"$LOG" 2>&1
rc=$?
set -e

case "$rc" in
  0)
    log "success: autonomous acquisition completed"
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
