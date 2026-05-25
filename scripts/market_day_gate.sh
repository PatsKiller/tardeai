#!/usr/bin/env bash
# market_day_gate.sh — skip execution on weekends and US market holidays.
# Usage in cron:
#   */15 9-16 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh $PY scripts/some_script.py --flags >> logs/some.log 2>&1
#
# If today is a holiday or weekend, exits 0 silently.
# Otherwise exec's the remaining arguments.
set -euo pipefail
cd "$(dirname "$0")/.."

if .venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from market_session import is_trading_day
sys.exit(0 if is_trading_day() else 1)
" 2>/dev/null; then
    exec "$@"
else
    # Holiday or weekend — skip silently
    exit 0
fi
