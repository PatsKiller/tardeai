#!/usr/bin/env bash
# =============================================================================
# PACKET F — Moomoo Stage 0 foundation (PREPARE-ONLY / DEFAULT-DISABLED).
# =============================================================================
# Read-plane only. NO order routing, NO trade unlock, NO agent OPERATIONAL,
# NO schedule enable. Secrets / DSN values are NEVER printed.
#
# USAGE:
#   packet_f_moomoo_stage0.sh                              # exit 2
#   packet_f_moomoo_stage0.sh <RELEASE_SHA>                # prepare-only, exit 3
#   packet_f_moomoo_stage0.sh <RELEASE_SHA> --self-check
#   packet_f_moomoo_stage0.sh <RELEASE_SHA> --preflight --ack APPLY-MOOMOO-STAGE0
#   packet_f_moomoo_stage0.sh <RELEASE_SHA> --execute  --ack APPLY-MOOMOO-STAGE0
#
# EXIT: 0 ok · 2 usage/gate · 3 prepare-only · 4 preflight fail
# =============================================================================
set -euo pipefail

readonly PACKET="F:moomoo_stage0"
readonly ACK_TOKEN="APPLY-MOOMOO-STAGE0"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly PYTHON="${VENV_PYTHON:-$REPO_ROOT/.venv/bin/python}"
readonly RUNNER="$REPO_ROOT/scripts/operator_packets/packet_f_moomoo_stage0.py"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY / DEFAULT-DISABLED ==="; }
die()    { echo "[F][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[F] $*"; }

EXPECTED_SHA=""
SELF_CHECK=0
PREFLIGHT=0
EXECUTE=0
PROBE=0
ACK=""
CONFIG=""
REPORT_JSON=""
NEXT=""

for arg in "$@"; do
  if [[ "$NEXT" == "ack" ]]; then ACK="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "config" ]]; then CONFIG="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "report-json" ]]; then REPORT_JSON="$arg"; NEXT=""; continue; fi
  case "$arg" in
    --self-check)   SELF_CHECK=1 ;;
    --preflight)    PREFLIGHT=1 ;;
    --execute)      EXECUTE=1 ;;
    --probe-opend)  PROBE=1 ;;
    --ack)          NEXT="ack" ;;
    --config)       NEXT="config" ;;
    --report-json)  NEXT="report-json" ;;
    *)
      if [[ -z "$EXPECTED_SHA" ]]; then EXPECTED_SHA="$arg"
      else die "unexpected argument: $arg" 2; fi
      ;;
  esac
done

banner
[[ -f "$RUNNER" ]] || die "python runner missing: $RUNNER" 2

if [[ -z "$EXPECTED_SHA" && "$SELF_CHECK" != "1" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no release SHA / action. Nothing was enabled. Stage 0 is read-plane only.
  usage: $0 <RELEASE_SHA> --self-check
         $0 <RELEASE_SHA> --preflight --ack $ACK_TOKEN [--config PATH] [--probe-opend]
         $0 <RELEASE_SHA> --execute  --ack $ACK_TOKEN [--config PATH]
USAGE
  exit 2
fi

PYBIN="$PYTHON"; [[ -x "$PYBIN" ]] || PYBIN="python3"

if [[ "$SELF_CHECK" == "1" ]]; then
  if [[ -n "$EXPECTED_SHA" ]]; then
    [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be 40 lowercase hex" 2
    HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
    [[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != $EXPECTED_SHA" 2
    note "exact-RC-SHA gate OK @ $HEAD_SHA"
  fi
  exec "$PYBIN" "$RUNNER" --self-check
fi

[[ -n "$EXPECTED_SHA" ]] || die "release SHA required" 2
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be 40 lowercase hex" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"

if [[ "$PREFLIGHT" != "1" && "$EXECUTE" != "1" ]]; then
  note "PREPARE-ONLY: neither --preflight nor --execute; Stage 0 stays disabled."
  note "NO order routing. NO trade unlock. NO agent OPERATIONAL. NO schedule enable."
  note "To preflight: $0 $EXPECTED_SHA --preflight --ack $ACK_TOKEN"
  exit 3
fi

[[ "$ACK" == "$ACK_TOKEN" ]] || die "--preflight/--execute requires --ack $ACK_TOKEN" 2

ARGS=()
[[ "$PREFLIGHT" == "1" ]] && ARGS+=(--preflight)
[[ "$EXECUTE" == "1" ]] && ARGS+=(--execute)
[[ "$PROBE" == "1" ]] && ARGS+=(--probe-opend)
ARGS+=(--ack "$ACK_TOKEN")
[[ -n "$CONFIG" ]] && ARGS+=(--config "$CONFIG")
[[ -n "$REPORT_JSON" ]] && ARGS+=(--report-json "$REPORT_JSON")

note "handing off to Stage 0 runner (read-plane only)"
# Deliberately do not echo any env secret/DSN values.
exec "$PYBIN" "$RUNNER" "${ARGS[@]}"
