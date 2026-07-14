#!/bin/bash
# Trade AI docs → Google Drive sync via gog CLI.
# One-way push: MS-01 is authoritative, Drive is read-only mirror.
# Cron: hourly at :05
#
# NEVER syncs: .env, state files, credentials, logs, secrets.
# Preserves folder hierarchy on Drive (docs/recovery/... etc.)

set -euo pipefail

# cron runs with a minimal PATH that omits ~/.local/bin, where the gog CLI lives — this made
# the hourly cron sync fail silently ("gog: command not found", 0 uploaded) while interactive
# runs worked. Prepend the absolute dir so gog resolves under cron. (2026-06-04)
export PATH="/home/johnclaw/.local/bin:$PATH"

export GOG_KEYRING_PASSWORD=$(cat /home/johnclaw/.openclaw/credentials/gog_keyring_password)
GOG_ACCOUNT="john@jwwhiting.com"
DRIVE_FOLDER_ID="1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR"  # Trade_AI_Docs_v2 (structured)
SRC="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG="/home/johnclaw/logs/drive-sync.log"
MANIFEST="/home/johnclaw/.local/state/drive-sync-manifest.txt"
FOLDER_CACHE="/home/johnclaw/.local/state/drive-folder-cache.txt"
IDMAP="/home/johnclaw/.local/state/drive-sync-ids.txt"  # relpath|drive_file_id — update in place, no dupes

mkdir -p "$(dirname "$LOG")" "$(dirname "$MANIFEST")"
touch "$MANIFEST" "$FOLDER_CACHE" "$IDMAP"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" >> "$LOG"; }
log "=== sync start ==="

# ── Runtime-dump exclusion ──
# Hermes drain/runtime payloads and snapshot JSON dumps under docs/hermes/** are NOT project
# documentation — they should not mirror into the curated Trade_AI_Docs_v2 Drive folder.
# Curated Hermes markdown (architecture docs, *_report.md) is intentionally NOT matched here.
# (bash `case` globs match across '/', so `*` spans path segments.)
is_runtime_dump_excluded() {
  local rel="$1"
  case "$rel" in
    docs/hermes/phase3b_dryrun/*)                              return 0 ;;  # drain payload dumps
    docs/hermes/backlog_health/*.json)                         return 0 ;;  # snapshot JSON (keep .md)
    docs/hermes/*hermes_auto_ticker_challenger_*_payload.json) return 0 ;;  # nested drain payloads
    docs/hermes/*_payload.json)                                return 0 ;;  # any hermes payload json
    docs/hermes/*latest_*_summary.json)                        return 0 ;;  # latest_* snapshot summaries
  esac
  return 1
}

# ── Folder resolution: get or create a Drive folder for a path ──
# Uses file-based cache: each line is "path|drive_id"
resolve_folder() {
  local dir_path="$1"
  # Check cache first
  local cached
  cached=$(grep "^${dir_path}|" "$FOLDER_CACHE" 2>/dev/null | head -1 | cut -d'|' -f2)
  if [ -n "$cached" ]; then
    echo "$cached"
    return
  fi

  # Walk path components
  local current_parent="$DRIVE_FOLDER_ID"
  local built_path=""
  IFS='/' read -ra PARTS <<< "$dir_path"
  for part in "${PARTS[@]}"; do
    built_path="${built_path:+$built_path/}$part"

    # Check cache for this intermediate path
    local mid_cached
    mid_cached=$(grep "^${built_path}|" "$FOLDER_CACHE" 2>/dev/null | head -1 | cut -d'|' -f2)
    if [ -n "$mid_cached" ]; then
      current_parent="$mid_cached"
      continue
    fi

    # Search Drive for existing folder
    local found_id
    found_id=$(gog drive ls --account "$GOG_ACCOUNT" --parent "$current_parent" --max=1000 --json --no-input 2>/dev/null \
      | python3 -c "
import sys,json
try:
    files=json.load(sys.stdin).get('files',[])
    matches=[f['id'] for f in files if f.get('name')=='$part' and 'folder' in f.get('mimeType','')]
    print(matches[0] if matches else '')
except: print('')
" 2>/dev/null || echo "")

    if [ -n "$found_id" ]; then
      current_parent="$found_id"
    else
      # Create folder
      local new_id
      new_id=$(gog drive mkdir "$part" --account "$GOG_ACCOUNT" --parent "$current_parent" --json --no-input 2>>"$LOG" \
        | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('folder',d).get('id',''))
except: print('')
" 2>/dev/null || echo "")

      if [ -n "$new_id" ]; then
        current_parent="$new_id"
        log "Created folder: $built_path ($new_id)"
      else
        log "WARN: could not create folder $built_path"
        echo "$DRIVE_FOLDER_ID"
        return
      fi
    fi

    # Cache this path
    echo "${built_path}|${current_parent}" >> "$FOLDER_CACHE"
  done

  echo "$current_parent"
}

# ── Build file list ──
CANDIDATES=$(mktemp)
find "$SRC/docs" -type f \
  ! -path "*/state/*" \
  ! -path "*/.git/*" \
  ! -path "*/__pycache__/*" \
  ! -path "*/hermes/phase3b_dryrun/*" \
  ! -path "*/artifacts/*" \
  ! -path "*redeploy_review*" \
  ! -path "*_review_20*/*.png" \
  ! -name "hermes_auto_*_payload.json" \
  ! -name "*.pyc" ! -name "*.log" ! -name "*.sql" \
  ! -name "*.tar.gz" ! -name "*.zip" \
  ! -name ".env*" ! -name "*.key" ! -name "*.pem" ! -name "*.token" \
  ! -path "*credentials*" ! -path "*secret*" ! -path "*password*" \
  ! -name "holdings*.json" ! -name "portfolio*.json" \
  >> "$CANDIDATES"

find "$SRC/config/strategies" -name "*.yaml" -type f >> "$CANDIDATES" 2>/dev/null || true
[ -f "$SRC/.env.example" ] && echo "$SRC/.env.example" >> "$CANDIDATES"

TOTAL=$(wc -l < "$CANDIDATES")
UPLOADED=0
SKIPPED=0

while IFS= read -r filepath; do
  relpath="${filepath#$SRC/}"

  # Skip runtime payload/snapshot dumps (not project docs) — checked before hashing
  if is_runtime_dump_excluded "$relpath"; then
    log "SKIPPED runtime dump: $relpath"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  hash=$(sha256sum "$filepath" | cut -d' ' -f1)

  # Skip if unchanged
  if grep -qF "$relpath|$hash" "$MANIFEST" 2>/dev/null; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # Content scan — reject secrets
  if head -c 8192 "$filepath" | grep -qEa 'sk-[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[a-zA-Z0-9]{36}|[0-9]{8,10}:[a-zA-Z0-9_-]{30,}'; then
    log "SKIPPED (content scan): $relpath"
    continue
  fi

  # Resolve target folder
  dir_path=$(dirname "$relpath")
  if [ "$dir_path" != "." ]; then
    target_parent=$(resolve_folder "$dir_path")
  else
    target_parent="$DRIVE_FOLDER_ID"
  fi

  # Upload — convert text files to Google Docs for Drive API readability.
  # BUT Google Docs conversion of large files times out (http2 timeout). Skip
  # conversion above 1 MB and upload raw so the file still mirrors to Drive.
  CONVERT_FLAG=""
  fsize=$(stat -c%s "$filepath" 2>/dev/null || echo 0)
  if [ "$fsize" -le 1048576 ]; then
    case "$filepath" in
      *.md)  CONVERT_FLAG="--convert-to=doc" ;;
      *.csv) CONVERT_FLAG="--convert-to=sheet" ;;
      *.txt) CONVERT_FLAG="--convert-to=doc" ;;
    esac
  else
    log "LARGE (${fsize}B): $relpath — uploading raw (no Doc conversion)"
  fi
  # ── DELETE-BEFORE-UPLOAD (no duplicate proliferation) ──
  # Google Workspace Docs CANNOT be content-replaced (gog --replace errors: "cannot replace content for
  # Google Workspace files"), and a plain re-upload mints a NEW Doc each run. So: find EVERY existing copy
  # by name in the target folder, trash them, then create one fresh converted Doc. Net result = exactly one
  # current Doc per name. All gog calls are timeout-bounded so a hung call can't stall the whole sync.
  filename=$(basename "$relpath")
  old_ids=$(timeout 45 gog drive ls --account "$GOG_ACCOUNT" --parent "$target_parent" --max=1000 --json --no-input 2>/dev/null \
    | python3 -c "
import sys,json
try: print('\n'.join(f['id'] for f in json.load(sys.stdin).get('files',[]) if f.get('name')=='$filename' and 'folder' not in f.get('mimeType','')))
except: pass
" 2>/dev/null || echo "")
  for oid in $old_ids; do
    timeout 45 gog drive delete "$oid" --account "$GOG_ACCOUNT" --force --no-input >/dev/null 2>>"$LOG" || true
  done

  if timeout 120 gog drive upload "$filepath" --account "$GOG_ACCOUNT" --parent "$target_parent" $CONVERT_FLAG --no-input 2>>"$LOG"; then
    grep -v "^${relpath}|" "$MANIFEST" > "${MANIFEST}.new" 2>/dev/null || touch "${MANIFEST}.new"
    echo "${relpath}|${hash}" >> "${MANIFEST}.new"; mv "${MANIFEST}.new" "$MANIFEST"
    UPLOADED=$((UPLOADED + 1))
    log "SYNCED (delete+create): $relpath"
  else
    log "FAILED: $relpath"
  fi

  sleep 0.3
done < "$CANDIDATES"

rm -f "$CANDIDATES"
log "sync done: $UPLOADED uploaded, $SKIPPED unchanged, $TOTAL total candidates"

# ── Cleanup: remove Drive files whose local source was deleted ──
DELETED=0
if [ -s "$MANIFEST" ]; then
  CLEANUP_MANIFEST=$(mktemp)
  cp "$MANIFEST" "$CLEANUP_MANIFEST"
  while IFS='|' read -r relpath hash; do
    [ -z "$relpath" ] && continue
    local_file="$SRC/$relpath"
    # Remove from Drive if the local source was deleted OR it is now an excluded runtime dump
    # (excluded dumps may still exist locally — they just must not mirror to Drive).
    if [ ! -f "$local_file" ]; then
      log "CLEANUP: $relpath no longer exists locally"
    elif is_runtime_dump_excluded "$relpath"; then
      log "CLEANUP excluded runtime dump: $relpath"
    else
      continue
    fi
    # Find the file on Drive by searching the target folder
    dir_path=$(dirname "$relpath")
    filename=$(basename "$relpath")
    target_parent="$DRIVE_FOLDER_ID"
    if [ "$dir_path" != "." ]; then
      cached_parent=$(grep "^${dir_path}|" "$FOLDER_CACHE" 2>/dev/null | head -1 | cut -d'|' -f2)
      [ -n "$cached_parent" ] && target_parent="$cached_parent"
    fi
    # Search for file in target folder
    drive_file_id=$(gog drive ls --account "$GOG_ACCOUNT" --parent "$target_parent" --json --no-input 2>/dev/null \
      | python3 -c "
import sys,json
try:
    files=json.load(sys.stdin).get('files',[])
    matches=[f['id'] for f in files if f.get('name')=='$filename' and 'folder' not in f.get('mimeType','')]
    print(matches[0] if matches else '')
except: print('')
" 2>/dev/null || echo "")
    if [ -n "$drive_file_id" ]; then
      if gog drive rm "$drive_file_id" --account "$GOG_ACCOUNT" --force --no-input 2>>"$LOG"; then
        log "DELETED from Drive: $relpath ($drive_file_id)"
        DELETED=$((DELETED + 1))
      else
        log "WARN: could not delete $relpath from Drive"
      fi
    fi
    # Remove from manifest
    grep -v "^${relpath}|" "$MANIFEST" > "${MANIFEST}.new" 2>/dev/null || touch "${MANIFEST}.new"
    mv "${MANIFEST}.new" "$MANIFEST"
  done < "$CLEANUP_MANIFEST"
  rm -f "$CLEANUP_MANIFEST"
fi
if [ "$DELETED" -gt 0 ]; then
  log "cleanup done: $DELETED files removed from Drive"
fi
