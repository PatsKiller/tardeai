#!/usr/bin/env bash
# Options paper lifecycle monitor — mark-to-market + Alpaca reconcile (advisory only).
set -euo pipefail
PROJECT_ROOT="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"
set -a
source "$PROJECT_ROOT/.env" 2>/dev/null || true
set +a
mkdir -p logs data/runtime
exec bash scripts/safe_flock.sh /tmp/tradeai_options_paper_monitor.lock \
  .venv/bin/python scripts/options_paper_position_monitor.py --run --json \
  >> logs/options_paper_monitor.log 2>&1