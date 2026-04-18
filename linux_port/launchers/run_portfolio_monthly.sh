#!/bin/bash
# ============================================================
#  Portfolio Intelligence - Monthly Run (Linux)
#  Cron: 5 7 1 * * /path/to/launchers/run_portfolio_monthly.sh
#  Runs 1st of every month at 7:05 AM ET
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || exit 1
source venv/bin/activate

python3 scripts/portfolio_orchestrator.py --project-root . --run-label monthly --run-type monthly
