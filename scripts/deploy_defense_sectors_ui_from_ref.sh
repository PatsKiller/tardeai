#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="DEFENSE_SECTORS_SHADOW_UI_ONLY"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${UI_SOURCE_REF:-}"
readonly LIVE_APP="$HOST_REPO/apps/command-center-v3"
readonly LIVE_DIST="$LIVE_APP/dist"
readonly BACKUP_ROOT=/home/johnclaw/tradeai-deploy-backups/command-center-v3
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly STAGE_ROOT="$(mktemp -d /tmp/defense-sectors-ui-stage.XXXXXX)"
readonly CANDIDATE="${LIVE_DIST}.candidate-${STAMP}"
readonly TAR="$(command -v tar)"
readonly NPM="$(command -v npm)"
readonly NPX="$(command -v npx)"
readonly PYTHON="$(command -v python3)"

OLD_MOVED=0
NEW_INSTALLED=0
cleanup() {
  rm -rf "$STAGE_ROOT" "$CANDIDATE"
  if [[ "$OLD_MOVED" -eq 1 && "$NEW_INSTALLED" -eq 0 && -d "${BACKUP_DIST:-}" && ! -d "$LIVE_DIST" ]]; then
    mv "$BACKUP_DIST" "$LIVE_DIST"
  fi
}
trap cleanup EXIT

if [[ "${UI_DEPLOY_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: UI_DEPLOY_ACK must equal $ACK_REQUIRED" >&2
  exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: UI_SOURCE_REF must be an exact 40-character commit SHA" >&2
  exit 2
fi
if [[ ! -d "$HOST_REPO/.git" ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: repository unavailable: $HOST_REPO" >&2
  exit 2
fi
git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "$RESOLVED_COMMIT" != "$SOURCE_REF" ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: resolved commit differs from exact source ref" >&2
  exit 2
fi
readonly BACKUP_DIR="$BACKUP_ROOT/${STAMP}-${RESOLVED_COMMIT:0:12}"
readonly BACKUP_DIST="$BACKUP_DIR/dist"

for required in "$TAR" "$NPM" "$NPX" "$PYTHON"; do
  if [[ -z "$required" || ! -x "$required" ]]; then
    echo "BLOCKED_UI_DEPLOYMENT: required existing command unavailable" >&2
    exit 2
  fi
done

mkdir -p "$STAGE_ROOT"
git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" apps/command-center-v3 scripts/check_design_tokens.sh scripts/test_chip_scope.mjs \
  | "$TAR" -x -C "$STAGE_ROOT"

readonly STAGED_APP="$STAGE_ROOT/apps/command-center-v3"
cd "$STAGED_APP"
"$NPM" ci
"$NPX" tsc --pretty false
"$NPX" vite build

if [[ ! -f "$STAGED_APP/dist/index.html" ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: Vite output missing index.html" >&2
  exit 4
fi

markers=(
  "Sector decision board"
  "ELIGIBLE NOW"
  "RESEARCH WATCH"
  "AVOID / REDUCE"
  "NO DECISION"
  "model critique only"
  "Review decision"
  "Watch sector"
  "Copy brief + Rotation"
  "Open policy review"
  "Open Watchlist"
  "Refresh evidence"
)
for marker in "${markers[@]}"; do
  if ! grep -R --binary-files=text -Fq "$marker" "$STAGED_APP/dist"; then
    echo "BLOCKED_UI_DEPLOYMENT: built bundle missing actionable marker: $marker" >&2
    exit 4
  fi
done

"$PYTHON" - "$STAGED_APP/dist/build-meta.json" "$RESOLVED_COMMIT" "$STAMP" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
commit = sys.argv[2]
stamp = sys.argv[3]
try:
    payload = json.loads(path.read_text()) if path.exists() else {}
except Exception:
    payload = {}
payload.update({
    "ui_version": f"defense-sectors-actionable-{commit[:12]}-{stamp}",
    "source_commit": commit,
    "deployed_at_utc": stamp,
    "deployment_scope": "DEFENSE_SECTORS_SHADOW_UI_ONLY",
    "interaction_contract": "decision-board-actionable-v1",
})
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR"
rm -rf "$CANDIDATE"
mkdir -p "$CANDIDATE"
cp -a "$STAGED_APP/dist/." "$CANDIDATE/"

if [[ -d "$LIVE_DIST" ]]; then
  mv "$LIVE_DIST" "$BACKUP_DIST"
  OLD_MOVED=1
fi
mv "$CANDIDATE" "$LIVE_DIST"
NEW_INSTALLED=1

printf 'ui_source_commit|%s\n' "$RESOLVED_COMMIT"
printf 'interaction_contract|decision-board-actionable-v1\n'
printf 'deployment_scope|DEFENSE_SECTORS_SHADOW_UI_ONLY\n'
printf 'host_source_checkout|UNCHANGED\n'
printf 'live_dist|%s\n' "$LIVE_DIST"
printf 'backup_dist|%s\n' "$BACKUP_DIST"
printf 'build_meta|%s\n' "$LIVE_DIST/build-meta.json"
printf 'service_restart|NONE_REQUIRED\n'
printf 'producer_activation|NONE\n'
printf 'database_write|NONE\n'
printf 'check_page|/v3/defense\n'
printf 'check_page|/v3/watch?tab=sectors\n'
printf 'check_page|/v3/watch?tab=watchlist\n'
printf 'expected_marker|Review decision\n'
printf 'expected_marker|Watch sector\n'
printf 'expected_marker|Copy brief + Rotation\n'
printf 'expected_marker|Open policy review\n'
printf 'expected_watch_default|/v3/watch?tab=watchlist\n'
printf 'final_status|PASS_UI_STATIC_DEPLOY\n'
