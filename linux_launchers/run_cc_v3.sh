#!/usr/bin/env bash
set -euo pipefail

# Command Center v3 — rebuild dist when source is newer (served by portfolio_server at /v3/)

PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
APP_DIR="$PROJECT_ROOT/apps/command-center-v3"

cd "$APP_DIR"

if [ ! -f "dist/index.html" ] || [ "$(find src -newer dist/index.html -print -quit 2>/dev/null)" ]; then
  echo "[CC-v3] Building..."
  npm run build 2>&1
else
  echo "[CC-v3] dist is up to date ($(cat dist/build-meta.json 2>/dev/null || echo 'no meta'))"
fi

echo "[CC-v3] Open http://localhost:7777/v3/journal (portfolio server must be running on 7777)"