#!/bin/bash
# Trade AI docs → Google Drive sync via gog CLI.
# One-way push: MS-01 is authoritative, Drive is read-only mirror.
# Cron: hourly at :05
#
# NEVER syncs: .env, state files, credentials, logs, secrets.

set -euo pipefail

export GOG_KEYRING_PASSWORD=$(cat /home/johnclaw/.openclaw/credentials/gog_keyring_password)
GOG_ACCOUNT="john@jwwhiting.com"
DRIVE_FOLDER_ID="1oL_OxjCF-q1pq9c-8GCa8YS3TFeQOv41"
SRC="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG="/home/johnclaw/logs/drive-sync.log"
MANIFEST="/home/johnclaw/.local/state/drive-sync-manifest.txt"

mkdir -p "$(dirname "$LOG")" "$(dirname "$MANIFEST")"
touch "$MANIFEST"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" >> "$LOG"; }
log "=== sync start ==="

# Build file list from docs/ and config/strategies/
CANDIDATES=$(mktemp)
find "$SRC/docs" -type f \
  ! -path "*/state/*" \
  ! -path "*/.git/*" \
  ! -path "*/__pycache__/*" \
  ! -name "*.pyc" ! -name "*.log" ! -name "*.sql" \
  ! -name "*.tar.gz" ! -name "*.zip" \
  ! -name ".env*" ! -name "*.key" ! -name "*.pem" ! -name "*.token" \
  ! -path "*credentials*" ! -path "*secret*" ! -path "*password*" \
  ! -name "holdings*.json" ! -name "portfolio*.json" \
  >> "$CANDIDATES"

find "$SRC/config/strategies" -name "*.yaml" -type f >> "$CANDIDATES"

# Add .env.example if it exists
[ -f "$SRC/.env.example" ] && echo "$SRC/.env.example" >> "$CANDIDATES"

TOTAL=$(wc -l < "$CANDIDATES")
UPLOADED=0
SKIPPED=0

while IFS= read -r filepath; do
  # Compute hash for delta detection
  hash=$(sha256sum "$filepath" | cut -d' ' -f1)
  relpath="${filepath#$SRC/}"

  # Check manifest (skip if unchanged)
  if grep -qF "$relpath|$hash" "$MANIFEST" 2>/dev/null; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # Content scan — reject files with credential patterns
  if head -c 8192 "$filepath" | grep -qEa 'sk-[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[a-zA-Z0-9]{36}|[0-9]{8,10}:[a-zA-Z0-9_-]{30,}'; then
    log "SKIPPED (content scan): $relpath"
    continue
  fi

  # Upload via gog
  if gog drive upload "$filepath" --account "$GOG_ACCOUNT" --parent "$DRIVE_FOLDER_ID" --no-input 2>>"$LOG"; then
    # Update manifest
    grep -v "^$relpath|" "$MANIFEST" > "${MANIFEST}.tmp" 2>/dev/null || true
    echo "$relpath|$hash" >> "${MANIFEST}.tmp"
    mv "${MANIFEST}.tmp" "$MANIFEST"
    UPLOADED=$((UPLOADED + 1))
  else
    log "FAILED: $relpath"
  fi

  # Rate limit: 0.5s between uploads to avoid API throttle
  sleep 0.5
done < "$CANDIDATES"

rm -f "$CANDIDATES"
log "sync done: $UPLOADED uploaded, $SKIPPED unchanged, $TOTAL total candidates"
