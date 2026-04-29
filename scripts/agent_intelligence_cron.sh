#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
MODE="${1:-daily}"
cd "$PROJECT_DIR"
mkdir -p logs
LOG="logs/agent_intelligence_${MODE}_$(date +%Y%m%d_%H%M%S).log"
{
  echo "[agent-intel-cron] mode=$MODE started=$(date -Is)"
  python3 scripts/asset_intelligence_pipeline.py --json || true
  python3 scripts/proactive_discovery.py --json || true
  python3 scripts/watchlist_review.py --json || true
  if [ "$MODE" = "deep" ]; then
    python3 scripts/refresh_agent_context.py --mode deep --json || true
  else
    python3 scripts/refresh_agent_context.py --mode audit --json || true
  fi
  echo "[agent-intel-cron] finished=$(date -Is)"
} | tee "$LOG"
