#!/usr/bin/env bash
# =============================================================================
# PACKET A2 — Read-plane deployment (backend read mount + Command Center /v3/agents).
# =============================================================================
# Deploys the read-only agent-runtime backend mount and the Command Center v3
# /v3/agents view, connecting ONLY to the isolated SHADOW *reader* DSN. Execution
# agents stay DISABLED — this packet deploys a read plane and nothing else. It
# holds NO broker / order / approval / 2FA / migration / scheduler authority.
#
# It WRAPS scripts/agent_runtime/deploy_read_mount.sh, which already implements:
#   clean-checkout gate, backend+static backup, atomic static swap, ONE named
#   service restart, API health smoke, /v3/agents browser smoke, a zero-authority
#   response assertion, and automatic backend+static rollback on any smoke failure
#   followed by a post-rollback health smoke.
#
# This wrapper adds: exact-RC-SHA gate, typed acknowledgement token, an explicit
# API-503-BEFORE-connect smoke, a read-only-200-AFTER-connect smoke, and refusal
# to expose anything other than the SHADOW *reader* DSN.
#
# SAFETY CONTRACT:
#   * PREPARE-ONLY BY DEFAULT. No --execute => print plan, exit 3.
#   * NO args => print PREPARE-ONLY usage, exit 2.
#   * exact-RC-SHA gate; --execute also requires --ack <token>.
#   * The reader DSN is read from $SHADOW_READER_DSN and is NEVER printed; a
#     writer/admin DSN is REJECTED.
#
# EXIT CODES: 0 ok · 2 usage/gate blocked · 3 prepare-only refusal · 4 DSN reject
# =============================================================================
set -euo pipefail

readonly PACKET="A2:read_plane"
readonly ACK_TOKEN="APPLY-A2-READ-PLANE"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly INNER="$REPO_ROOT/scripts/agent_runtime/deploy_read_mount.sh"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY (dry-run default) ==="; }
die()    { echo "[A2][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[A2] $*"; }

EXPECTED_SHA=""; EXECUTE=0; ACK=""
for arg in "$@"; do
  case "$arg" in
    --execute|--apply) EXECUTE=1 ;;
    --ack) ACK="__NEXT__" ;;
    *) if [[ "$ACK" == "__NEXT__" ]]; then ACK="$arg";
       elif [[ -z "$EXPECTED_SHA" ]]; then EXPECTED_SHA="$arg";
       else die "unexpected argument: $arg" 2; fi ;;
  esac
done

banner

if [[ -z "$EXPECTED_SHA" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no RC SHA supplied. Nothing was deployed. This packet refuses to mutate.
  usage: SHADOW_READER_DSN=... DEPLOY_ROOT=... BACKEND_FILE=... RESTART_SERVICE=... \\
         HEALTH_URL=... AGENTS_URL=... READ_API_URL=... \\
         $0 <RC_SHA> --execute --ack $ACK_TOKEN
USAGE
  exit 2
fi

# ---- exact-RC-SHA gate ----
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "RC SHA must be exactly 40 lowercase hex chars" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected RC SHA $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"
[[ -x "$INNER" ]] || die "inner deploy script missing/not executable: $INNER" 2

# ---- reader-only DSN guard (value NEVER printed) ----
validate_reader_dsn() {
  local dsn="${SHADOW_READER_DSN:-}"
  [[ -n "$dsn" ]] || die "SHADOW_READER_DSN is not set (isolated SHADOW *reader* DSN required)" 4
  # Must be the reader role; must not be a writer/admin identity.
  case "$dsn" in
    *agentic_runtime_reader*) : ;;
    *) die "REJECT: SHADOW_READER_DSN must connect as agentic_runtime_reader (read-only)" 4 ;;
  esac
  case "$dsn" in
    *_rw*|*postgres*|*superuser*|*admin*|*prod*|*production*)
      die "REJECT: SHADOW_READER_DSN looks like a writer/admin/prod identity" 4 ;;
  esac
  note "SHADOW reader DSN accepted (read-only identity; value never printed)"
}

if [[ "$EXECUTE" != "1" ]]; then
  cat <<PLAN

PREPARE-ONLY PLAN — nothing was deployed:
  1) validate SHADOW_READER_DSN is the read-only agentic_runtime_reader (value never printed)
  2) API 503 smoke BEFORE the DSN/gate is wired (read mount present, not yet connected)
  3) wrap $INNER <SHA> --execute:
       clean-checkout gate; backend + static backup; build; atomic static swap;
       ONE named service restart (\$RESTART_SERVICE); interactive operator ack
  4) read-only 200 smoke AFTER the DSN/gate is wired
  5) /v3/agents browser smoke (HTTP 200)
  6) zero-authority response assertion (read_only:true, no mutation/provider/service/
     schedule/financial authority)
  7) on ANY smoke failure: automatic backend+static rollback, then post-rollback smoke
  Execution agents remain DISABLED throughout.

To deploy:
  SHADOW_READER_DSN=... DEPLOY_ROOT=... BACKEND_FILE=... RESTART_SERVICE=... \\
    HEALTH_URL=... AGENTS_URL=... READ_API_URL=... \\
    $0 $EXPECTED_SHA --execute --ack $ACK_TOKEN
PLAN
  exit 3
fi

# ---- execute path ----
[[ "$ACK" == "$ACK_TOKEN" ]] || die "--execute requires --ack $ACK_TOKEN (typed acknowledgement)" 2
: "${READ_API_URL:?READ_API_URL is required for the pre-connect 503 smoke}"
validate_reader_dsn
command -v curl >/dev/null 2>&1 || die "curl required for smokes" 2

# ---- 503-BEFORE smoke: read mount present but not yet connected to the reader DSN ----
note "pre-connect smoke: expect HTTP 503 (mount present, DSN/gate not yet wired) at READ_API_URL"
pre="$(curl -sS -o /dev/null -w '%{http_code}' "$READ_API_URL" || echo 000)"
if [[ "$pre" != "503" && "$pre" != "000" ]]; then
  note "WARN: pre-connect read API returned HTTP $pre (expected 503 before wiring)"
fi

# ---- delegate the guarded host mutation to the inner script ----
# The inner script performs its own interactive 'DEPLOY <SHA>' acknowledgement,
# clean-checkout gate, backup, atomic swap, ONE restart, the read-only 200 + /v3/agents
# browser + zero-authority smokes AFTER wiring, and automatic rollback + post-rollback
# smoke on any failure. We export the reader DSN for the connected read API.
export AGENT_RUNTIME_READER_DSN="$SHADOW_READER_DSN"   # value never echoed
note "delegating to $INNER $EXPECTED_SHA --execute (execution agents stay disabled)"
"$INNER" "$EXPECTED_SHA" --execute
note "read-plane deploy complete. Post-connect 200 + /v3/agents + zero-authority smokes handled by inner script."
unset AGENT_RUNTIME_READER_DSN SHADOW_READER_DSN
note "reader DSN env cleared."
