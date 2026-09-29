#!/usr/bin/env bash
# Options monitor — proposals + open-position refresh (market hours).
# Day pull: every 5 min 11:00–15:55 ET weekdays, plus the 16:05 close.
# 9:30–11:00 stays empty so this does not share the scalp GPU window.
# Overnight there is no chain cron. A non-force read outside the regular
# session serves the last snapshot (proposal_cache_serves).
set -euo pipefail
PROJECT_ROOT="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"
set -a
source "$PROJECT_ROOT/.env" 2>/dev/null || true
set +a
exec bash scripts/safe_flock.sh /tmp/tradeai_options_monitor.lock \
  .venv/bin/python scripts/run_options_monitor.py >> logs/options_monitor.log 2>&1