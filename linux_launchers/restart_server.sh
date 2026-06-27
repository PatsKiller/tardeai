#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/restart_server-$STAMP.log"
PID_FILE="$PROJECT_ROOT/logs/portfolio_server.pid"

mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
source .venv/bin/activate

V3_DIR="$PROJECT_ROOT/apps/command-center-v3"
if [ ! -f "$V3_DIR/dist/index.html" ] || [ "$(find "$V3_DIR/src" -newer "$V3_DIR/dist/index.html" -print -quit 2>/dev/null)" ]; then
  echo "Building Command Center v3 (stale or missing dist)..."
  (cd "$V3_DIR" && npm run build) 2>&1
fi

{
  echo "Stopping portfolio server on port 7777..."

  if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" || true)"
    if [ -n "${OLD_PID:-}" ] && ps -p "$OLD_PID" >/dev/null 2>&1; then
      kill "$OLD_PID" || true
      sleep 2
    fi
  fi

  pkill -f "scripts/portfolio_server.py" || true
  sleep 2

  echo "Starting portfolio server..."
  nohup python scripts/portfolio_server.py > "$LOG_DIR/portfolio_server-live.log" 2>&1 &
  NEW_PID=$!
  echo "$NEW_PID" > "$PID_FILE"

  echo "Portfolio server started on port 7777"
  echo "PID: $NEW_PID"
  echo
  echo "Open: http://localhost:7777/reports/command_center.html"
} 2>&1 | tee "$LOG_FILE"
