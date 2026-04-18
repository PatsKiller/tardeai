#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/run_portfolio-$STAMP.log"
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
source .venv/bin/activate
{
  echo "[DAILY] Starting Portfolio Intelligence daily run..."
  python scripts/portfolio_orchestrator.py --project-root . --run-label morning --run-type daily
  if [ -f data/portfolios/reports/portfolio_live.html ]; then
    cp data/portfolios/reports/portfolio_live.html reports/portfolio_live.html
  fi
  # Backfill per-account period returns after pipeline
  echo "[DAILY] Updating per-account period returns..."
  python backfill_acct_periods_v3.py || echo "[DAILY] backfill skipped (non-fatal)"
  curl -s -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:7777/api/clear-pending >/dev/null 2>&1 || true
} 2>&1 | tee "$LOG_FILE"
