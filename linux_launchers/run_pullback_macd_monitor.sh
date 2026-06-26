#!/usr/bin/env bash
# Pullback/MACD intraday monitor — runs hourly on TRADING DAYS only (market_day_gate skips weekends
# and US holidays). Re-evaluates active candidates + open pullback proposals: refreshes those that
# still fit the plan, expires those that don't, and catches new intraday triggers (VWAP/MACD turn).
set -euo pipefail
PROJECT_ROOT="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"
exec /usr/bin/flock -n /tmp/tradeai_pullback_monitor.lock \
  bash scripts/market_day_gate.sh .venv/bin/python scripts/pullback_macd_screener.py --monitor
