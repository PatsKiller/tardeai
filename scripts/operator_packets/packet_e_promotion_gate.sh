#!/usr/bin/env bash
# =============================================================================
# PACKET E wrapper — Phase 10 promotion gate (PREPARE-ONLY / DEFAULT-DISABLED).
# =============================================================================
# Thin wrapper around packet_e_promotion_gate.py.
#
# SAFETY CONTRACT:
#   * PREPARE-ONLY BY DEFAULT (no --preflight/--execute => plan, exit 3).
#   * NO args => exit 2.
#   * Requires --ack PROMOTE-AGENT-OPERATIONAL-E and an explicit AGENT_ID list.
#   * Preflight evaluates Packet D report / LAB counts only (no promotion).
#   * --execute NEVER marks any agent OPERATIONAL. Phase 11 human sign-off is
#     still required; at most a signed intent is written under docs/operations/.
#   * No broker / schedule enable / production trade_ai writes. DSN never printed.
#
# USAGE:
#   packet_e_promotion_gate.sh                                    # exit 2
#   packet_e_promotion_gate.sh <RELEASE_SHA>                      # prepare-only, exit 3
#   packet_e_promotion_gate.sh <RELEASE_SHA> --self-check
#   packet_e_promotion_gate.sh <RELEASE_SHA> --preflight \
#       --agent-id sentinel --agent-id darwin \
#       --ack PROMOTE-AGENT-OPERATIONAL-E \
#       --packet-d-report PATH [--lab-counts PATH]
#   packet_e_promotion_gate.sh <RELEASE_SHA> --execute \
#       --agent-id sentinel --ack PROMOTE-AGENT-OPERATIONAL-E \
#       --packet-d-report PATH [--write-intent]
#
# EXIT CODES: 0 ok · 2 usage/gate/disabled · 3 prepare-only · 4 preflight/error
# =============================================================================
set -euo pipefail

readonly PACKET="E:promotion_gate"
readonly ACK_TOKEN="PROMOTE-AGENT-OPERATIONAL-E"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly PYTHON="${VENV_PYTHON:-$REPO_ROOT/.venv/bin/python}"
readonly RUNNER="$REPO_ROOT/scripts/operator_packets/packet_e_promotion_gate.py"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY / DEFAULT-DISABLED ==="; }
die()    { echo "[E][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[E] $*"; }

EXPECTED_SHA=""
SELF_CHECK=0
PREFLIGHT=0
EXECUTE=0
WRITE_INTENT=0
ACK=""
AGENT_IDS=()
AGENTS_CSV=""
PACKET_D_REPORT=""
LAB_COUNTS=""
REPORT_JSON=""
NEXT=""

for arg in "$@"; do
  if [[ "$NEXT" == "ack" ]]; then ACK="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "agent-id" ]]; then AGENT_IDS+=("$arg"); NEXT=""; continue; fi
  if [[ "$NEXT" == "agents" ]]; then AGENTS_CSV="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "packet-d-report" ]]; then PACKET_D_REPORT="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "lab-counts" ]]; then LAB_COUNTS="$arg"; NEXT=""; continue; fi
  if [[ "$NEXT" == "report-json" ]]; then REPORT_JSON="$arg"; NEXT=""; continue; fi
  case "$arg" in
    --self-check)       SELF_CHECK=1 ;;
    --preflight)        PREFLIGHT=1 ;;
    --execute)          EXECUTE=1 ;;
    --write-intent)     WRITE_INTENT=1 ;;
    --ack)              NEXT="ack" ;;
    --agent-id)         NEXT="agent-id" ;;
    --agents)           NEXT="agents" ;;
    --packet-d-report)  NEXT="packet-d-report" ;;
    --lab-counts)       NEXT="lab-counts" ;;
    --report-json)      NEXT="report-json" ;;
    *)
      if [[ -z "$EXPECTED_SHA" ]]; then
        EXPECTED_SHA="$arg"
      else
        die "unexpected argument: $arg" 2
      fi
      ;;
  esac
done

banner
[[ -f "$RUNNER" ]] || die "python runner missing: $RUNNER" 2

# ---- no-args ----
if [[ -z "$EXPECTED_SHA" && "$SELF_CHECK" != "1" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no release SHA / action supplied. Nothing was promoted.
This packet is default-disabled and NEVER marks any agent OPERATIONAL.
  usage: $0 <RELEASE_SHA> --self-check
         $0 <RELEASE_SHA> --preflight --agent-id <ID> [--agent-id <ID> ...] \\
              --ack $ACK_TOKEN [--packet-d-report PATH] [--lab-counts PATH]
         $0 <RELEASE_SHA> --execute --agent-id <ID> ... --ack $ACK_TOKEN \\
              [--packet-d-report PATH] [--lab-counts PATH] [--write-intent]
USAGE
  exit 2
fi

PYBIN="$PYTHON"; [[ -x "$PYBIN" ]] || PYBIN="python3"

# ---- self-check (optional SHA gate when SHA provided) ----
if [[ "$SELF_CHECK" == "1" ]]; then
  if [[ -n "$EXPECTED_SHA" ]]; then
    [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be exactly 40 lowercase hex chars" 2
    HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
    [[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected release SHA $EXPECTED_SHA" 2
    note "exact-RC-SHA gate OK @ $HEAD_SHA"
  fi
  exec "$PYBIN" "$RUNNER" --self-check
fi

# ---- exact-RC-SHA gate ----
[[ -n "$EXPECTED_SHA" ]] || die "release SHA required" 2
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be exactly 40 lowercase hex chars" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected release SHA $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"

# ---- prepare-only: no action ----
if [[ "$PREFLIGHT" != "1" && "$EXECUTE" != "1" ]]; then
  note "PREPARE-ONLY: neither --preflight nor --execute supplied; promotion gate stays disabled."
  note "No agent becomes OPERATIONAL. Timers/cron remain disabled. CANDIDATE ≠ policy."
  note "To preflight: $0 $EXPECTED_SHA --preflight --agent-id <ID> --ack $ACK_TOKEN --packet-d-report PATH"
  note "To record intent only (still not OPERATIONAL): $0 $EXPECTED_SHA --execute --agent-id <ID> --ack $ACK_TOKEN --write-intent"
  exit 3
fi

# ---- ack + agents required for preflight/execute ----
[[ "$ACK" == "$ACK_TOKEN" ]] || die "--preflight/--execute requires --ack $ACK_TOKEN" 2
if [[ ${#AGENT_IDS[@]} -eq 0 && -z "$AGENTS_CSV" ]]; then
  die "explicit AGENT_ID list required (--agent-id and/or --agents)" 2
fi

# Build python argv — never pass DSN values (and never echo env DSNs).
ARGS=()
if [[ "$PREFLIGHT" == "1" ]]; then ARGS+=(--preflight); fi
if [[ "$EXECUTE" == "1" ]]; then ARGS+=(--execute); fi
if [[ "$WRITE_INTENT" == "1" ]]; then ARGS+=(--write-intent); fi
ARGS+=(--ack "$ACK_TOKEN")
for aid in "${AGENT_IDS[@]:-}"; do
  [[ -n "$aid" ]] && ARGS+=(--agent-id "$aid")
done
[[ -n "$AGENTS_CSV" ]] && ARGS+=(--agents "$AGENTS_CSV")
[[ -n "$PACKET_D_REPORT" ]] && ARGS+=(--packet-d-report "$PACKET_D_REPORT")
[[ -n "$LAB_COUNTS" ]] && ARGS+=(--lab-counts "$LAB_COUNTS")
[[ -n "$REPORT_JSON" ]] && ARGS+=(--report-json "$REPORT_JSON")

note "handing off to promotion gate runner (agents remain SHADOW; no OPERATIONAL mutation)"
# Deliberately do not export or print SHADOW_DSN / LAB_DSN.
exec "$PYBIN" "$RUNNER" "${ARGS[@]}"
