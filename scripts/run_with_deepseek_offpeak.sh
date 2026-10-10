#!/usr/bin/env bash
# PEAK_SKIP wrapper for DeepSeek bulk jobs.
#
# Default --gate: official UTC peaks OR outside 10:00–21:00 America/New_York
#   (same policy as run_watchlist_agent_jobs_offpeak.sh).
# --official: skip only official DeepSeek peak hours (01:00–04:00 and 06:00–10:00 UTC).
# --scheduled: skip outside weekdays 09:00–21:00 ET / weekends, and inside official peak (operator rule 2026-09-14).
#
# --defer-in-process (with --scheduled only): for a lane whose every paid call is gated IN PROCESS by
#   lib/llm_deferral (evaluate() before the call; AGENTS.md §12). Out of window the command is NOT skipped:
#   the wrapper prints PEAK_DEFER_IN_PROCESS, exports LLM_DEFER_OFFPEAK=1 and runs it, so the lane writes
#   its own honest receipt (deferred, not blind) and a liveness check on that receipt does not go stale
#   every night. In window it runs as usual, still armed. If lib/llm_deferral cannot be loaded or is not
#   armed, it falls back to the plain PEAK_SKIP below (fail closed: no paid work at peak).
#   Cause 2026-10-10: n8n_failure_diagnosis.py (receipt checked stale at 45 min) could not use this wrapper.
#
# Exit 0 on PEAK_SKIP. Does not retune hermes-autonomous-loop.timer.
# READ_ONLY_ADVISORY. No broker / order / stop / 2FA.
set -euo pipefail

GATE="--gate"
DEFER_IN_PROCESS=0
USAGE="usage: run_with_deepseek_offpeak.sh [--official|--scheduled [--defer-in-process]] -- <command>..."
if [[ "${1:-}" == "--official" ]]; then
  GATE="--gate-official"
  shift
elif [[ "${1:-}" == "--scheduled" ]]; then
  # Operator rule 2026-09-14: scheduled paid work only weekdays 09:00-21:00 ET or weekends, never in the
  # official DeepSeek peak. Put this in front of the command on the crontab line, so manual runs are free.
  GATE="--gate-scheduled"
  shift
  if [[ "${1:-}" == "--defer-in-process" ]]; then
    DEFER_IN_PROCESS=1
    shift
  fi
fi
if [[ "${1:-}" == "--defer-in-process" ]]; then
  # Only --scheduled shares lib/llm_deferral's window (is_scheduled_deepseek_window); refuse anything else.
  echo "--defer-in-process requires --scheduled first; ${USAGE}" >&2
  exit 2
fi
if [[ "${1:-}" == "--" ]]; then
  shift
fi
if [[ "$#" -lt 1 ]]; then
  echo "${USAGE}" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-${TRADEAI_PYTHON:-$ROOT/.venv/bin/python}}"
MODULE="${TRADEAI_OFFPEAK_PY:-$HOME/trade-ai-releases/portfolio-server/CURRENT/scripts/lib/deepseek_offpeak.py}"
if [[ ! -f "$MODULE" ]]; then
  MODULE="$ROOT/scripts/lib/deepseek_offpeak.py"
fi

set +e
"$PY" "$MODULE" "$GATE"
rc=$?
set -e
if [[ "$DEFER_IN_PROCESS" -eq 1 ]]; then
  export LLM_DEFER_OFFPEAK=1
fi
if [[ "$rc" -eq 10 && "$DEFER_IN_PROCESS" -eq 1 ]]; then
  set +e
  "$PY" - "$(dirname "$(dirname "$MODULE")")" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
from lib import llm_deferral
sys.exit(0 if llm_deferral.enabled() else 3)
PYEOF
  drc=$?
  set -e
  if [[ "$drc" -eq 0 ]]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) PEAK_DEFER_IN_PROCESS gate=${GATE}"
    exec "$@"
  fi
  echo "in-process deferral unavailable rc=${drc}; falling back to PEAK_SKIP" >&2
fi
if [[ "$rc" -eq 10 ]]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) PEAK_SKIP gate=${GATE}"
  exit 0
fi
if [[ "$rc" -ne 0 ]]; then
  echo "deepseek offpeak gate failed rc=${rc}" >&2
  exit "$rc"
fi
exec "$@"
