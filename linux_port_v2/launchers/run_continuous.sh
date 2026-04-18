#!/bin/bash
# ============================================================
#  Trade AI v12.1d - Continuous Runner Launcher (Linux)
#  Cron: 0 4 * * 1-5 /path/to/launchers/run_continuous.sh
#
#  Schedule (all ET — adjust TZ in .env):
#    4:00-7:00 AM  LIVE cycles every 15 min
#    7:00 AM       FULL run (primary pre-market)
#    8:00 AM       FULL run (90-min-to-open)
#    9:00 AM       FULL run (30-min-to-open)
#    9:30 AM       FULL run (market open)
#    10:00 AM      FULL run (first-hour pivot)
#    10:30 AM      Auto-shutdown
# ============================================================

# Resolve project root (one level up from launchers/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || exit 1

# Activate virtual environment
source venv/bin/activate

# Run continuous pipeline
python3 scripts/continuous_runner.py --project-root .
