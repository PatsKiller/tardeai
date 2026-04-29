#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/run_continuous-$STAMP.log"
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
source .venv/bin/activate
# Export .env variables so scripts can read them via os.getenv
set -a
source .env 2>/dev/null || true
set +a
{
  python scripts/continuous_runner.py --project-root .
} 2>&1 | tee -a "$LOG_FILE"
