#!/usr/bin/env bash
# non_trading_hours_gate.sh — run a job ONLY outside the regular US equity session.
#
# Research Intelligence content production must not compete with the trading desk
# during RTH (09:30–16:00 ET on trading days). Allowed sessions:
#   afterhours | closed | weekend | holiday
# Blocked:
#   regular | premarket
#
# Usage:
#   bash scripts/non_trading_hours_gate.sh .venv/bin/python scripts/foo.py --apply
#
# On session-check failure: FAIL CLOSED (skip) — safer for LLM-heavy overnight work
# than running mid-session and starving scalp/proposal paths.
set -uo pipefail
cd "$(dirname "$0")/.."

session=$(.venv/bin/python -c "
import sys
sys.path.insert(0, 'scripts')
from market_session import current_market_session
print(current_market_session())
" 2>&1) || {
    echo "[non_trading_hours_gate] $(date +%F\ %T) session check FAILED (${session:0:120}) — skipping job"
    exit 0
}

case "$session" in
    afterhours|closed|weekend|holiday)
        echo "[non_trading_hours_gate] $(date +%F\ %T) session=$session — running"
        exec "$@"
        ;;
    regular|premarket)
        echo "[non_trading_hours_gate] $(date +%F\ %T) skipped: session=$session (RI updates overnight / after close only)"
        exit 0
        ;;
    *)
        echo "[non_trading_hours_gate] $(date +%F\ %T) unexpected session '$session' — skipping"
        exit 0
        ;;
esac
