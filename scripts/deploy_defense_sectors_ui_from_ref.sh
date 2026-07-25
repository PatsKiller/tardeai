#!/usr/bin/env bash
# Build and deploy only the Command Center v3 static bundle from one exact reviewed commit.
#
# Safety boundary:
# - exact 40-character Git source commit required;
# - source is read from Git objects into a temporary directory;
# - the dirty host checkout is never switched, reset, cleaned, pulled, merged or edited;
# - only apps/command-center-v3/dist is replaced, with a timestamped backup;
# - no service restart, producer execution, schedule change, database access or trading action.
set -euo pipefail
umask 077

readonly GIT=/usr/bin/git
readonly TAR=/usr/bin/tar
readonly NPM=/usr/bin/npm
readonly NPX=/usr/bin/npx
readonly PYTHON=/usr/bin/python3
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly REQUIRED_ACK=DEFENSE_SECTORS_SHADOW_UI_ONLY
readonly BACKUP_ROOT=/home/johnclaw/tradeai-deploy-backups/command-center-v3

if [[ "${UI_DEPLOY_ACK:-}" != "$REQUIRED_ACK" ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: set UI_DEPLOY_ACK=$REQUIRED_ACK" >&2
  exit 2
fi
for executable in "$GIT" "$TAR" "$NPM" "$NPX" "$PYTHON"; do
  if [[ ! -x "$executable" ]]; then
    echo "BLOCKED_UI_DEPLOYMENT: required executable unavailable: $executable" >&2
    exit 2
  fi
done

readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${UI_SOURCE_REF:-}"
readonly LIVE_APP="$HOST_REPO/apps/command-center-v3"
readonly LIVE_DIST="$LIVE_APP/dist"

if [[ "$HOST_REPO" != "$REPO_DEFAULT" || ! -d "$HOST_REPO/.git" ]]; then
  echo "REFUSED_UI_TARGET: expected live repository path is unavailable" >&2
  exit 3
fi
if [[ ! "$SOURCE_REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: UI_SOURCE_REF must be one exact 40-character commit SHA" >&2
  exit 2
fi
if ! "$GIT" -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}" 2>/dev/null; then
  echo "BLOCKED_UI_DEPLOYMENT: reviewed UI source commit is unavailable locally" >&2
  exit 2
fi
readonly RESOLVED_COMMIT="$("$GIT" -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "${RESOLVED_COMMIT,,}" != "${SOURCE_REF,,}" ]]; then
  echo "BLOCKED_UI_DEPLOYMENT: source ref did not resolve to the exact supplied commit" >&2
  exit 2
fi

required_paths=(
  apps/command-center-v3/package.json
  apps/command-center-v3/package-lock.json
  apps/command-center-v3/src/components/rotation/InstitutionalRotationBrief.tsx
  apps/command-center-v3/src/main.tsx
  apps/command-center-v3/src/defenseSectorsResponsive.css
)
for path in "${required_paths[@]}"; do
  if ! "$GIT" -C "$HOST_REPO" cat-file -e "$RESOLVED_COMMIT:$path" 2>/dev/null; then
    echo "BLOCKED_UI_DEPLOYMENT: required reviewed path unavailable: $path" >&2
    exit 2
  fi
done

readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly SHORT_SHA="${RESOLVED_COMMIT:0:12}"
readonly STAGE_ROOT="$(mktemp -d /tmp/defense-sectors-ui-source.XXXXXX)"
readonly CANDIDATE="$LIVE_APP/.dist-candidate-$STAMP-$SHORT_SHA"
readonly BACKUP_DIR="$BACKUP_ROOT/$STAMP-$SHORT_SHA"
readonly BACKUP_DIST="$BACKUP_DIR/dist"
OLD_MOVED=0
NEW_INSTALLED=0

cleanup() {
  rm -rf "$STAGE_ROOT" "$CANDIDATE"
  if [[ "$OLD_MOVED" -eq 1 && "$NEW_INSTALLED" -eq 0 && ! -e "$LIVE_DIST" && -d "$BACKUP_DIST" ]]; then
    mv "$BACKUP_DIST" "$LIVE_DIST"
    echo "rollback_live_dist|RESTORED" >&2
  fi
}
trap cleanup EXIT

chmod 700 "$STAGE_ROOT"
"$GIT" -C "$HOST_REPO" archive "$RESOLVED_COMMIT" apps/command-center-v3 \
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
)
for marker in "${markers[@]}"; do
  if ! grep -R --binary-files=text -Fq "$marker" "$STAGED_APP/dist"; then
    echo "BLOCKED_UI_DEPLOYMENT: built bundle missing marker: $marker" >&2
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
    "ui_version": f"defense-sectors-{commit[:12]}-{stamp}",
    "source_commit": commit,
    "deployed_at_utc": stamp,
    "deployment_scope": "DEFENSE_SECTORS_SHADOW_UI_ONLY",
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
printf 'deployment_scope|DEFENSE_SECTORS_SHADOW_UI_ONLY\n'
printf 'host_source_checkout|UNCHANGED\n'
printf 'live_dist|%s\n' "$LIVE_DIST"
printf 'backup_dist|%s\n' "$BACKUP_DIST"
printf 'build_meta|%s\n' "$LIVE_DIST/build-meta.json"
printf 'service_restart|NONE_REQUIRED\n'
printf 'producer_activation|NONE\n'
printf 'database_write|NONE\n'
printf 'check_page|/v3/defense\n'
printf 'check_page|/v3/sectors\n'
printf 'expected_marker|Sector decision board\n'
printf 'final_status|PASS_UI_STATIC_DEPLOY\n'
