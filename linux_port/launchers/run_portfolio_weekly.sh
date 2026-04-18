#!/bin/bash
# ============================================================
#  Portfolio Intelligence - Weekly Technical Scan (Linux)
#  Cron: 0 20 * * 0 /path/to/launchers/run_portfolio_weekly.sh
#  Runs every Sunday at 8:00 PM ET
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || exit 1
source venv/bin/activate

echo ""
echo "============================================================"
echo " Portfolio Intelligence - Weekly Technical Scan"
echo " $(date)"
echo "============================================================"
echo ""

python3 scripts/portfolio_orchestrator.py --project-root . --run-label weekly --run-type weekly

echo ""
echo "Weekly scan complete."
