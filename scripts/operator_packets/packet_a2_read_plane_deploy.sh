#!/usr/bin/env bash
# =============================================================================
# PACKET A2 — Read-plane deployment (backend read mount + Command Center /v3/agents).
# =============================================================================
# Deploys the read-only agent-runtime backend mount and the Command Center v3
# /v3/agents view, connecting ONLY to the isolated SHADOW *reader* DSN. Execution
# agents stay DISABLED — this packet deploys a read plane and nothing else. It
# holds NO broker / order / approval / 2FA / migration / scheduler authority.
#
# It WRAPS scripts/agent_runtime/deploy_read_mount.sh, which implements the guarded
# host mutation: clean-checkout gate, backend+static backup, atomic static swap,
# ONE named service restart, and — the fail-closed acceptance contract —
#   * a STRICT pre-connect baseline (HTTP 503 + read_only + zero authority +
#     disconnected) enforced BEFORE any build/backup/symlink/restart, and
#   * a STRICT post-connect acceptance (HTTP 200 + read_only + zero authority +
#     connected to the shadow reader identity + no execution agent) enforced AFTER
#     the single restart, with automatic backend+static rollback on any failure
#     followed by a post-rollback health verification.
#
# This wrapper adds: exact-RC-SHA gate, typed acknowledgement token, a genuine
# no-mutation --preflight readiness mode, execution-time revalidation, and refusal
# to expose anything other than the SHADOW *reader* ROLE NAME.
#
# FAIL-CLOSED CONTRACT (the defect this packet repairs):
#   The previous wrapper pre-connect smoke ACCEPTED connection-failure 000 and only
#   WARNED on an unexpected status instead of requiring HTTP 503, so a disconnected
#   read plane could be reported as a successful deploy. The requirement now lives at
#   the true mutation gate (the inner script) where it is fail-closed: 503-before ->
#   200-after, both carrying read_only:true and zero authority. The wrapper no longer
#   warns-and-continues; --preflight enforces the strict 503 baseline read-only, and
#   the inner re-runs it immediately before the first host mutation.
#
# SAFETY CONTRACT:
#   * PREPARE-ONLY BY DEFAULT. No --execute / --preflight => print plan, exit 3.
#   * NO args => print PREPARE-ONLY usage, exit 2.
#   * exact-RC-SHA gate; --execute also requires --ack <token>.
#   * --preflight performs read-only FS / systemd-status / HTTP checks and reuses the
#     inner DRY-RUN path. It NEVER builds-with-install, mkdir/copies/symlinks, restarts
#     a service, connects to PostgreSQL, applies migrations, or enables agents.
#   * The reader DSN is read from $SHADOW_READER_DSN and is NEVER printed (only the
#     parsed ROLE NAME may be printed); a writer/admin DSN is REJECTED.
#
# EXIT CODES: 0 ok · 2 usage/gate blocked · 3 prepare-only refusal · 4 DSN reject
# =============================================================================
set -euo pipefail

readonly PACKET="A2:read_plane"
readonly ACK_TOKEN="APPLY-A2-READ-PLANE"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly INNER="$REPO_ROOT/scripts/agent_runtime/deploy_read_mount.sh"
readonly CC_DIR="$REPO_ROOT/apps/command-center-v3"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY (dry-run default) ==="; }
die()    { echo "[A2][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[A2] $*"; }

PARSED_READER_ROLE=""
PRE_CONNECT_STATUS=""

EXPECTED_SHA=""; EXECUTE=0; PREFLIGHT=0; ACK=""
for arg in "$@"; do
  case "$arg" in
    --execute|--apply) EXECUTE=1 ;;
    --preflight) PREFLIGHT=1 ;;
    --ack) ACK="__NEXT__" ;;
    *) if [[ "$ACK" == "__NEXT__" ]]; then ACK="$arg";
       elif [[ -z "$EXPECTED_SHA" ]]; then EXPECTED_SHA="$arg";
       else die "unexpected argument: $arg" 2; fi ;;
  esac
done

banner
[[ "$EXECUTE" == "1" && "$PREFLIGHT" == "1" ]] && die "--preflight and --execute are mutually exclusive" 2

if [[ -z "$EXPECTED_SHA" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no release SHA supplied. Nothing was deployed. This packet refuses to mutate.
  preflight (no host mutation):
    SHADOW_READER_DSN=... DEPLOY_ROOT=... BACKEND_FILE=... RESTART_SERVICE=... \\
      HEALTH_URL=... AGENTS_URL=... READ_API_URL=... \\
      $0 <RELEASE_SHA> --preflight
  deploy:
    SHADOW_READER_DSN=... DEPLOY_ROOT=... BACKEND_FILE=... RESTART_SERVICE=... \\
      HEALTH_URL=... AGENTS_URL=... READ_API_URL=... \\
      $0 <RELEASE_SHA> --execute --ack $ACK_TOKEN
USAGE
  exit 2
fi

# ---- exact-RC-SHA gate (shared by preflight + execute) ----------------------
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be exactly 40 lowercase hex chars" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected release SHA $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"
[[ -x "$INNER" ]] || die "inner deploy script missing/not executable: $INNER" 2

# ---- reader-only DSN guard (value NEVER printed) ----------------------------
# Parses $SHADOW_READER_DSN LOCALLY (NO connection, NO psql/pg_isready/DB driver/
# socket/network) into user/host/port/dbname, then checks ONLY those parsed
# fields. It NEVER scans the URI scheme (so a legitimate postgresql:// reader URI
# passes) and NEVER scans the password. Reuses the A1 gate-6 parsing approach
# (URL form + libpq key=value form). The DSN and all parsed values stay unprinted;
# only the parsed ROLE NAME is exposed (in PARSED_READER_ROLE) for the preflight
# summary — never the host, port, dbname, or password.
validate_reader_dsn() {
  local dsn="${SHADOW_READER_DSN:-}"
  # (1) required
  [[ -n "$dsn" ]] || die "SHADOW_READER_DSN is not set (isolated SHADOW *reader* DSN required)" 4

  # (2) parse BOTH forms into user/host/port/dbname WITHOUT ever connecting.
  local user="" host="" port="" db="" body kv key val
  if [[ "$dsn" =~ ^postgres(ql)?:// ]]; then
    # URL form: postgres[ql]://[user[:pass]@]host[:port][/db][?query]
    body="${dsn#postgres://}"; body="${body#postgresql://}"
    case "$body" in *\?*) body="${body%%\?*}";; esac          # drop ?query
    case "$body" in */*)  db="${body#*/}"; body="${body%%/*}";; esac
    # userinfo: everything before the last '@' is user[:pass]; keep user only.
    if [[ "$body" == *@* ]]; then
      local userinfo="${body%@*}"; body="${body##*@}"
      user="${userinfo%%:*}"                                  # strip :password
    fi
    # body is now host[:port]
    if [[ "$body" == *:* ]]; then host="${body%%:*}"; port="${body##*:}"; else host="$body"; fi
  elif [[ "$dsn" == *=* ]]; then
    # libpq key=value form: user=... host=... port=... dbname=... password=...
    for kv in $dsn; do
      [[ "$kv" == *=* ]] || die "REJECT: malformed libpq token in SHADOW_READER_DSN" 4
      key="${kv%%=*}"; val="${kv#*=}"; key="${key,,}"
      case "$key" in
        user)   user="$val" ;;
        host)   host="$val" ;;
        port)   port="$val" ;;
        dbname) db="$val" ;;
        *) : ;;   # password/sslmode/etc: benign, ignored — never scanned
      esac
    done
  else
    die "REJECT: SHADOW_READER_DSN is malformed (not a postgres URL or libpq key=value DSN)" 4
  fi

  # (3) require the reader role EXACTLY (checked on the parsed user, not the URI).
  [[ -n "$user" ]] || die "REJECT: could not parse a user from SHADOW_READER_DSN" 4
  [[ "$user" == "agentic_runtime_reader" ]] \
    || die "REJECT: SHADOW_READER_DSN must connect as agentic_runtime_reader (read-only)" 4

  # (4) reject a writer/admin/prod IDENTITY — checked ONLY on parsed user/host/db,
  #     NEVER the scheme and NEVER the password.
  local luser="${user,,}" lhost="${host,,}" ldb="${db,,}"
  case "$luser" in
    postgres|*_rw|*superuser*|*admin*|*prod*|*production*)
      die "REJECT: SHADOW_READER_DSN user is a writer/admin/prod identity" 4 ;;
  esac
  [[ -n "$host" ]] || die "REJECT: could not parse host from SHADOW_READER_DSN" 4
  case "$lhost" in *prod*|*production*)
    die "REJECT: SHADOW_READER_DSN host contains a 'prod' substring — refusing" 4 ;;
  esac
  [[ -n "$db" ]] || die "REJECT: could not parse dbname from SHADOW_READER_DSN" 4
  case "$ldb" in
    trade_ai) die "REJECT: SHADOW_READER_DSN dbname is production 'trade_ai' — read plane is LAB/SHADOW only" 4 ;;
    *prod*|*production*) die "REJECT: SHADOW_READER_DSN dbname contains a 'prod' substring — refusing" 4 ;;
  esac

  # (5) success: DSN/host/port/db/password never printed — only the parsed role.
  PARSED_READER_ROLE="$user"
  note "SHADOW reader DSN accepted (read-only identity; value never printed)"
}

# ---- required host inputs ---------------------------------------------------
require_host_inputs() {
  local missing=()
  [[ -n "${DEPLOY_ROOT:-}" ]]     || missing+=(DEPLOY_ROOT)
  [[ -n "${BACKEND_FILE:-}" ]]    || missing+=(BACKEND_FILE)
  [[ -n "${RESTART_SERVICE:-}" ]] || missing+=(RESTART_SERVICE)
  [[ -n "${HEALTH_URL:-}" ]]      || missing+=(HEALTH_URL)
  [[ -n "${AGENTS_URL:-}" ]]      || missing+=(AGENTS_URL)
  [[ -n "${READ_API_URL:-}" ]]    || missing+=(READ_API_URL)
  [[ ${#missing[@]} -eq 0 ]] || die "missing required host inputs: ${missing[*]}" 2
}

# ---- zero-authority body assertion (shared) ---------------------------------
# $1 = response body. read_only:true required; NO true authority field permitted.
assert_zero_authority() {
  echo "$1" | grep -q '"read_only" *: *true' \
    || die "read API body is not read_only:true" 2
  if echo "$1" | grep -qiE '"(mutation|provider_call|service_control|schedule_change|financial_action)" *: *true'; then
    die "read API body advertises non-zero authority (mutation/provider_call/service_control/schedule_change/financial_action)" 2
  fi
}

# ---- STRICT pre-connect baseline (fail-closed; read-only HTTP only) ---------
# Require EXACTLY HTTP 503 with a read_only, zero-authority, disconnected body.
# ALL other statuses (000, 200, redirects, auth, 404, 500) BLOCK. Sets
# PRE_CONNECT_STATUS. This performs a read-only HTTP GET and NO host mutation.
strict_pre_connect_503() {
  command -v curl >/dev/null 2>&1 || die "curl required for the strict pre-connect baseline" 2
  local resp code body
  resp="$(curl -sS -w '\n%{http_code}' "$READ_API_URL" 2>/dev/null || true)"
  code="${resp##*$'\n'}"; body="${resp%$'\n'*}"
  [[ "$code" == "503" ]] \
    || die "strict pre-connect baseline: READ_API returned HTTP $code (require EXACTLY 503; ALL other statuses BLOCK) — no host mutation" 2
  assert_zero_authority "$body"
  echo "$body" | grep -qiE '"connected" *: *false|disconnected|unavailable|not[_-]?connected' \
    || die "strict pre-connect baseline: body does not indicate a disconnected/unavailable read plane — no host mutation" 2
  if echo "$body" | grep -qiE '"connected" *: *true'; then
    die "strict pre-connect baseline: body claims healthy-connected before wiring — no host mutation" 2
  fi
  PRE_CONNECT_STATUS="$code"
  note "strict pre-connect baseline OK (HTTP 503, read_only, zero authority, disconnected)"
}

# =============================================================================
# PREFLIGHT — genuine no-mutation readiness check.
# =============================================================================
if [[ "$PREFLIGHT" == "1" ]]; then
  note "PREFLIGHT (no host mutation) — read-only FS / systemd-status / HTTP checks + inner dry-run"

  # (2) HEAD == SHA already verified above. (3) reject dirty/untracked worktree.
  CLEAN_TREE="clean"
  if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    CLEAN_TREE="DIRTY"
    die "worktree is dirty/untracked; preflight refuses (clean tree required)" 2
  fi

  # (5) required inputs; (4) corrected parsed-field reader DSN guard.
  require_host_inputs
  validate_reader_dsn

  # (6) read-only verification — NO mutation.
  [[ -d "$DEPLOY_ROOT" ]] || die "DEPLOY_ROOT is not a directory: $DEPLOY_ROOT" 2
  RELEASES_DIR="$DEPLOY_ROOT/releases"
  BACKUPS_DIR="$DEPLOY_ROOT/backups"
  CURRENT_LINK="$DEPLOY_ROOT/current"
  CURRENT_TARGET="<none>"
  if [[ -L "$CURRENT_LINK" ]]; then
    CURRENT_TARGET="$(readlink -f "$CURRENT_LINK" 2>/dev/null || echo '<unresolved>')"
  elif [[ -e "$CURRENT_LINK" ]]; then
    CURRENT_TARGET="$(readlink -f "$CURRENT_LINK" 2>/dev/null || echo "$CURRENT_LINK")"
  fi
  [[ -f "$BACKEND_FILE" ]] || die "BACKEND_FILE does not exist or is not a regular file: $BACKEND_FILE" 2

  # restart service exists — read-only systemd status (NEVER restart/reload).
  command -v systemctl >/dev/null 2>&1 || die "systemctl unavailable for the read-only unit check" 2
  systemctl cat "$RESTART_SERVICE" >/dev/null 2>&1 \
    || systemctl status "$RESTART_SERVICE" >/dev/null 2>&1 \
    || die "restart service unit not found (read-only check): $RESTART_SERVICE" 2

  # repo backend syntax passes (read-only compile; NO dependency install).
  PYBIN="${PYBIN:-$REPO_ROOT/.venv/bin/python}"; [[ -x "$PYBIN" ]] || PYBIN="python3"
  "$PYBIN" -m py_compile "$REPO_ROOT/scripts/portfolio_server.py" \
    || die "repo backend failed syntax validation" 2

  # Command Center build inputs exist (NO build here).
  [[ -f "$CC_DIR/package.json" ]] || die "Command Center build input missing: $CC_DIR/package.json" 2

  # strict pre-connect HTTP-503 baseline passes (read-only HTTP).
  strict_pre_connect_503

  # (7) reuse the inner DRY-RUN path (no mutation).
  note "invoking inner dry-run (no mutation): $INNER $EXPECTED_SHA --dry-run"
  "$INNER" "$EXPECTED_SHA" --dry-run >/dev/null \
    || die "inner dry-run reported a problem" 2

  # (8) print the readiness summary. (9) NEVER print DSN / user / password.
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  cat <<PF
[A2][PREFLIGHT] release_sha=$EXPECTED_SHA
[A2][PREFLIGHT] clean_tree=$CLEAN_TREE
[A2][PREFLIGHT] deploy_root=$DEPLOY_ROOT
[A2][PREFLIGHT] backend_file=$BACKEND_FILE
[A2][PREFLIGHT] restart_service=$RESTART_SERVICE
[A2][PREFLIGHT] health_url=$HEALTH_URL
[A2][PREFLIGHT] agents_url=$AGENTS_URL
[A2][PREFLIGHT] read_api_url=$READ_API_URL
[A2][PREFLIGHT] current_static_target=$CURRENT_TARGET
[A2][PREFLIGHT] proposed_release=$RELEASES_DIR/${EXPECTED_SHA}-${TS}
[A2][PREFLIGHT] proposed_backup=$BACKUPS_DIR/${EXPECTED_SHA}-${TS}
[A2][PREFLIGHT] reader_role=$PARSED_READER_ROLE
[A2][PREFLIGHT] pre_connect_status=$PRE_CONNECT_STATUS
[A2][PREFLIGHT] host_mutations=0
PF
  note "PREFLIGHT PASSED — no host mutation performed."
  exit 0
fi

# =============================================================================
# PREPARE-ONLY (default) — nothing deployed.
# =============================================================================
if [[ "$EXECUTE" != "1" ]]; then
  cat <<PLAN

PREPARE-ONLY PLAN — nothing was deployed:
  1) validate SHADOW_READER_DSN is the read-only agentic_runtime_reader (value never printed)
  2) --preflight (no host mutation): SHA + clean tree + inputs + parsed reader identity +
       read-only FS/systemd-status checks + STRICT HTTP-503 pre-connect baseline + inner dry-run
  3) --execute wraps $INNER <SHA> --execute, which fail-closed enforces:
       exact-ref + clean-tree gate; STRICT HTTP-503 pre-connect baseline BEFORE any
       build/backup/symlink/restart; backend + static backup; build; atomic static swap;
       ONE named service restart (\$RESTART_SERVICE); interactive operator ack;
       STRICT HTTP-200 post-connect acceptance (read_only, zero authority, connected to the
       shadow reader, no execution agent); automatic backend+static rollback + post-rollback
       health verification on ANY failure (incl. a 503-after, a non-read-only body, or any
       authority=true). Execution agents remain DISABLED throughout.

To preflight (no host mutation):
  SHADOW_READER_DSN=... DEPLOY_ROOT=... BACKEND_FILE=... RESTART_SERVICE=... \\
    HEALTH_URL=... AGENTS_URL=... READ_API_URL=... \\
    $0 $EXPECTED_SHA --preflight

To deploy:
  SHADOW_READER_DSN=... DEPLOY_ROOT=... BACKEND_FILE=... RESTART_SERVICE=... \\
    HEALTH_URL=... AGENTS_URL=... READ_API_URL=... \\
    $0 $EXPECTED_SHA --execute --ack $ACK_TOKEN
PLAN
  exit 3
fi

# =============================================================================
# EXECUTE — delegate the guarded host mutation to the inner script.
# =============================================================================
[[ "$ACK" == "$ACK_TOKEN" ]] || die "--execute requires --ack $ACK_TOKEN (typed acknowledgement)" 2
: "${READ_API_URL:?READ_API_URL is required (the inner enforces the strict pre-connect 503 baseline)}"

# Execution-time revalidation — a prior preflight NEVER bypasses this. Immediately
# before delegating to the mutation gate, RE-RUN: exact SHA + clean tree + parsed
# reader identity. The STRICT HTTP-503 pre-connect baseline and the STRICT HTTP-200
# post-connect acceptance are re-run fail-closed INSIDE the inner script — the pre-
# connect one immediately before its first host mutation (before any build/backup/
# symlink/restart), the post-connect one after the single restart.
validate_reader_dsn
HEAD_NOW="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_NOW" == "$EXPECTED_SHA" ]] || die "HEAD $HEAD_NOW moved off release SHA $EXPECTED_SHA; refuse to deploy" 2
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || die "worktree became dirty; refuse to deploy" 2
note "execution-time revalidation OK (exact SHA + clean tree + parsed reader identity)"

# The inner script performs its own interactive 'DEPLOY <SHA>' acknowledgement,
# clean-checkout gate, the STRICT pre-connect 503 baseline (before any mutation),
# backup, atomic swap, ONE restart, the STRICT post-connect 200 acceptance, and
# automatic backend+static rollback + post-rollback health verification on any
# failure. We export the reader DSN for the connected read API (value never echoed).
export AGENT_RUNTIME_READER_DSN="$SHADOW_READER_DSN"
note "delegating to $INNER $EXPECTED_SHA --execute (execution agents stay disabled)"
"$INNER" "$EXPECTED_SHA" --execute
note "read-plane deploy complete. STRICT pre-connect 503 + post-connect 200 + rollback handled by inner script."
unset AGENT_RUNTIME_READER_DSN SHADOW_READER_DSN
note "reader DSN env cleared."
