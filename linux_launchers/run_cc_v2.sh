#!/usr/bin/env bash
set -euo pipefail

# Command Center v2 — production serve on port 7788
# Python HTTP server + proxy to 7777
# Does NOT touch port 7777

PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
APP_DIR="$PROJECT_ROOT/apps/command-center-v2"

cd "$APP_DIR"

# Build if dist is stale or missing
if [ ! -f "dist/index.html" ] || [ "$(find src -newer dist/index.html -print -quit 2>/dev/null)" ]; then
  echo "[CC-v2] Building..."
  npx vite build 2>&1
fi

echo "[CC-v2] Starting Python server on port 7788..."
exec python3 serve.py
