#!/usr/bin/env bash
# Hourly code mirror → Google Drive (Trade_AI_Docs_v2/code_mirror/).
#
# One-way push: MS-01 is authoritative. Drive holds two stable archives:
#   hub_git_snapshot.tar.gz          — git-tracked files from the hub checkout
#   current_production_snapshot.tar.gz — served CURRENT release code tree
#   CODE_MIRROR_STATUS.json          — as_of, SHAs, sizes, hashes
#
# Why archives (not per-file): the hub tree is ~26GB / ~900k files once
# untracked/data/venv are counted; git-tracked alone is ~8.7k files / ~28MB
# gzipped. The existing docs sync already mirrors docs/ hourly.
#
# NEVER syncs: .env, credentials, data/, logs/, .venv, node_modules, secrets.
# Does NOT use `gog … --dry-run` (gog v0.12 uploads anyway — DRIVE_MUTATION_SAFETY.md).
#
# Usage:
#   scripts/sync_code_mirror_to_drive.sh --dry-run   # build + receipt only
#   scripts/sync_code_mirror_to_drive.sh --apply     # upload (mutates Drive)
#
# Cron (PROPOSED — operator install required, AGENTS.md §9.3 / §17):
#   35 * * * * bash …/safe_flock.sh /tmp/code_mirror_drive_sync.lock \
#     bash …/scripts/sync_code_mirror_to_drive.sh --apply \
#     >> /home/johnclaw/logs/code-mirror-drive-sync.log 2>&1

set -euo pipefail

export PATH="/home/johnclaw/.local/bin:$PATH"

MODE=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) MODE="dry-run" ;;
    --apply)   MODE="apply" ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg (use --dry-run or --apply)" >&2
      exit 2
      ;;
  esac
done
if [[ -z "$MODE" ]]; then
  echo "usage: $0 --dry-run | --apply" >&2
  exit 2
fi

HUB_SRC="${TRADEAI_CODE_MIRROR_HUB:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
CUR_LINK="${TRADEAI_CODE_MIRROR_CURRENT:-/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT}"
DRIVE_ROOT_ID="${TRADEAI_CODE_MIRROR_DRIVE_ROOT:-1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR}"  # Trade_AI_Docs_v2
FOLDER_NAME="code_mirror"
ACCOUNT="${GOG_ACCOUNT:-john@jwwhiting.com}"

STATE_DIR="/home/johnclaw/.local/state/code-mirror-drive-sync"
RESULT_JSON="/home/johnclaw/.local/state/code-mirror-drive-sync-last.json"
LOG="${TRADEAI_CODE_MIRROR_LOG:-/home/johnclaw/logs/code-mirror-drive-sync.log}"
GOG_BIN="${GOG_BIN:-/home/johnclaw/.local/bin/gog}"
KEYRING_FILE="/home/johnclaw/.openclaw/credentials/gog_keyring_password"

HUB_ARCHIVE_NAME="hub_git_snapshot.tar.gz"
CUR_ARCHIVE_NAME="current_production_snapshot.tar.gz"
STATUS_NAME="CODE_MIRROR_STATUS.json"

mkdir -p "$STATE_DIR" "$(dirname "$LOG")" "$(dirname "$RESULT_JSON")"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1" | tee -a "$LOG" >&2; }

die() { log "ERROR: $1"; write_result failed; exit 1; }

write_result() {
  local status="$1"
  python3 - "$RESULT_JSON" "$status" "$MODE" "$STATE_DIR" "$HUB_SRC" "$CUR_LINK" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

path, status, mode, state_dir, hub, cur_link = sys.argv[1:7]
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
prev = {}
try:
    prev = json.loads(Path(path).read_text(encoding="utf-8"))
except Exception:
    prev = {}

def meta(name: str) -> dict:
    p = Path(state_dir) / name
    if not p.is_file():
        return {"present": False, "path": str(p)}
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return {
        "present": True,
        "path": str(p),
        "bytes": p.stat().st_size,
        "sha256": h.hexdigest(),
    }

hub_sha = None
try:
    import subprocess
    hub_sha = subprocess.check_output(
        ["git", "-C", hub, "rev-parse", "HEAD"], text=True, timeout=30
    ).strip()
except Exception:
    hub_sha = None

cur_resolved = None
cur_pin = None
try:
    cur_resolved = str(Path(cur_link).resolve())
    pin_file = Path(cur_resolved) / "SOURCE_COMMIT"
    if pin_file.is_file():
        cur_pin = pin_file.read_text(encoding="utf-8").strip().split()[0]
except Exception:
    pass

rec = {
    "schema": "CodeMirrorDriveSync@v1",
    "status": status,
    "mode": mode,
    "started_utc": prev.get("started_utc") if status == "running" else prev.get("started_utc"),
    "finished_utc": None if status == "running" else now,
    "hub_src": hub,
    "hub_head": hub_sha,
    "current_link": cur_link,
    "current_resolved": cur_resolved,
    "current_source_commit": cur_pin,
    "drive_root_id": os.environ.get("TRADEAI_CODE_MIRROR_DRIVE_ROOT", "1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR"),
    "drive_folder_name": "code_mirror",
    "artifacts": {
        "hub_git_snapshot.tar.gz": meta("hub_git_snapshot.tar.gz"),
        "current_production_snapshot.tar.gz": meta("current_production_snapshot.tar.gz"),
        "CODE_MIRROR_STATUS.json": meta("CODE_MIRROR_STATUS.json"),
    },
}
if status == "running":
    rec["started_utc"] = now
    rec["finished_utc"] = None
elif not rec.get("started_utc"):
    rec["started_utc"] = now

# Preserve upload fields from apply path when present on disk status.
status_path = Path(state_dir) / "CODE_MIRROR_STATUS.json"
if status_path.is_file():
    try:
        st = json.loads(status_path.read_text(encoding="utf-8"))
        rec["upload"] = st.get("upload")
        rec["excludes"] = st.get("excludes")
    except Exception:
        pass

Path(path).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
PY
}

require_sources() {
  [[ -d "$HUB_SRC/.git" ]] || die "hub git missing: $HUB_SRC/.git"
  [[ -d "$CUR_LINK" ]] || die "CURRENT missing: $CUR_LINK"
  CUR_SRC="$(readlink -f "$CUR_LINK")"
  [[ -d "$CUR_SRC" ]] || die "CURRENT resolve failed: $CUR_LINK"
}

build_hub_archive() {
  local out="$STATE_DIR/$HUB_ARCHIVE_NAME"
  local tmp="$STATE_DIR/.hub_git_snapshot.tar.gz.tmp"
  log "building hub git archive from $HUB_SRC"
  # git archive only ships tracked files — .env and secrets stay out if gitignored.
  if git -C "$HUB_SRC" ls-files --error-unmatch .env >/dev/null 2>&1; then
    die ".env is tracked in hub git — refusing to archive (secret egress)"
  fi
  git -C "$HUB_SRC" archive --format=tar.gz -o "$tmp" HEAD
  mv -f "$tmp" "$out"
  log "hub archive: $(du -h "$out" | cut -f1) ($(stat -c%s "$out") bytes)"
}

build_current_archive() {
  local out="$STATE_DIR/$CUR_ARCHIVE_NAME"
  local tmp="$STATE_DIR/.current_production_snapshot.tar.gz.tmp"
  log "building CURRENT production archive from $CUR_SRC"
  # Do not follow symlinks into persistent-state / data (tar default stores symlink).
  tar -czf "$tmp" \
    --exclude='./.venv' \
    --exclude='./node_modules' \
    --exclude='./data' \
    --exclude='./logs' \
    --exclude='./dist' \
    --exclude='./__pycache__' \
    --exclude='./.git' \
    --exclude='./.pytest_cache' \
    --exclude='./htmlcov' \
    --exclude='./.mypy_cache' \
    --exclude='./.env' \
    --exclude='./.env.*' \
    --exclude='*.pem' \
    --exclude='*.key' \
    --exclude='*.pyc' \
    --exclude='*credentials*' \
    --exclude='*secret*' \
    --exclude='*password*' \
    --exclude='./holdings.json' \
    --exclude='./data/portfolios' \
    -C "$CUR_SRC" .
  mv -f "$tmp" "$out"
  log "current archive: $(du -h "$out" | cut -f1) ($(stat -c%s "$out") bytes)"
}

write_status_json() {
  local hub_sha cur_pin
  hub_sha="$(git -C "$HUB_SRC" rev-parse HEAD)"
  cur_pin=""
  if [[ -f "$CUR_SRC/SOURCE_COMMIT" ]]; then
    cur_pin="$(head -1 "$CUR_SRC/SOURCE_COMMIT" | awk '{print $1}')"
  fi
  python3 - "$STATE_DIR" "$HUB_SRC" "$CUR_SRC" "$hub_sha" "$cur_pin" "$MODE" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

state, hub, cur, hub_sha, cur_pin, mode = sys.argv[1:7]

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

arts = {}
for name in (
    "hub_git_snapshot.tar.gz",
    "current_production_snapshot.tar.gz",
):
    p = Path(state) / name
    arts[name] = {"bytes": p.stat().st_size, "sha256": sha(p)}

doc = {
    "schema": "CodeMirrorDriveSyncStatus@v1",
    "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "mode": mode,
    "hub_src": hub,
    "hub_head": hub_sha,
    "current_resolved": cur,
    "current_source_commit": cur_pin or None,
    "artifacts": arts,
    "excludes": [
        ".env / .env.* / *.pem / *.key",
        ".venv / node_modules / data / logs / dist / __pycache__",
        "credentials|secret|password path segments",
        "hub: git-tracked only (git archive HEAD)",
    ],
    "upload": None,
}
out = Path(state) / "CODE_MIRROR_STATUS.json"
out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(out)
PY
}

ensure_gog_auth() {
  [[ -x "$GOG_BIN" ]] || die "gog missing/executable: $GOG_BIN"
  [[ -f "$KEYRING_FILE" ]] || die "gog keyring password file missing"
  export GOG_KEYRING_PASSWORD
  GOG_KEYRING_PASSWORD="$(cat "$KEYRING_FILE")"
  export GOG_ACCOUNT="$ACCOUNT"
  # Never call `gog auth manage` from cron (hangs without TTY).
  "$GOG_BIN" auth alias set default "$ACCOUNT" --no-input >/dev/null 2>&1 || true
}

resolve_or_create_folder() {
  # Find code_mirror under Trade_AI_Docs_v2; create once if absent.
  local found
  found="$("$GOG_BIN" drive ls --account "$ACCOUNT" --parent "$DRIVE_ROOT_ID" --max=200 --json --no-input 2>>"$LOG" \
    | python3 -c "
import json,sys
files=json.load(sys.stdin).get('files',[])
matches=[f for f in files if f.get('name')=='$FOLDER_NAME' and 'folder' in f.get('mimeType','')]
if len(matches)>1:
    sys.stderr.write('DUPLICATE_FOLDER name=$FOLDER_NAME count=%d\\n' % len(matches))
print(matches[0]['id'] if matches else '')
" 2>>"$LOG" || true)"
  if [[ -n "$found" ]]; then
    echo "$found"
    return
  fi
  log "creating Drive folder $FOLDER_NAME under $DRIVE_ROOT_ID"
  "$GOG_BIN" drive mkdir "$FOLDER_NAME" --account "$ACCOUNT" --parent "$DRIVE_ROOT_ID" --json --no-input 2>>"$LOG" \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(d.get('folder',d).get('id',''))
"
}

delete_existing_named() {
  local parent="$1" name="$2"
  local ids
  ids="$("$GOG_BIN" drive ls --account "$ACCOUNT" --parent "$parent" --max=200 --json --no-input 2>>"$LOG" \
    | python3 -c "
import json,sys
files=json.load(sys.stdin).get('files',[])
for f in files:
    if f.get('name')=='$name' and 'folder' not in f.get('mimeType',''):
        print(f.get('id',''))
" 2>>"$LOG" || true)"
  for fid in $ids; do
    [[ -n "$fid" ]] || continue
    log "delete-before-upload: $name ($fid)"
    "$GOG_BIN" drive rm "$fid" --account "$ACCOUNT" -y --permanent --no-input >>"$LOG" 2>&1 || \
      log "WARN: delete failed for $fid (continuing)"
  done
}

upload_file() {
  local parent="$1" path="$2" name="$3"
  delete_existing_named "$parent" "$name"
  log "uploading $name ($(du -h "$path" | cut -f1))"
  "$GOG_BIN" drive upload "$path" --account "$ACCOUNT" --parent "$parent" --name "$name" --json --no-input >>"$LOG" 2>&1 \
    || die "upload failed: $name"
}

patch_status_upload() {
  local folder_id="$1"
  python3 - "$STATE_DIR/$STATUS_NAME" "$folder_id" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path, folder_id = sys.argv[1:3]
doc = json.loads(Path(path).read_text(encoding="utf-8"))
doc["upload"] = {
    "drive_folder_id": folder_id,
    "uploaded_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "files": [
        "hub_git_snapshot.tar.gz",
        "current_production_snapshot.tar.gz",
        "CODE_MIRROR_STATUS.json",
    ],
}
Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY
}

# ── main ──
log "=== code mirror sync start mode=$MODE ==="
write_result running
require_sources
build_hub_archive
build_current_archive
write_status_json >/dev/null

if [[ "$MODE" == "dry-run" ]]; then
  log "dry-run: archives built; no Drive mutation"
  write_result dry_run_ok
  python3 -c "import json;print(json.dumps(json.load(open('$RESULT_JSON')),indent=2))"
  log "=== code mirror sync dry-run done ==="
  exit 0
fi

# --apply
ensure_gog_auth
FOLDER_ID="$(resolve_or_create_folder)"
[[ -n "$FOLDER_ID" ]] || die "could not resolve/create Drive folder $FOLDER_NAME"
log "Drive folder id=$FOLDER_ID"
upload_file "$FOLDER_ID" "$STATE_DIR/$HUB_ARCHIVE_NAME" "$HUB_ARCHIVE_NAME"
upload_file "$FOLDER_ID" "$STATE_DIR/$CUR_ARCHIVE_NAME" "$CUR_ARCHIVE_NAME"
patch_status_upload "$FOLDER_ID"
upload_file "$FOLDER_ID" "$STATE_DIR/$STATUS_NAME" "$STATUS_NAME"
write_result done
log "=== code mirror sync apply done ==="
python3 -c "import json;print(json.dumps(json.load(open('$RESULT_JSON')),indent=2))"
exit 0
