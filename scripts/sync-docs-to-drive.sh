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
export GOG_ACCOUNT="${GOG_ACCOUNT:-john@jwwhiting.com}"
# Default account for gog (alias "default") — never call `gog auth manage` from cron (hangs without TTY).
gog auth alias set default "$GOG_ACCOUNT" --no-input >/dev/null 2>&1 || true
DRIVE_FOLDER_ID="1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR"  # Trade_AI_Docs_v2 (structured)
# Canonical docs/ under Trade_AI_Docs_v2. Duplicate 1Rb6qcu… is deprecated.
CANONICAL_DOCS_ID="1BMxbxU9c9rF3NBvXVQtVEewdvkifVkwP"
CANONICAL_OPS_ID="1a7vr2gnNipfaFejjgHxKNhSFmnh_XVZ_"
RESULT_JSON="/home/johnclaw/.local/state/drive-sync-last-result.json"
# Pin to CURRENT (promoted SHA). Do not sync a stale rebuild feature branch.
# Override with TRADEAI_DOCS_SRC if you intentionally push a worktree.
SRC="${TRADEAI_DOCS_SRC:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
if [[ ! -d "$SRC/docs" ]]; then
  echo "docs SRC missing: $SRC/docs" >&2
  exit 1
fi
LOG="/home/johnclaw/logs/drive-sync.log"
MANIFEST="/home/johnclaw/.local/state/drive-sync-manifest.txt"
FOLDER_CACHE="/home/johnclaw/.local/state/drive-folder-cache.txt"
IDMAP="/home/johnclaw/.local/state/drive-sync-ids.txt"  # relpath|drive_file_id — update in place, no dupes

mkdir -p "$(dirname "$LOG")" "$(dirname "$MANIFEST")" "$(dirname "$RESULT_JSON")"
touch "$MANIFEST" "$FOLDER_CACHE" "$IDMAP"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" >> "$LOG"; }

write_result() {
  local status="$1" uploaded="${2:-0}" skipped="${3:-0}" failed="${4:-0}" extra="${5:-}"
  python3 - "$RESULT_JSON" "$status" "$uploaded" "$skipped" "$failed" "$extra" <<'PY'
import json, sys, os
from datetime import datetime, timezone
path, status, uploaded, skipped, failed, extra = sys.argv[1:7]
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
prev = {}
try:
    prev = json.loads(open(path, encoding="utf-8").read())
except Exception:
    prev = {}
src = extra or ""
pin = None
try:
    p = os.path.join(src, "SOURCE_COMMIT")
    if os.path.isfile(p):
        pin = open(p, encoding="utf-8").read().strip().split()[0]
except Exception:
    pin = None
main_sha = None
try:
    import subprocess
    main_sha = subprocess.check_output(
        ["git", "-C", "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
         "rev-parse", "origin/main"],
        text=True, timeout=15,
    ).strip()
except Exception:
    main_sha = None
source_status = "ok"
if pin and main_sha and pin != main_sha:
    source_status = "DEGRADED_STALE_SOURCE"
rec = {
    "status": status,
    "started_utc": prev.get("started_utc") if status != "running" else now,
    "finished_utc": None if status == "running" else now,
    "uploaded": int(uploaded or 0),
    "skipped": int(skipped or 0),
    "failed": int(failed or 0),
    "exit_code": 0 if status == "running" else (1 if status != "done" or int(failed or 0) else 0),
    "account": os.environ.get("GOG_ACCOUNT") or "john@jwwhiting.com",
    "canonical_docs_id": "1BMxbxU9c9rF3NBvXVQtVEewdvkifVkwP",
    "src": src,
    "source_commit": pin,
    "origin_main": main_sha,
    "source_status": source_status,
    "targeted_replace_until": "2026-08-27",
    "reads_raw": True,
}
if status == "running":
    rec["started_utc"] = now
    rec["finished_utc"] = None
json.dump(rec, open(path, "w", encoding="utf-8"), indent=2)
open(path, "a", encoding="utf-8").write("\n")
PY
}

# Pin folder cache to the canonical docs/ + docs/ops IDs so the hourly job
# does not keep writing into the duplicate 1Rb6qcu… tree.
pin_canonical_folder_cache() {
  python3 - "$FOLDER_CACHE" "$CANONICAL_DOCS_ID" "$CANONICAL_OPS_ID" <<'PY'
import sys
from pathlib import Path
path, docs_id, ops_id = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out = []
seen_docs = seen_ops = False
for ln in lines:
    if ln.startswith("docs|"):
        out.append(f"docs|{docs_id}")
        seen_docs = True
    elif ln.startswith("docs/ops|"):
        out.append(f"docs/ops|{ops_id}")
        seen_ops = True
    else:
        out.append(ln)
if not seen_docs:
    out.insert(0, f"docs|{docs_id}")
if not seen_ops:
    out.append(f"docs/ops|{ops_id}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

UPLOADED=0
SKIPPED=0
FAILED=0
LIVE_OK="$(mktemp)"
LIVE_BAD="$(mktemp)"
trap 'write_result failed "${UPLOADED:-0}" "${SKIPPED:-0}" "${FAILED:-0}" "$SRC"; rm -f "$LIVE_OK" "$LIVE_BAD"' ERR
trap 'rm -f "$LIVE_OK" "$LIVE_BAD"' EXIT

folder_id_alive() {
  local id="$1"
  grep -qx "$id" "$LIVE_OK" 2>/dev/null && return 0
  grep -qx "$id" "$LIVE_BAD" 2>/dev/null && return 1
  if timeout 20 gog drive ls --account "$GOG_ACCOUNT" --parent "$id" --max=1 --json --no-input >/dev/null 2>&1; then
    echo "$id" >> "$LIVE_OK"
    return 0
  fi
  echo "$id" >> "$LIVE_BAD"
  return 1
}

drop_folder_cache_line() {
  local dir_path="$1"
  grep -v "^${dir_path}|" "$FOLDER_CACHE" > "${FOLDER_CACHE}.new" 2>/dev/null || touch "${FOLDER_CACHE}.new"
  mv "${FOLDER_CACHE}.new" "$FOLDER_CACHE"
}

purge_dead_archive_cache() {
  # Drop cache + manifest lines for archived trees. Those parent IDs 404;
  # retrying them every hour is the 1230-fail lie.
  python3 - "$FOLDER_CACHE" "$MANIFEST" <<'PY'
import sys
from pathlib import Path
cache, manifest = Path(sys.argv[1]), Path(sys.argv[2])
import re
year_dir = re.compile(r"20\d{2}")
def keep(line: str) -> bool:
    low = line.replace("\\", "/")
    if any(n in low for n in (
        "/_archive/", "docs/_archive|", "/_trash/", "docs/_trash|",
        "/_findings/", "docs/_findings|", "/ui_review/", "docs/ui_review|",
    )):
        return False
    # Dated first-level docs dirs are session dumps with dead Drive parents.
    # Keep docs/ops/SESSION_* (year is in the filename, not the folder).
    parts = low.split("|", 1)[0].split("/")
    if len(parts) >= 2 and parts[0] == "docs" and year_dir.search(parts[1] or ""):
        return False
    return True
for path in (cache, manifest):
    if not path.exists():
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [ln for ln in lines if keep(ln)]
    if len(out) != len(lines):
        path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
        print(f"purged {len(lines)-len(out)} lines from {path}")
PY
}

log "=== sync start ==="
pin_canonical_folder_cache
purge_dead_archive_cache
write_result running 0 0 0 "$SRC"
log "SRC=$SRC"

# ── Runtime-dump exclusion ──
# Hermes drain/runtime payloads and snapshot JSON dumps under docs/hermes/** are NOT project
# documentation — they should not mirror into the curated Trade_AI_Docs_v2 Drive folder.
# Curated Hermes markdown (architecture docs, *_report.md) is intentionally NOT matched here.
# (bash `case` globs match across '/', so `*` spans path segments.)
is_runtime_dump_excluded() {
  local rel="$1"
  case "$rel" in
    docs/_archive/*|docs/_trash/*|docs/_findings/*)            return 0 ;;  # dead Drive parents / scratch shots
    docs/ui_review/*)                                          return 0 ;;  # UI screenshot dumps, dead parents
    docs/*_20[0-9][0-9][0-9][0-9][0-9][0-9]_*)                 return 0 ;;  # compact dated dumps
    docs/*20[0-9][0-9]*/*)                                     return 0 ;;  # first-level docs dir with a year
    docs/*/*20[0-9][0-9]*/*)                                   return 0 ;;  # nested dated dump dirs
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
    if folder_id_alive "$cached"; then
      echo "$cached"
      return
    fi
    log "STALE folder cache $dir_path ($cached) — dropping"
    drop_folder_cache_line "$dir_path"
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
      if folder_id_alive "$mid_cached"; then
        current_parent="$mid_cached"
        continue
      fi
      log "STALE folder cache $built_path ($mid_cached) — dropping"
      drop_folder_cache_line "$built_path"
    fi

    # Search Drive for existing folder
    local found_id
    # 2026-09-01: this returned '' on ANY failure -- a timeout, a transient API
    # error, a parse problem -- and the caller then created a folder. So one bad
    # `ls` minted a DUPLICATE folder with the same name. Two folders named `docs`
    # exist in Trade_AI_Docs_v2 for exactly this reason.
    #
    # Once duplicated, `matches[0]` picked whichever Drive listed first, which is
    # not stable, so uploads alternated between them -- and the delete-before-
    # upload lookup is scoped to ONE target_parent, so it could not see the copy
    # in the sibling. That is the 28 extra copies.
    #
    # Now: LOOKUP_FAILED is distinguished from NOT_FOUND, and a failed lookup
    # ABORTS rather than creating. Existing duplicates are reported as a finding
    # and the selection is left unchanged -- consolidating them is the operator's
    # call, not a side effect of this fix.
    found_id=$(gog drive ls --account "$GOG_ACCOUNT" --parent "$current_parent" --max=1000 --json --no-input 2>/dev/null \
      | python3 -c "
import sys,json
try:
    files=json.load(sys.stdin).get('files',[])
except Exception:
    print('LOOKUP_FAILED'); raise SystemExit(0)
matches=[f for f in files if f.get('name')=='$part' and 'folder' in f.get('mimeType','')]
if not matches:
    print('')
else:
    # Selection is DELIBERATELY UNCHANGED from the previous behaviour. Switching
    # to oldest-wins looked more principled, but the dry run showed it would move
    # uploads from the folder currently holding 111 files to its older sibling --
    # a mass re-upload and 111 orphans, to fix a naming collision. Consolidating
    # duplicate folders is the operator's call (§17), not a side effect of a
    # resolver fix. The collision is REPORTED so it can be decided.
    if len(matches) > 1:
        sys.stderr.write('DUPLICATE_FOLDER name=$part count=%d ids=%s\\n' % (len(matches), ','.join(f['id'] for f in matches)))
    print(matches[0]['id'])
" 2>>"$LOG" || echo "LOOKUP_FAILED")

    if [ "$found_id" = "LOOKUP_FAILED" ]; then
      log "ABORT: folder lookup failed for '$part' under $current_parent — refusing to create a duplicate"
      return 1
    fi

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
        log "WARN: could not create folder $built_path — skip (do not fall back to root)"
        echo ""
        return
      fi
    fi

    # Cache this path
    echo "${built_path}|${current_parent}" >> "$FOLDER_CACHE"
  done

  echo "$current_parent"
}

# ── Folder resolution (find-only, no create) for the cleanup pass ──
# The cleanup pass removes Drive files whose LOCAL source was deleted. Those folders
# are never visited by this run's upload pass (so resolve_folder doesn't cache them)
# and may have been evicted from FOLDER_CACHE by a prior root reset. Walking the path
# with `gog drive ls` (no mkdir) resolves the real Drive parent instead of silently
# defaulting to the sync root and orphaning the file. Returns the folder id, or a
# nonzero status when a path component no longer exists on Drive (the whole subtree
# is already gone — nothing left to prune).
resolve_existing_folder() {
  local dir_path="$1"
  local current_parent="$DRIVE_FOLDER_ID"
  local built_path=""
  local mid_cached found_id
  IFS='/' read -ra PARTS <<< "$dir_path"
  for part in "${PARTS[@]}"; do
    built_path="${built_path:+$built_path/}$part"

    mid_cached=$(grep "^${built_path}|" "$FOLDER_CACHE" 2>/dev/null | head -1 | cut -d'|' -f2 || true)
    if [ -n "$mid_cached" ]; then
      current_parent="$mid_cached"
      continue
    fi

    found_id=$(gog drive ls --account "$GOG_ACCOUNT" --parent "$current_parent" --max=1000 --json --no-input 2>/dev/null \
      | python3 -c "
import sys,json
try:
    fs=json.load(sys.stdin).get('files',[])
    matches=[f['id'] for f in fs if f.get('name')=='$part' and 'folder' in f.get('mimeType','')]
    print(matches[0] if matches else '')
except: print('')
" 2>/dev/null || echo "")

    if [ -n "$found_id" ]; then
      current_parent="$found_id"
      echo "${built_path}|${current_parent}" >> "$FOLDER_CACHE"
    else
      return 1
    fi
  done

  echo "$current_parent"
  return 0
}

# ── Build file list ──
CANDIDATES=$(mktemp)
find "$SRC/docs" -type f \
  ! -path "*/state/*" \
  ! -path "*/.git/*" \
  ! -path "*/__pycache__/*" \
  ! -path "*/_archive/*" \
  ! -path "*/_trash/*" \
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

# Root governance docs. The sweep above is scoped to $SRC/docs, so AGENTS.md —
# the single source of truth for agent behaviour, and the file most edited during
# an incident — had NEVER been synced to Drive. Everything under docs/ went up
# hourly while the document that governs all of it did not.
for _gov in AGENTS.md CLAUDE.md AI_WORK_POLICY.md; do
  [ -f "$SRC/$_gov" ] && echo "$SRC/$_gov" >> "$CANDIDATES"
done

TOTAL=$(wc -l < "$CANDIDATES")
UPLOADED=0
SKIPPED=0
FAILED=0

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
  if [ -z "$target_parent" ]; then
    log "FAILED (no live parent): $relpath"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Upload — convert text files to Google Docs for Drive API readability.
  # BUT Google Docs conversion of large files times out (http2 timeout). Skip
  # conversion above 1 MB and upload raw so the file still mirrors to Drive.
  CONVERT_FLAG=""
  fsize=$(stat -c%s "$filepath" 2>/dev/null || echo 0)
  if [ "$fsize" -le 1048576 ]; then
    case "$filepath" in
      *.md)  CONVERT_FLAG="" ;;   # v1.2.3 P0-2: markdown uploads RAW — byte parity with the repo; Docs conversion destroyed punctuation/placeholders (validator finding)
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
    FAILED=$((FAILED + 1))
  fi

  sleep 0.3
done < "$CANDIDATES"

rm -f "$CANDIDATES"
log "sync done: $UPLOADED uploaded, $SKIPPED unchanged, $FAILED failed, $TOTAL total candidates"
write_result done "$UPLOADED" "$SKIPPED" "$FAILED" "$SRC"

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
    # Resolve the file's parent folder on Drive via the find-only resolver, so a
    # folder that fell out of FOLDER_CACHE (or was never cached) still resolves to
    # its real Drive parent. Previously this only checked the cache and defaulted to
    # the sync root — orphaning any file whose parent was uncached.
    dir_path=$(dirname "$relpath")
    filename=$(basename "$relpath")
    target_parent="$DRIVE_FOLDER_ID"
    if [ "$dir_path" != "." ]; then
      if ! target_parent=$(resolve_existing_folder "$dir_path"); then
        target_parent=""   # parent subtree already gone on Drive → children gone too
      fi
    fi
    # Search for file in target folder (skip if the parent folder is already gone)
    drive_file_id=""
    if [ -n "$target_parent" ]; then
      drive_file_id=$(gog drive ls --account "$GOG_ACCOUNT" --parent "$target_parent" --json --no-input 2>/dev/null \
        | python3 -c "
import sys,json
try:
    files=json.load(sys.stdin).get('files',[])
    matches=[f['id'] for f in files if f.get('name')=='$filename' and 'folder' not in f.get('mimeType','')]
    print(matches[0] if matches else '')
except: print('')
" 2>/dev/null || echo "")
    fi
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
