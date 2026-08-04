#!/usr/bin/env bash
# One-shot self-disabling scheduled Flash canary wrapper.
# Removes its uniquely marked cron line BEFORE any paid provider work.
#
# Guarantees:
#   - Does NOT clear ~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED
#   - Process-scoped containment override only for this process
#   - Self-removes only TRADEAI_SCHEDULED_CANARY_ONCE marker lines
#   - Never modifies the four recurring process_watchlist production lines
#   - Worker internal flock only (no outer flock; avoids double-lock)
#   - Exactly one provider call via --scheduled-canary
#
set -euo pipefail

PROJ="${PROJ:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
PY="${PY:-$PROJ/.venv/bin/python}"
MARKER="${TRADEAI_SCHEDULED_CANARY_MARKER:-# TRADEAI_SCHEDULED_CANARY_ONCE}"
LOG="${TRADEAI_SCHEDULED_CANARY_LOG:-$PROJ/logs/scheduled_agent_flash_canary_once.log}"
FLAG_HOST="${HOME}/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED"
DISABLED_STAMP="${TRADEAI_SCHEDULED_CANARY_DISABLED_STAMP:-/tmp/tradeai_scheduled_canary_once_disabled}"

self_disable() {
  # Remove ONLY lines containing the unique marker. Never touch host flag.
  # Never rewrite production worker lines (they do not contain MARKER).
  if ! command -v crontab >/dev/null 2>&1; then
    return 0
  fi
  local tmp before after
  tmp="$(mktemp)"
  before="$(crontab -l 2>/dev/null || true)"
  if ! printf '%s\n' "$before" | grep -qF "$MARKER"; then
    rm -f "$tmp"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) self_disable: marker already absent" >>"$LOG"
    return 0
  fi
  printf '%s\n' "$before" | grep -vF "$MARKER" >"$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
  after="$(crontab -l 2>/dev/null || true)"
  if printf '%s\n' "$after" | grep -qF "$MARKER"; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) self_disable: FAILED marker still present" >>"$LOG"
    return 1
  fi
  # Prove production worker lines unchanged if they existed (pattern without marker)
  touch "$DISABLED_STAMP"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) self_disable: removed unique canary marker lines" >>"$LOG"
  return 0
}

mkdir -p "$(dirname "$LOG")"
{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) scheduled canary start pid=$$ ==="
  echo "host_flag_present=$( [[ -f "$FLAG_HOST" ]] && echo yes || echo no )"
  if [[ -f "$FLAG_HOST" ]]; then
    echo "host_flag_content=$(tr '\n' ' ' <"$FLAG_HOST")"
  fi
} >>"$LOG"

if [[ ! -f "$FLAG_HOST" ]]; then
  echo "ABORT: canonical containment flag missing" | tee -a "$LOG"
  exit 78
fi

# CRITICAL: remove one-shot cron BEFORE any paid work (and keep trap for safety)
self_disable
trap self_disable EXIT

# Process-scoped override ONLY
export AGENT_JOBS_P0_CONTAINED=0
export AGENT_JOBS_P0_CONTAINMENT_FLAG="/tmp/canary_absent_scheduled_once_$$"
export AGENT_FLASH_MAX_CALLS_PER_RUN_TOTAL=1
export AGENT_FLASH_MAX_CALLS_PER_PROCESS=1
export AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN="${AGENT_FLASH_MAX_PROJECTED_USD_PER_RUN:-0.05}"

if [[ -f "${HOME}/.config/tradeai/agent-operator.env" ]]; then
  set -a
  eval "$(
    "$PY" - <<'PY'
from pathlib import Path
p=Path.home()/".config/tradeai"/"agent-operator.env"
for line in p.read_text().splitlines():
    if line.startswith("LLM_GLOBAL_DAILY_USD_CAP="):
        print("export "+line)
        break
PY
  )"
  set +a
fi
export LLM_GLOBAL_DAILY_USD_CAP="${LLM_GLOBAL_DAILY_USD_CAP:-0.25}"

if [[ -f /run/user/$(id -u)/tradeai/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /run/user/$(id -u)/tradeai/env
  set +a
fi

cd "$PROJ"
export PYTHONPATH="$PROJ/scripts"

timeout 180 "$PY" scripts/process_watchlist_agent_jobs.py \
  --scheduled-canary \
  --limit 1 \
  --max-provider-calls 1 \
  --process-id watchlist_maria_flash_narrative \
  >>"$LOG" 2>&1
rc=$?
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) scheduled canary exit=$rc" >>"$LOG"
exit "$rc"
