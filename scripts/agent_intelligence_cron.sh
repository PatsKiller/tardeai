#!/usr/bin/env bash
set -euo pipefail
MODE="daily"
DRY_RUN=0
MODE_SET=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    daily|deep|intraday)
      if (( MODE_SET )); then echo "usage: agent_intelligence_cron.sh [daily|deep|intraday] [--dry-run]" >&2; exit 2; fi
      MODE="$arg"; MODE_SET=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
if (( DRY_RUN )); then
  echo "DRY-RUN agent-intelligence-cron-$MODE: would run asset intelligence, proactive discovery, watchlist review and context refresh ($MODE); no child, interpreter, state or writes; inputs NOT_MEASURED"
  exit 0
fi
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_ROOT}"
cd "$PROJECT_DIR"
mkdir -p logs
STATUS=0
step() {
  local label="$1"; shift
  local rc=0
  "$@" || rc=$?
  .venv/bin/python scripts/completion_compound_receipt.py --lane "agent-intelligence-cron-$MODE" --step "$label" --exit "$rc" || true
  if (( rc != 0 )); then STATUS=1; fi
}
LOG="logs/agent_intelligence_${MODE}_$(date +%Y%m%d_%H%M%S).log"
{
  echo "[agent-intel-cron] mode=$MODE started=$(date -Is)"
  step asset-intelligence .venv/bin/python scripts/asset_intelligence_pipeline.py --json
  step proactive-discovery .venv/bin/python scripts/proactive_discovery.py --json
  step watchlist-review .venv/bin/python scripts/watchlist_review.py --json
  if [ "$MODE" = "deep" ]; then
    step context-refresh .venv/bin/python scripts/refresh_agent_context.py --mode deep --json
  else
    step context-refresh .venv/bin/python scripts/refresh_agent_context.py --mode audit --json
  fi
  echo "[agent-intel-cron] finished=$(date -Is)"
} > >(tee "$LOG") 2>&1
.venv/bin/python scripts/completion_compound_receipt.py --lane "agent-intelligence-cron-$MODE" --exit "$STATUS" || true
exit "$STATUS"
