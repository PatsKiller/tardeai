#!/usr/bin/env bash
# market_day_gate.sh — skip execution on weekends and US market holidays.
# Usage in cron:
#   */15 9-16 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh $PY scripts/some_script.py --flags >> logs/some.log 2>&1
#
# Skips are LOGGED (one line into the job's own log), never silent — on 2026-07-03
# (July-4th observed) three gated crons skipped correctly but the empty logs read as
# failures. If the session check itself errors, the gate FAILS OPEN and runs the job:
# gated jobs are read-only data syncs, and a broken checker must not silently halt
# every sync forever.
set -uo pipefail
cd "$(dirname "$0")/.."

session=$(.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from market_session import current_market_session, is_trading_day
print('TRADE' if is_trading_day() else current_market_session())
" 2>&1) || {
    echo "[market_day_gate] $(date +%F\ %T) session check FAILED (${session:0:120}) — failing open, running job"
    exec "$@"
}

case "$session" in
    TRADE)
        exec "$@"
        ;;
    weekend|holiday)
        echo "[market_day_gate] $(date +%F\ %T) skipped: $session"
        exit 0
        ;;
    *)
        echo "[market_day_gate] $(date +%F\ %T) unexpected session '$session' — failing open, running job"
        exec "$@"
        ;;
esac
