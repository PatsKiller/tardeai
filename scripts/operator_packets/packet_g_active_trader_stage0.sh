#!/usr/bin/env bash
# =============================================================================
# PACKET G — Active Trader Stage 0 (PREPARE-ONLY / DEFAULT-DISABLED).
# =============================================================================
# Baseline docs checksum + read-only health preflight. NEVER enables live_canary,
# order routes, session authorize, agent OPERATIONAL, or schedules.
# DSN / secrets NEVER printed.
#
# USAGE:
#   packet_g_active_trader_stage0.sh                         # exit 2
#   packet_g_active_trader_stage0.sh <RELEASE_SHA>           # prepare-only, exit 3
#   packet_g_active_trader_stage0.sh <RELEASE_SHA> --self-check
#   packet_g_active_trader_stage0.sh <RELEASE_SHA> --preflight --ack APPLY-AT-STAGE0
#   packet_g_active_trader_stage0.sh <RELEASE_SHA> --execute  --ack APPLY-AT-STAGE0
#
# EXIT: 0 ok · 2 usage/gate · 3 prepare-only · 4 preflight fail
# =============================================================================
set -euo pipefail

readonly PACKET="G:active_trader_stage0"
readonly ACK_TOKEN="APPLY-AT-STAGE0"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly PYTHON="${VENV_PYTHON:-$REPO_ROOT/.venv/bin/python}"
readonly RUNNER="$REPO_ROOT/scripts/operator_packets/packet_g_active_trader_stage0.py"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY / DEFAULT-DISABLED ==="; }
die()    { echo "[G][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[G] $*"; }

EXPECTED_SHA=""
SELF_CHECK=0
PREFLIGHT=0
EXECUTE=0
ACK=""
CONFIG=""
REPORT_JSON=""
NEXT=""

for arg in "$@"; do
  if [[ "$NEXT" == "ack" ]]; then ACK="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "config" ]]; then CONFIG="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "report-json" ]]; then REPORT_JSON="$arg"; NEXT=""; continue; fi
  case "$arg" in
    --self-check)  SELF_CHECK=1 ;;
    --preflight)   PREFLIGHT=1 ;;
    --execute)     EXECUTE=1 ;;
    --ack)         NEXT="ack" ;;
    --config)      NEXT="config" ;;
    --report-json) NEXT="report-json" ;;
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
PREPARE-ONLY: no release SHA / action. Nothing enabled. Stage 0 is read-only baseline.
  usage: $0 <RELEASE_SHA> --self-check
         $0 <RELEASE_SHA> --preflight --ack $ACK_TOKEN [--config PATH]
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
  note "PREPARE-ONLY: neither --preflight nor --execute; Active Trader Stage 0 stays disabled."
  note "write:false canary:false — NO live orders, NO session authorize, NO live_canary."
  note "To preflight: $0 $EXPECTED_SHA --preflight --ack $ACK_TOKEN"
  exit 3
fi

[[ "$ACK" == "$ACK_TOKEN" ]] || die "--preflight/--execute requires --ack $ACK_TOKEN" 2

ARGS=()
[[ "$PREFLIGHT" == "1" ]] && ARGS+=(--preflight)
[[ "$EXECUTE" == "1" ]] && ARGS+=(--execute)
ARGS+=(--ack "$ACK_TOKEN")
[[ -n "$CONFIG" ]] && ARGS+=(--config "$CONFIG")
[[ -n "$REPORT_JSON" ]] && ARGS+=(--report-json "$REPORT_JSON")

note "handing off to Stage 0 runner (read-only baseline)"
exec "$PYBIN" "$RUNNER" "${ARGS[@]}"
