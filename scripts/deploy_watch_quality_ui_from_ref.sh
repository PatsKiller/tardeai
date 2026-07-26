#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="WATCH_QUALITY_SHADOW_UI_ONLY"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_QUALITY_SOURCE_REF:-}"
readonly EVIDENCE_ROOT="${WATCH_QUALITY_EVIDENCE_ROOT:-/home/johnclaw/tradeai-audit/watch-quality}"
readonly LIVE_APP="$HOST_REPO/apps/command-center-v3"
readonly LIVE_DIST="$LIVE_APP/dist"
readonly BACKUP_ROOT=/home/johnclaw/tradeai-deploy-backups/command-center-v3
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly STAGE_ROOT="$(mktemp -d /tmp/watch-quality-ui-stage.XXXXXX)"
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
    printf 'rollback_live_dist|RESTORED\n'
  fi
}
trap cleanup EXIT

if [[ "${WATCH_QUALITY_UI_DEPLOY_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_GATE5: WATCH_QUALITY_UI_DEPLOY_ACK must equal $ACK_REQUIRED" >&2
  exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_GATE5: WATCH_QUALITY_SOURCE_REF must be an exact 40-character commit SHA" >&2
  exit 2
fi
if [[ ! -d "$HOST_REPO/.git" ]]; then
  echo "BLOCKED_GATE5: repository unavailable: $HOST_REPO" >&2
  exit 2
fi

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "$RESOLVED_COMMIT" != "$SOURCE_REF" ]]; then
  echo "BLOCKED_GATE5: resolved commit differs from exact source ref" >&2
  exit 2
fi
readonly BACKUP_DIR="$BACKUP_ROOT/${STAMP}-${RESOLVED_COMMIT:0:12}"
readonly BACKUP_DIST="$BACKUP_DIR/dist"

GATE4_JSON="${WATCH_QUALITY_GATE4_JSON:-}"
if [[ -z "$GATE4_JSON" ]]; then
  GATE4_JSON="$(find "$EVIDENCE_ROOT" -maxdepth 1 -type f \
    -name 'watch-quality-gate4-*.json' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print; exit}')"
fi
if [[ -z "$GATE4_JSON" || ! -f "$GATE4_JSON" ]]; then
  echo "BLOCKED_GATE5: Gate 4 evidence not found" >&2
  exit 2
fi
if ! grep -Fq '"status": "PASS_GATE4_READONLY_VERIFICATION"' "$GATE4_JSON"; then
  echo "BLOCKED_GATE5: Gate 4 evidence is not passing" >&2
  exit 2
fi
if ! grep -Fq '"read_only": true' "$GATE4_JSON"; then
  echo "BLOCKED_GATE5: Gate 4 evidence does not prove read-only verification" >&2
  exit 2
fi

for required in "$TAR" "$NPM" "$NPX" "$PYTHON"; do
  if [[ -z "$required" || ! -x "$required" ]]; then
    echo "BLOCKED_GATE5: required existing command unavailable" >&2
    exit 2
  fi
done

mkdir -p "$STAGE_ROOT"
git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" apps/command-center-v3 \
  | "$TAR" -x -C "$STAGE_ROOT"
readonly STAGED_APP="$STAGE_ROOT/apps/command-center-v3"
cd "$STAGED_APP"
"$NPM" ci
"$NPX" tsc --pretty false
"$NPX" vite build

if [[ ! -f "$STAGED_APP/dist/index.html" ]]; then
  echo "BLOCKED_GATE5: Vite output missing index.html" >&2
  exit 4
fi

markers=(
  "watch-quality-governance-v1"
  "STREET DATA >7D"
  "OWNERSHIP ELIGIBLE"
  "MECHANICS VALID"
  "DETERMINISTIC_REVIEW_REQUIRED"
  "RECOMMENDED · NOT RUN"
  "command-center-global-review-v1"
  "command-center-structured-provenance-v1"
  "OPEN REVIEW"
)
for marker in "${markers[@]}"; do
  if ! grep -R --binary-files=text -Fq "$marker" "$STAGED_APP/dist"; then
    echo "BLOCKED_GATE5: built bundle missing marker: $marker" >&2
    exit 4
  fi
done

"$PYTHON" - "$STAGED_APP/dist/build-meta.json" "$RESOLVED_COMMIT" "$STAMP" "$GATE4_JSON" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
commit = sys.argv[2]
stamp = sys.argv[3]
gate4 = sys.argv[4]
try:
    payload = json.loads(path.read_text()) if path.exists() else {}
except Exception:
    payload = {}
payload.update({
    "ui_version": f"watch-quality-{commit[:12]}-{stamp}",
    "source_commit": commit,
    "deployed_at_utc": stamp,
    "deployment_scope": "WATCH_QUALITY_SHADOW_UI_ONLY",
    "watch_quality_contract": "watch-quality-governance-v1",
    "global_review_contract": "command-center-global-review-v1",
    "structured_evidence_contract": "command-center-structured-provenance-v1",
    "gate4_evidence": gate4,
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
printf 'gate4_evidence|%s\n' "$GATE4_JSON"
printf 'watch_quality_contract|watch-quality-governance-v1\n'
printf 'global_review_contract|command-center-global-review-v1\n'
printf 'structured_evidence_contract|command-center-structured-provenance-v1\n'
printf 'deployment_scope|WATCH_QUALITY_SHADOW_UI_ONLY\n'
printf 'host_source_checkout|UNCHANGED\n'
printf 'live_dist|%s\n' "$LIVE_DIST"
printf 'backup_dist|%s\n' "$BACKUP_DIST"
printf 'build_meta|%s\n' "$LIVE_DIST/build-meta.json"
printf 'service_restart|NONE_REQUIRED\n'
printf 'backend_change|NONE\n'
printf 'scheduler_activation|NONE\n'
printf 'model_provider_call|NONE\n'
printf 'database_write|NONE\n'
printf 'check_page|/v3/watch?tab=watchlist\n'
printf 'check_symbol|FATN\n'
printf 'expected_marker|STREET DATA >7D\n'
printf 'expected_marker|OWNERSHIP ELIGIBLE\n'
printf 'expected_marker|MECHANICS VALID\n'
printf 'expected_marker|watch-quality-governance-v1\n'
printf 'final_status|PASS_GATE5_WATCH_UI_DEPLOY\n'
