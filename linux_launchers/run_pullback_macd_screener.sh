#!/usr/bin/env bash
# Daily S&P 500 pullback + approaching-MACD-cross screener (post-close).
set -euo pipefail
PROJECT_ROOT="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"
exec /usr/bin/flock -n /tmp/tradeai_pullback_macd.lock \
  .venv/bin/python scripts/pullback_macd_screener.py >> logs/pullback_macd_screener.log 2>&1
