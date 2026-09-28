#!/usr/bin/env bash
set -euo pipefail
# 2026-09-28 (audit C-02): the continuous scanner ran from the DEV tree while every cron lane ran from
# CURRENT. PROJECT_ROOT now derives from this launcher's own location (env override wins), so the
# unit can point at the served release; the shared venv is used because releases ship no .venv.
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VENV_DIR="${TRADEAI_VENV:-${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv}"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/run_continuous-$STAMP.log"
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then source "$PROJECT_ROOT/.venv/bin/activate"; else source "$VENV_DIR/bin/activate"; fi
# Export .env variables so scripts can read them via os.getenv
set -a
source .env 2>/dev/null || true
set +a
# Gate: run preflight check before starting (non-fatal — informational only)
echo "[gate] Running preflight check..."
python scripts/system_preflight_check.py 2>&1 | tee -a "$LOG_DIR/preflight-$STAMP.log" || echo "[gate] Preflight had warnings — continuing anyway"
echo "[gate] Preflight complete. Starting Trade AI..."
{
  python scripts/continuous_runner.py --project-root .
} 2>&1 | tee -a "$LOG_FILE"
