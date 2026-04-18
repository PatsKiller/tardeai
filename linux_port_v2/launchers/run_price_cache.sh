#!/bin/bash
# ============================================================
#  Portfolio Price Cache Builder (Linux)
#  Cron: 0 19 * * 0 /path/to/launchers/run_price_cache.sh
#  Runs every Sunday at 7:00 PM ET (before weekly scan at 8PM)
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || exit 1
source venv/bin/activate

echo ""
echo "============================================================"
echo " Building Portfolio Price Cache (Jan 2020 to today)"
echo " This takes 2-5 minutes on first run, ~30s after that."
echo "============================================================"
echo ""

python3 scripts/portfolio_price_cache.py --project-root .

echo ""
echo "Done. Refresh the dashboard to see updated Period Returns."
