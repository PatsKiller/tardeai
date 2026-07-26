#!/usr/bin/env bash
# Prepared (NOT auto-executed) deployment for the agent-runtime read/monitoring rollout.
#
# Deploys ONLY the Command Center v3 static build (read-only monitoring surface + read adapter).
# It performs NO database migration and holds NO broker / order / approval / 2FA / provider /
# service / scheduler authority. The single mutating host action is an atomic static symlink flip,
# which is fully reversible by the rollback step.
#
# Safety model:
#   * dry-run by default; refuses to change anything unless --execute is passed;
#   * pins to an exact SHA and aborts if HEAD or the working tree does not match;
#   * backs up the current release and flips atomically (mv -T on a symlink);
#   * runs a read-only health smoke and auto-rolls-back on failure.
#
# Host prerequisites (all fail-closed if unset — see the report's "remaining host prerequisites"):
#   DEPLOY_ROOT           serving root that contains releases/ and the `current` symlink
#   HEALTH_URL            URL of the served index.html (expects HTTP 200)
#   READ_API_HEALTH_URL   (optional) read API runs endpoint; verified read_only + zero authority
set -euo pipefail

EXPECTED_SHA="${1:-}"
MODE="${2:---dry-run}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CC_DIR="$REPO_ROOT/apps/command-center-v3"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

die() { echo "[deploy][FATAL] $*" >&2; exit 1; }
note() { echo "[deploy] $*"; }

[[ -n "$EXPECTED_SHA" ]] || die "usage: deploy_read_monitoring.sh <EXPECTED_SHA> [--execute]"
[[ "$MODE" == "--execute" || "$MODE" == "--dry-run" ]] || die "second arg must be --execute or --dry-run"
EXECUTE=0; [[ "$MODE" == "--execute" ]] && EXECUTE=1

# ---- 1. exact-ref gate ----------------------------------------------------
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "HEAD $HEAD_SHA != expected $EXPECTED_SHA"
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || die "working tree is dirty; refuse to deploy"
note "exact-ref gate OK @ $HEAD_SHA"

# ---- host prerequisites ---------------------------------------------------
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required (serving root with releases/ and current symlink)}"
: "${HEALTH_URL:?HEALTH_URL is required (served index for the health smoke)}"
RELEASES="$DEPLOY_ROOT/releases"
CURRENT="$DEPLOY_ROOT/current"
NEW_RELEASE="$RELEASES/${EXPECTED_SHA}-${TS}"

# ---- 2. build -------------------------------------------------------------
note "building Command Center v3 (npm ci && npm run build)"
if [[ "$EXECUTE" == "1" ]]; then
  ( cd "$CC_DIR" && npm ci && npm run build )
else
  note "DRY-RUN: would run 'npm ci && npm run build' in $CC_DIR"
fi
DIST="$CC_DIR/dist"

# Static safety gate: the bundle must advertise the read-only contract and must not contain
# forbidden authority tokens. Runs in both modes when a dist already exists.
if [[ -d "$DIST" ]]; then
  grep -rq "agent-runtime-command-center-read-api-v1\|agent-runtime-monitoring-v1" "$DIST" \
    || die "built bundle is missing the read-only contract marker"
  if grep -rqiE "broker[_-]?write|order[_-]?submit|approval[_-]?mutate|two[_-]?factor|production[_-]?db[_-]?write" "$DIST"; then
    die "built bundle contains a forbidden authority token"
  fi
  note "static safety gate OK"
fi

# ---- 3/4. backup + stage --------------------------------------------------
PREVIOUS_TARGET=""
[[ -L "$CURRENT" ]] && PREVIOUS_TARGET="$(readlink -f "$CURRENT" || true)"
note "previous release: ${PREVIOUS_TARGET:-<none>}"

if [[ "$EXECUTE" != "1" ]]; then
  note "DRY-RUN complete. Would: stage $DIST -> $NEW_RELEASE, atomically flip $CURRENT, smoke $HEALTH_URL, rollback on failure."
  exit 0
fi

mkdir -p "$RELEASES"
cp -a "$DIST" "$NEW_RELEASE"
note "staged release at $NEW_RELEASE"

# ---- 5. atomic swap -------------------------------------------------------
ln -sfn "$NEW_RELEASE" "$CURRENT.tmp.$$"
mv -T "$CURRENT.tmp.$$" "$CURRENT"
note "atomic swap done: current -> $NEW_RELEASE"

# ---- 6/7. health smoke + rollback ----------------------------------------
rollback() {
  echo "[deploy][ROLLBACK] $*" >&2
  if [[ -n "$PREVIOUS_TARGET" ]]; then
    ln -sfn "$PREVIOUS_TARGET" "$CURRENT.tmp.$$"
    mv -T "$CURRENT.tmp.$$" "$CURRENT"
    echo "[deploy][ROLLBACK] restored current -> $PREVIOUS_TARGET" >&2
  else
    echo "[deploy][ROLLBACK] no previous release to restore" >&2
  fi
  exit 1
}

code="$(curl -fsS -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
[[ "$code" == "200" ]] || rollback "index health smoke failed (HTTP $code) at $HEALTH_URL"
note "index health smoke OK ($HEALTH_URL -> 200)"

if [[ -n "${READ_API_HEALTH_URL:-}" ]]; then
  body="$(curl -fsS "$READ_API_HEALTH_URL" || true)"
  echo "$body" | grep -q '"read_only": *true' || rollback "read API is not read_only at $READ_API_HEALTH_URL"
  echo "$body" | grep -qiE '"(mutation|financial_action|service_control)": *true' && rollback "read API advertised mutation authority"
  note "read API health smoke OK (read_only, zero authority)"
fi

note "deploy complete @ $EXPECTED_SHA -> $NEW_RELEASE"
