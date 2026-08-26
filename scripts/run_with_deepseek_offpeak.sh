#!/usr/bin/env bash
# PEAK_SKIP wrapper for DeepSeek bulk jobs.
#
# Default --gate: official UTC peaks OR outside 10:00–21:00 America/New_York
#   (same policy as run_watchlist_agent_jobs_offpeak.sh).
# --official: skip only official DeepSeek peak hours (01:00–04:00 and 06:00–10:00 UTC).
#
# Exit 0 on PEAK_SKIP. Does not retune hermes-autonomous-loop.timer.
# READ_ONLY_ADVISORY. No broker / order / stop / 2FA.
set -euo pipefail

GATE="--gate"
if [[ "${1:-}" == "--official" ]]; then
  GATE="--gate-official"
  shift
fi
if [[ "${1:-}" == "--" ]]; then
  shift
fi
if [[ "$#" -lt 1 ]]; then
  echo "usage: run_with_deepseek_offpeak.sh [--official] -- <command>..." >&2
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
if [[ "$rc" -eq 10 ]]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) PEAK_SKIP gate=${GATE}"
  exit 0
fi
if [[ "$rc" -ne 0 ]]; then
  echo "deepseek offpeak gate failed rc=${rc}" >&2
  exit "$rc"
fi
exec "$@"
