#!/usr/bin/env bash
# Options monitor — proposals + open-position refresh (market hours).
# Cron: every 10 min 9:35–16:05 ET weekdays (see crontab_backup.txt).
set -euo pipefail
PROJECT_ROOT="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"
set -a
source "$PROJECT_ROOT/.env" 2>/dev/null || true
set +a
exec bash scripts/safe_flock.sh /tmp/tradeai_options_monitor.lock \
  .venv/bin/python scripts/run_options_monitor.py >> logs/options_monitor.log 2>&1