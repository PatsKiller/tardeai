#!/bin/bash
# Trade AI docs → Google Drive sync.
# One-way push: MS-01 is authoritative, Drive is read-only mirror.
# Requires: rclone remote "gdrive-tradeai" configured with drive.file scope.

set -euo pipefail

SRC=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
DEST=gdrive-tradeai:trade-ai-docs
LOG=/home/johnclaw/logs/docs-sync.log

mkdir -p "$(dirname "$LOG")"

# Sync docs tree (excludes sensitive/generated files)
rclone sync \
  "$SRC/docs/" \
  "$DEST/docs/" \
  --exclude "**/state/**" \
  --exclude "**/.git/**" \
  --exclude "**/__pycache__/**" \
  --exclude "*.pyc" \
  --exclude "*.log" \
  --exclude "*.sql" \
  --exclude "*.tar.gz" \
  --exclude "*.zip" \
  --exclude ".env*" \
  --exclude "*.key" \
  --exclude "*.pem" \
  --exclude "*.token" \
  --exclude "**/credentials*" \
  --exclude "**/*secret*" \
  --exclude "**/*password*" \
  --exclude "holdings*.json" \
  --exclude "portfolio*.json" \
  --log-file="$LOG" \
  --log-level INFO

# Sync strategy YAMLs (non-secret config)
rclone sync \
  "$SRC/config/strategies/" \
  "$DEST/config-strategies/" \
  --include "*.yaml" \
  --log-file="$LOG" \
  --log-level INFO

# Sync .env.example (sanitized template)
if [ -f "$SRC/.env.example" ]; then
  rclone copy "$SRC/.env.example" "$DEST/" --log-file="$LOG" --log-level INFO
fi

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] sync OK" >> "$LOG"
