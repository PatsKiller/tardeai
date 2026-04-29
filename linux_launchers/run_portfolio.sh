#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/run_portfolio-$STAMP.log"
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
source .venv/bin/activate

# Pre-flight: load Gmail keyring credential for unattended gog send (non-blocking)
GOG_KR="$HOME/.openclaw/credentials/gog_keyring_password"
if [ -f "$GOG_KR" ]; then
  GOG_KEYRING_PASSWORD="$(head -1 "$GOG_KR")"
  export GOG_KEYRING_PASSWORD
else
  echo "[DAILY] WARNING: $GOG_KR not found — Gmail digest will be skipped"
fi

{
  echo "[DAILY] Starting Portfolio Intelligence daily run..."
  python scripts/portfolio_orchestrator.py --project-root . --run-label morning --run-type daily
  if [ -f data/portfolios/reports/portfolio_live.html ]; then
    cp data/portfolios/reports/portfolio_live.html reports/portfolio_live.html
  fi
  # Backfill per-account period returns after pipeline
  echo "[DAILY] Updating per-account period returns..."
  python backfill_acct_periods_v3.py || echo "[DAILY] backfill skipped (non-fatal)"
  # Session hygiene FIRST: archive stale/oversized Telegram sessions before SOUL refresh
  # so the next Telegram message gets a clean session + fresh SOUL values
  echo "[DAILY] Running session hygiene..."
  python3 "$HOME/.openclaw/skills/steph-wealth-advisor/scripts/session_hygiene.py" --max-age-hours 12 --max-size-kb 300 || echo "[DAILY] Session hygiene skipped (non-fatal)"
  # Refresh Steph SOUL.md live portfolio section from current holdings.json
  echo "[DAILY] Refreshing Steph SOUL.md..."
  python3 "$HOME/.openclaw/skills/steph-wealth-advisor/scripts/refresh_soul.py" || echo "[DAILY] SOUL refresh skipped (non-fatal)"
  curl -s -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:7777/api/clear-pending >/dev/null 2>&1 || true
} 2>&1 | tee "$LOG_FILE"
