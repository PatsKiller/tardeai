#!/usr/bin/env bash
# Alpaca PAPER options lane — poll fills/closes (read-only; no order submit).
set -euo pipefail
PROJECT_ROOT="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"
set -a
source "$PROJECT_ROOT/.env" 2>/dev/null || true
set +a
mkdir -p logs
exec bash scripts/safe_flock.sh /tmp/tradeai_alpaca_options_reconcile.lock \
  .venv/bin/python scripts/alpaca_paper_options_executor.py --reconcile \
  >> logs/alpaca_paper_options_reconcile.log 2>&1