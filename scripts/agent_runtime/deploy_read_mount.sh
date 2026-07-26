#!/usr/bin/env bash
# Coordinated (NOT auto-executed) deployment for the read-only agent-runtime MOUNT.
#
# Supersedes deploy_read_monitoring.sh (static-only) by coordinating the ONE thing
# that script could not: the backend mount inside scripts/portfolio_server.py that
# exposes GET /api/v3/agent-runtime/*. It deploys the Command Center v3 static build
# AND restarts exactly one named backend service so the new read routes are served.
#
# It holds NO database migration and NO broker / order / approval / 2FA / provider /
# scheduler / financial authority. Every mutating host action (backend file swap,
# static symlink flip, one service restart) is backed up first and fully reversible
# by the rollback path.
#
# Safety model:
#   * DRY-RUN BY DEFAULT — changes nothing unless --execute is passed;
#   * pins to an exact SHA and aborts if HEAD or the working tree does not match;
#   * backs up the backend file AND the current static release before touching them;
#   * requires an explicit interactive operator acknowledgement before the restart;
#   * restarts ONE named service only (RESTART_SERVICE);
#   * runs API health + /v3/agents browser + authority-envelope smokes;
#   * on ANY smoke failure, automatically rolls back BOTH backend and static, then
#     re-verifies health.
#
# Host prerequisites (all fail-closed if unset — see the report's remaining prerequisites):
#   DEPLOY_ROOT           serving root that contains releases/ and the `current` symlink
#   BACKEND_FILE          path to the live scripts/portfolio_server.py under service control
#   RESTART_SERVICE       systemd unit name of the ONE backend service to restart
#   HEALTH_URL            served index.html URL (expects HTTP 200)
#   AGENTS_URL            /v3/agents URL (browser smoke; expects HTTP 200)
#   READ_API_URL          /api/v3/agent-runtime/runs URL (authority-envelope smoke)
# Optional:
#   VITE_AGENT_RUNTIME_API_BASE   frontend read API base baked into the build
set -euo pipefail

EXPECTED_SHA="${1:-}"
MODE="${2:---dry-run}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CC_DIR="$REPO_ROOT/apps/command-center-v3"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

die() { echo "[deploy][FATAL] $*" >&2; exit 1; }
note() { echo "[deploy] $*"; }

[[ -n "$EXPECTED_SHA" ]] || die "usage: deploy_read_mount.sh <EXPECTED_SHA> [--execute]"
[[ "$MODE" == "--execute" || "$MODE" == "--dry-run" ]] || die "second arg must be --execute or --dry-run"
EXECUTE=0; [[ "$MODE" == "--execute" ]] && EXECUTE=1

# ---- 1. exact-ref gate ----------------------------------------------------
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "HEAD $HEAD_SHA != expected $EXPECTED_SHA"
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || die "working tree is dirty; refuse to deploy"
note "exact-ref gate OK @ $HEAD_SHA"

# ---- host prerequisites ---------------------------------------------------
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required (serving root with releases/ and current symlink)}"
: "${BACKEND_FILE:?BACKEND_FILE is required (live scripts/portfolio_server.py path)}"
: "${RESTART_SERVICE:?RESTART_SERVICE is required (the ONE backend service to restart)}"
: "${HEALTH_URL:?HEALTH_URL is required (served index for the health smoke)}"
: "${AGENTS_URL:?AGENTS_URL is required (/v3/agents browser smoke)}"
: "${READ_API_URL:?READ_API_URL is required (authority-envelope smoke)}"

RELEASES="$DEPLOY_ROOT/releases"
CURRENT="$DEPLOY_ROOT/current"
NEW_RELEASE="$RELEASES/${EXPECTED_SHA}-${TS}"
BACKUP_DIR="$DEPLOY_ROOT/backups/${EXPECTED_SHA}-${TS}"
BACKEND_BACKUP="$BACKUP_DIR/portfolio_server.py.bak"

# ---- 2. build (correct API base) ------------------------------------------
note "building Command Center v3 (npm ci && npm run build) with VITE_AGENT_RUNTIME_API_BASE='${VITE_AGENT_RUNTIME_API_BASE:-<unset>}'"
if [[ "$EXECUTE" == "1" ]]; then
  ( cd "$CC_DIR" && VITE_AGENT_RUNTIME_API_BASE="${VITE_AGENT_RUNTIME_API_BASE:-}" npm ci && \
    VITE_AGENT_RUNTIME_API_BASE="${VITE_AGENT_RUNTIME_API_BASE:-}" npm run build )
else
  note "DRY-RUN: would run 'npm ci && npm run build' in $CC_DIR"
fi
DIST="$CC_DIR/dist"

# Static safety gate: bundle must advertise the read-only contract and no authority tokens.
if [[ -d "$DIST" ]]; then
  grep -rq "agent-runtime-command-center-read-api-v1\|agent-runtime-monitoring-v1" "$DIST" \
    || die "built bundle is missing the read-only contract marker"
  if grep -rqiE "broker[_-]?write|order[_-]?submit|approval[_-]?mutate|two[_-]?factor|production[_-]?db[_-]?write" "$DIST"; then
    die "built bundle contains a forbidden authority token"
  fi
  note "static safety gate OK"
fi

# ---- 3. server config validation ------------------------------------------
note "validating backend syntax (py_compile portfolio_server.py)"
PYBIN="${PYBIN:-$REPO_ROOT/.venv/bin/python}"
[[ -x "$PYBIN" ]] || PYBIN="python3"
"$PYBIN" -m py_compile "$REPO_ROOT/scripts/portfolio_server.py" \
  || die "backend server failed syntax validation; refuse to deploy"
note "backend syntax OK"

# ---- 4. backups (backend + static) ----------------------------------------
PREVIOUS_TARGET=""
[[ -L "$CURRENT" ]] && PREVIOUS_TARGET="$(readlink -f "$CURRENT" || true)"
note "previous static release: ${PREVIOUS_TARGET:-<none>}"
note "backend backup target: $BACKEND_BACKUP"

if [[ "$EXECUTE" != "1" ]]; then
  note "DRY-RUN complete. Would, in order:"
  note "  1) back up backend $BACKEND_FILE -> $BACKEND_BACKUP"
  note "  2) back up static (current -> $PREVIOUS_TARGET)"
  note "  3) stage $DIST -> $NEW_RELEASE and copy new backend into place"
  note "  4) PROMPT the operator for explicit acknowledgement"
  note "  5) atomically flip $CURRENT and restart ONE service: $RESTART_SERVICE"
  note "  6) smoke: API health, /v3/agents browser, authority envelope"
  note "  7) on any failure: ROLLBACK backend + static, then re-verify health"
  exit 0
fi

mkdir -p "$BACKUP_DIR" "$RELEASES"
cp -a "$BACKEND_FILE" "$BACKEND_BACKUP"
note "backend backed up -> $BACKEND_BACKUP"
cp -a "$DIST" "$NEW_RELEASE"
note "staged static release at $NEW_RELEASE"

# ---- 5. operator acknowledgement (explicit, before any restart) -----------
echo "" >&2
echo "[deploy] About to swap backend + static and restart service '$RESTART_SERVICE'." >&2
echo "[deploy] Type EXACTLY 'DEPLOY $EXPECTED_SHA' to proceed: " >&2
read -r ACK
[[ "$ACK" == "DEPLOY $EXPECTED_SHA" ]] || die "operator acknowledgement not given; aborted with no changes to the running service"
note "operator acknowledgement received"

# ---- rollback (restores BOTH backend and static, then re-verifies) --------
rollback() {
  echo "[deploy][ROLLBACK] $*" >&2
  if [[ -f "$BACKEND_BACKUP" ]]; then
    cp -a "$BACKEND_BACKUP" "$BACKEND_FILE"
    echo "[deploy][ROLLBACK] restored backend <- $BACKEND_BACKUP" >&2
  fi
  if [[ -n "$PREVIOUS_TARGET" ]]; then
    ln -sfn "$PREVIOUS_TARGET" "$CURRENT.tmp.$$"
    mv -T "$CURRENT.tmp.$$" "$CURRENT"
    echo "[deploy][ROLLBACK] restored static current -> $PREVIOUS_TARGET" >&2
  fi
  systemctl restart "$RESTART_SERVICE" || echo "[deploy][ROLLBACK] WARN service restart failed" >&2
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
  echo "[deploy][ROLLBACK] post-rollback health: HTTP $code" >&2
  exit 1
}

# ---- swap backend + static, then restart ONE service ----------------------
# Backend: copy the exact-ref server file into the service-controlled path.
# Static: handled by the atomic symlink flip below.
install -m 0644 "$REPO_ROOT/scripts/portfolio_server.py" "$BACKEND_FILE"
note "backend file updated -> $BACKEND_FILE"
ln -sfn "$NEW_RELEASE" "$CURRENT.tmp.$$"
mv -T "$CURRENT.tmp.$$" "$CURRENT"
note "atomic static swap done: current -> $NEW_RELEASE"

note "restarting ONE service: $RESTART_SERVICE"
systemctl restart "$RESTART_SERVICE" || rollback "service restart failed for $RESTART_SERVICE"

# ---- 6. smokes: API health, /v3/agents browser, authority envelope --------
code="$(curl -sS -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
[[ "$code" == "200" ]] || rollback "index health smoke failed (HTTP $code) at $HEALTH_URL"
note "index health smoke OK ($HEALTH_URL -> 200)"

acode="$(curl -sS -o /dev/null -w '%{http_code}' "$AGENTS_URL" || true)"
[[ "$acode" == "200" ]] || rollback "/v3/agents browser smoke failed (HTTP $acode) at $AGENTS_URL"
note "/v3/agents browser smoke OK ($AGENTS_URL -> 200)"

# Authority-envelope smoke: 200 (connected) or 503 (not yet connected) are BOTH
# acceptable, but the body must be read_only with zero authority in either case.
rbody="$(curl -sS "$READ_API_URL" || true)"
echo "$rbody" | grep -q '"read_only": *true' || rollback "read API is not read_only at $READ_API_URL"
if echo "$rbody" | grep -qiE '"(mutation|provider_call|service_control|schedule_change|financial_action)": *true'; then
  rollback "read API advertised non-zero authority"
fi
note "authority-envelope smoke OK (read_only, zero authority)"

note "deploy complete @ $EXPECTED_SHA -> backend + $NEW_RELEASE (service $RESTART_SERVICE restarted once)"
