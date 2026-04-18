#!/bin/bash
# ============================================================
#  Portfolio Intelligence - Daily Run (Linux)
#  Cron: 0 7 * * 1-5 /path/to/launchers/run_portfolio.sh
#  Runs weekdays at 7:00 AM ET
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || exit 1
source venv/bin/activate

python3 scripts/portfolio_orchestrator.py --project-root . --run-label morning --run-type daily
