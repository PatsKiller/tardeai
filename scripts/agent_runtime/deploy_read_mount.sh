#!/usr/bin/env bash
# Coordinated (NOT auto-executed) deployment for the read-only agent-runtime MOUNT.
#
# Supersedes deploy_read_monitoring.sh (static-only) by coordinating the things that
# script could not: (1) the backend mount inside scripts/portfolio_server.py that
# exposes GET /api/v3/agent-runtime/*, and (2) the CONNECT step that actually wires
# the read plane to the isolated SHADOW reader — without which a restart alone stays
# HTTP-503 (READ_API disconnected) forever. It installs the Command Center v3 static
# build into the LIVE serving root, writes the reader identity into the server's
# user-systemd environment, and restarts exactly one USER-level backend service so
# the new read routes are served AND connected.
#
# It holds NO database migration and NO broker / order / approval / 2FA / provider /
# scheduler / financial authority. Every mutating host action (backend file swap,
# static dir swap, reader env-file + systemd drop-in write, one user-service restart)
# is backed up first and fully reversible by the rollback path.
#
# HOST MODEL (this host, verified):
#   * the server runs as a USER-level systemd unit (systemctl --user), NOT a system
#     unit; there is NO sudo and NO system systemctl in this path;
#   * /v3 is served DIRECTLY from the repo apps/command-center-v3/dist (a real dir),
#     NOT a releases/current symlink layout;
#   * the read plane is DISCONNECTED (READ_API=503) until AGENT_RUNTIME_READ_API=1 and
#     AGENT_RUNTIME_READ_DSN are present in the server's environment — so this script
#     writes them into a mode-0600 user env file referenced by a user-systemd drop-in.
#
# Safety model:
#   * DRY-RUN BY DEFAULT — changes nothing unless --execute is passed;
#   * pins to an exact SHA and aborts if HEAD or the working tree does not match;
#   * backs up the backend file AND the current static dir (and any pre-existing reader
#     env-file / drop-in) before touching them;
#   * enforces a STRICT pre-connect HTTP-503 baseline (read_only, zero authority,
#     disconnected) BEFORE any build/backup/connect/swap/restart — fail-closed, no
#     host mutation;
#   * requires an explicit interactive operator acknowledgement before the restart;
#   * restarts ONE named USER service only (systemctl --user restart RESTART_SERVICE);
#   * runs API health + /v3/agents browser smokes, then a STRICT post-connect
#     acceptance (HTTP 200, read_only, zero authority, connected to the shadow reader
#     identity, no execution agent enabled/promoted);
#   * on ANY smoke failure (incl. a 503-after, a non-read-only body, or authority=true),
#     automatically DISCONNECTS (removes the reader env-file + drop-in, daemon-reload,
#     restart -> back to 503) AND rolls back BOTH backend and static, then re-verifies
#     health.
#
# Host prerequisites (all fail-closed if unset — see the report's remaining prerequisites):
#   SHADOW_READER_DSN     isolated SHADOW *reader* DSN written into the server env (never logged)
#   BACKEND_FILE          path to the live scripts/portfolio_server.py under service control
#   HEALTH_URL            served index.html URL (expects HTTP 200)
#   AGENTS_URL            /v3/agents URL (browser smoke; expects HTTP 200)
#   READ_API_URL          /api/v3/agent-runtime/runs URL (authority-envelope smoke)
# Optional (defaults shown):
#   STATIC_DIR            live static serving root      (default apps/command-center-v3/dist)
#   RESTART_SERVICE       user systemd unit to restart  (default portfolio-server.service)
#   READ_API_ENV_FILE     0600 reader env file          (default $HOME/.config/tradeai/agent-read-api.env)
#   USER_SYSTEMD_DIR      user systemd config dir        (default $HOME/.config/systemd/user)
#   A2_BACKUP_ROOT        backup/staging root (OUTSIDE the repo tree)
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

# ---- host prerequisites (with this-host defaults) -------------------------
STATIC_DIR="${STATIC_DIR:-$CC_DIR/dist}"
RESTART_SERVICE="${RESTART_SERVICE:-portfolio-server.service}"
READ_API_ENV_FILE="${READ_API_ENV_FILE:-$HOME/.config/tradeai/agent-read-api.env}"
USER_SYSTEMD_DIR="${USER_SYSTEMD_DIR:-$HOME/.config/systemd/user}"
A2_BACKUP_ROOT="${A2_BACKUP_ROOT:-$HOME/.local/state/tradeai/a2-read-plane}"
: "${BACKEND_FILE:?BACKEND_FILE is required (live scripts/portfolio_server.py path)}"
: "${HEALTH_URL:?HEALTH_URL is required (served index for the health smoke)}"
: "${AGENTS_URL:?AGENTS_URL is required (/v3/agents browser smoke)}"
: "${READ_API_URL:?READ_API_URL is required (authority-envelope smoke)}"

DROPIN_DIR="$USER_SYSTEMD_DIR/${RESTART_SERVICE}.d"
DROPIN_FILE="$DROPIN_DIR/10-agent-read-api.conf"

# ---- 1b. STRICT pre-connect baseline (fail-closed, BEFORE any host mutation) --
# A2 fail-closed contract: before ANY build / backup / connect / static swap /
# restart, the read plane MUST answer READ_API_URL with HTTP 503, a read_only:true
# body, ZERO authority, and a disconnected/unavailable indicator (NOT healthy-
# connected). EVERY other status — 000, 200, redirects, auth, 404, 500 — BLOCKS with
# no host mutation. This is re-run at execution time even if a preflight already passed.
strict_pre_connect_503() {
  command -v curl >/dev/null 2>&1 || die "curl required for the strict pre-connect baseline"
  local resp code body
  resp="$(curl -sS -w '\n%{http_code}' "$READ_API_URL" 2>/dev/null || true)"
  code="${resp##*$'\n'}"; body="${resp%$'\n'*}"
  [[ "$code" == "503" ]] \
    || die "STRICT pre-connect baseline: READ_API HTTP $code (require EXACTLY 503; ALL others BLOCK) — no host mutation"
  echo "$body" | grep -q '"read_only" *: *true' \
    || die "STRICT pre-connect baseline: body is not read_only:true — no host mutation"
  if echo "$body" | grep -qiE '"(mutation|provider_call|service_control|schedule_change|financial_action)" *: *true'; then
    die "STRICT pre-connect baseline: body advertises non-zero authority — no host mutation"
  fi
  echo "$body" | grep -qiE '"connected" *: *false|disconnected|unavailable|not[_-]?connected' \
    || die "STRICT pre-connect baseline: body does not indicate a disconnected/unavailable read plane — no host mutation"
  if echo "$body" | grep -qiE '"connected" *: *true'; then
    die "STRICT pre-connect baseline: body claims healthy-connected before wiring — no host mutation"
  fi
  note "STRICT pre-connect baseline OK (HTTP 503, read_only, zero authority, disconnected)"
}
if [[ "$EXECUTE" == "1" ]]; then
  # CONNECT requires the reader DSN — fail-closed if absent (value never printed).
  : "${SHADOW_READER_DSN:?SHADOW_READER_DSN is required for the connect step (value never printed)}"
  strict_pre_connect_503
fi

BACKUP_DIR="$A2_BACKUP_ROOT/${EXPECTED_SHA}-${TS}"
BACKEND_BACKUP="$BACKUP_DIR/portfolio_server.py.bak"
STATIC_BACKUP="$BACKUP_DIR/static-dist"
BUILD_STAGE="$BACKUP_DIR/build-dist"
ENV_FILE_BACKUP="$BACKUP_DIR/agent-read-api.env.bak"
DROPIN_BACKUP="$BACKUP_DIR/10-agent-read-api.conf.bak"

# ---- 2. build (correct API base) into a STAGING dir (never the live root) ---
# Atomic model: build to $BUILD_STAGE, safety-gate it, then swap it into $STATIC_DIR.
note "building Command Center v3 into staging dir (npm ci && npm run build --outDir) with VITE_AGENT_RUNTIME_API_BASE='${VITE_AGENT_RUNTIME_API_BASE:-<unset>}'"
if [[ "$EXECUTE" == "1" ]]; then
  mkdir -p "$BUILD_STAGE"
  ( cd "$CC_DIR" && VITE_AGENT_RUNTIME_API_BASE="${VITE_AGENT_RUNTIME_API_BASE:-}" npm ci && \
    VITE_AGENT_RUNTIME_API_BASE="${VITE_AGENT_RUNTIME_API_BASE:-}" npm run build -- --outDir "$BUILD_STAGE" )
else
  note "DRY-RUN: would run 'npm ci && npm run build -- --outDir $BUILD_STAGE' in $CC_DIR"
fi

# Static safety gate: bundle must advertise the read-only contract and no authority tokens.
if [[ "$EXECUTE" == "1" && -d "$BUILD_STAGE" ]]; then
  grep -rq "agent-runtime-command-center-read-api-v1\|agent-runtime-monitoring-v1" "$BUILD_STAGE" \
    || die "built bundle is missing the read-only contract marker"
  if grep -rqiE "broker[_-]?write|order[_-]?submit|approval[_-]?mutate|two[_-]?factor|production[_-]?db[_-]?write" "$BUILD_STAGE"; then
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

# ---- 4. backups (backend + static dir + any pre-existing reader wiring) -----
CURRENT_STATIC_TARGET="<none>"
[[ -e "$STATIC_DIR" ]] && CURRENT_STATIC_TARGET="$(readlink -f "$STATIC_DIR" 2>/dev/null || echo "$STATIC_DIR")"
note "current static serving root: $CURRENT_STATIC_TARGET"
note "backend backup target: $BACKEND_BACKUP"
note "static backup target:  $STATIC_BACKUP"
note "reader env file:       $READ_API_ENV_FILE"
note "reader drop-in:        $DROPIN_FILE"
note "restart unit (user):   systemctl --user restart $RESTART_SERVICE"

if [[ "$EXECUTE" != "1" ]]; then
  note "DRY-RUN complete. Would, in order:"
  note "  1) back up backend $BACKEND_FILE -> $BACKEND_BACKUP"
  note "  2) back up static dir $STATIC_DIR -> $STATIC_BACKUP (+ any pre-existing reader env/drop-in)"
  note "  3) build -> $BUILD_STAGE, safety-gate, copy new backend into place"
  note "  4) PROMPT the operator for explicit acknowledgement"
  note "  5) CONNECT: write 0600 $READ_API_ENV_FILE + drop-in $DROPIN_FILE, systemctl --user daemon-reload"
  note "  6) atomically swap $BUILD_STAGE -> $STATIC_DIR and restart ONE user service: $RESTART_SERVICE"
  note "  7) smoke: API health, /v3/agents browser, authority envelope"
  note "  8) on any failure: DISCONNECT (remove reader env/drop-in, daemon-reload, restart)"
  note "     + ROLLBACK backend + static, then re-verify health"
  exit 0
fi

mkdir -p "$BACKUP_DIR"
cp -a "$BACKEND_FILE" "$BACKEND_BACKUP"
note "backend backed up -> $BACKEND_BACKUP"
if [[ -e "$STATIC_DIR" ]]; then
  cp -a "$STATIC_DIR" "$STATIC_BACKUP"
  note "static dir backed up -> $STATIC_BACKUP"
fi
# Capture pre-existing reader wiring so rollback restores exact prior state (or removes).
ENV_FILE_PREEXISTED=0; DROPIN_PREEXISTED=0
if [[ -f "$READ_API_ENV_FILE" ]]; then ENV_FILE_PREEXISTED=1; cp -a "$READ_API_ENV_FILE" "$ENV_FILE_BACKUP"; fi
if [[ -f "$DROPIN_FILE" ]]; then DROPIN_PREEXISTED=1; cp -a "$DROPIN_FILE" "$DROPIN_BACKUP"; fi

# ---- 5. operator acknowledgement (explicit, before any restart) -----------
echo "" >&2
echo "[deploy] About to CONNECT the read plane, swap backend + static, and restart user service '$RESTART_SERVICE'." >&2
echo "[deploy] Type EXACTLY 'DEPLOY $EXPECTED_SHA' to proceed: " >&2
read -r ACK
[[ "$ACK" == "DEPLOY $EXPECTED_SHA" ]] || die "operator acknowledgement not given; aborted with no changes to the running service"
note "operator acknowledgement received"

# ---- disconnect helper (removes/restores reader env-file + drop-in) --------
# Returns the server to the DISCONNECTED (503) read plane. Used by rollback.
disconnect_read_plane() {
  if [[ "$ENV_FILE_PREEXISTED" == "1" && -f "$ENV_FILE_BACKUP" ]]; then
    cp -a "$ENV_FILE_BACKUP" "$READ_API_ENV_FILE"
    echo "[deploy][ROLLBACK] restored prior reader env file" >&2
  else
    rm -f "$READ_API_ENV_FILE"
    echo "[deploy][ROLLBACK] removed reader env file (disconnect)" >&2
  fi
  if [[ "$DROPIN_PREEXISTED" == "1" && -f "$DROPIN_BACKUP" ]]; then
    cp -a "$DROPIN_BACKUP" "$DROPIN_FILE"
    echo "[deploy][ROLLBACK] restored prior reader drop-in" >&2
  else
    rm -f "$DROPIN_FILE"
    echo "[deploy][ROLLBACK] removed reader drop-in (disconnect)" >&2
  fi
  systemctl --user daemon-reload || echo "[deploy][ROLLBACK] WARN user daemon-reload failed" >&2
}

# ---- rollback (disconnect + restore backend and static, then re-verify) ----
rollback() {
  echo "[deploy][ROLLBACK] $*" >&2
  # 1) disconnect the read plane (server returns to 503)
  disconnect_read_plane
  # 2) restore backend
  if [[ -f "$BACKEND_BACKUP" ]]; then
    cp -a "$BACKEND_BACKUP" "$BACKEND_FILE"
    echo "[deploy][ROLLBACK] restored backend <- $BACKEND_BACKUP" >&2
  fi
  # 3) restore static dir
  if [[ -e "$STATIC_BACKUP" ]]; then
    rm -rf "$STATIC_DIR"
    cp -a "$STATIC_BACKUP" "$STATIC_DIR"
    echo "[deploy][ROLLBACK] restored static dir <- $STATIC_BACKUP" >&2
  fi
  # 4) restart the ONE user service and verify health
  systemctl --user restart "$RESTART_SERVICE" || echo "[deploy][ROLLBACK] WARN user service restart failed" >&2
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
  echo "[deploy][ROLLBACK] post-rollback health: HTTP $code" >&2
  exit 1
}

# ---- CONNECT: write the reader identity into the user-systemd environment ---
# Mode-0600 env file with EXACTLY two lines; DSN value NEVER printed/logged.
mkdir -p "$(dirname "$READ_API_ENV_FILE")"
( umask 077
  printf 'AGENT_RUNTIME_READ_API=1\nAGENT_RUNTIME_READ_DSN=%s\n' "$SHADOW_READER_DSN" > "$READ_API_ENV_FILE"
)
chmod 600 "$READ_API_ENV_FILE"
note "wrote reader env file (mode 0600): $READ_API_ENV_FILE (AGENT_RUNTIME_READ_API=1, DSN redacted)"
mkdir -p "$DROPIN_DIR"
printf '[Service]\nEnvironmentFile=%s\n' "$READ_API_ENV_FILE" > "$DROPIN_FILE"
note "installed user-systemd drop-in: $DROPIN_FILE (EnvironmentFile=<reader env file>)"
systemctl --user daemon-reload || rollback "systemctl --user daemon-reload failed"
note "systemctl --user daemon-reload OK"

# ---- swap backend + static, then restart ONE user service ------------------
# Backend: copy the exact-ref server file into the service-controlled path.
install -m 0644 "$REPO_ROOT/scripts/portfolio_server.py" "$BACKEND_FILE" || rollback "backend install failed"
note "backend file updated -> $BACKEND_FILE"
# Static: atomic swap of the freshly built staging dir into the live serving root.
if [[ -e "$STATIC_DIR" ]]; then mv "$STATIC_DIR" "${STATIC_DIR}.a2old.$$" || rollback "could not move old static dir aside"; fi
mv "$BUILD_STAGE" "$STATIC_DIR" || rollback "could not install new static dir"
rm -rf "${STATIC_DIR}.a2old.$$" 2>/dev/null || true
note "atomic static swap done: $STATIC_DIR <- freshly built bundle"

note "restarting ONE user service: systemctl --user restart $RESTART_SERVICE"
systemctl --user restart "$RESTART_SERVICE" || rollback "user service restart failed for $RESTART_SERVICE"

# ---- 6. smokes: API health, /v3/agents browser, authority envelope --------
code="$(curl -sS -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
[[ "$code" == "200" ]] || rollback "index health smoke failed (HTTP $code) at $HEALTH_URL"
note "index health smoke OK ($HEALTH_URL -> 200)"

acode="$(curl -sS -o /dev/null -w '%{http_code}' "$AGENTS_URL" || true)"
[[ "$acode" == "200" ]] || rollback "/v3/agents browser smoke failed (HTTP $acode) at $AGENTS_URL"
note "/v3/agents browser smoke OK ($AGENTS_URL -> 200)"

# ---- STRICT post-connect acceptance (fail-closed → rollback) ----------------
# After the single restart, the read plane MUST be genuinely connected as the
# SHADOW reader: READ_API 200, read_only:true, ZERO authority, connected to the
# shadow reader identity (agentic_runtime_reader), and NO execution agent enabled
# or promoted. An HTTP 503 after deploy is a FAILED deploy. Any of these → automatic
# DISCONNECT + rollback of backend AND static, then the post-rollback health check.
rresp="$(curl -sS -w '\n%{http_code}' "$READ_API_URL" 2>/dev/null || true)"
rcode="${rresp##*$'\n'}"; rbody="${rresp%$'\n'*}"
[[ "$rcode" == "200" ]] || rollback "post-connect read API HTTP $rcode (a 503-after is a FAILED deploy) at $READ_API_URL"
echo "$rbody" | grep -q '"read_only" *: *true' || rollback "post-connect read API is not read_only:true at $READ_API_URL"
if echo "$rbody" | grep -qiE '"(mutation|provider_call|service_control|schedule_change|financial_action)" *: *true'; then
  rollback "post-connect read API advertised non-zero authority"
fi
echo "$rbody" | grep -qiE '"connected" *: *true' \
  || rollback "post-connect read API is not connected (shadow reader identity required)"
echo "$rbody" | grep -q 'agentic_runtime_reader' \
  || rollback "post-connect read API is not bound to the SHADOW reader identity (agentic_runtime_reader)"
if echo "$rbody" | grep -qiE '"(execution_agents_enabled|execution_agent_active|agent_promoted|agent_operational_promotion|agent_operational)" *: *true'; then
  rollback "post-connect read API shows an execution agent enabled/promoted"
fi
note "STRICT post-connect acceptance OK (HTTP 200, read_only, zero authority, connected to shadow reader, no execution agent)"

note "deploy complete @ $EXPECTED_SHA -> backend + $STATIC_DIR connected read plane (user service $RESTART_SERVICE restarted once)"
