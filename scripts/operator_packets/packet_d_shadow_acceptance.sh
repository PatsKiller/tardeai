#!/usr/bin/env bash
# =============================================================================
# PACKET D wrapper — SHADOW agent acceptance runner (DEFAULT-DISABLED).
# =============================================================================
# Thin, prepare-only wrapper around packet_d_shadow_acceptance.py. It adds the
# exact-RC-SHA gate, then hands off to the Python runner which is itself
# default-disabled (refuses without --run-shadow AND the typed --ack token) and
# SHADOW-pinned (no agent ever becomes OPERATIONAL from running it).
#
# SAFETY CONTRACT:
#   * PREPARE-ONLY BY DEFAULT (no --run-shadow => plan, exit 3). NO args => exit 2.
#   * exact-RC-SHA gate.
#   * SHADOW_DSN (agentic_runtime_shadow_rw) is read from env; value NEVER printed.
#   * No broker/order/approval/2FA/schedule authority; no agent promotion.
#
# USAGE:
#   packet_d_shadow_acceptance.sh                       # PREPARE-ONLY, exit 2
#   packet_d_shadow_acceptance.sh <RELEASE_SHA>              # plan, exit 3
#   packet_d_shadow_acceptance.sh <RELEASE_SHA> --self-check # invariants only, no DB
#   SHADOW_DSN=... packet_d_shadow_acceptance.sh <RELEASE_SHA> --run-shadow --ack RUN-SHADOW-ACCEPTANCE-D
#
# EXIT CODES: 0 ok · 2 usage/gate/disabled refusal · 3 prepare-only/threshold · 4 error
# =============================================================================
set -euo pipefail

readonly PACKET="D:shadow_acceptance"
readonly ACK_TOKEN="RUN-SHADOW-ACCEPTANCE-D"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly PYTHON="${VENV_PYTHON:-$REPO_ROOT/.venv/bin/python}"
readonly RUNNER="$REPO_ROOT/scripts/operator_packets/packet_d_shadow_acceptance.py"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY / DEFAULT-DISABLED ==="; }
die()    { echo "[D][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[D] $*"; }

EXPECTED_SHA=""; RUN_SHADOW=0; SELF_CHECK=0; ACK=""
NEXT=""
for arg in "$@"; do
  if [[ "$NEXT" == "ack" ]]; then ACK="$arg"; NEXT=""; continue; fi
  case "$arg" in
    --run-shadow) RUN_SHADOW=1 ;;
    --self-check) SELF_CHECK=1 ;;
    --ack)        NEXT="ack" ;;
    *) if [[ -z "$EXPECTED_SHA" ]]; then EXPECTED_SHA="$arg"; else die "unexpected argument: $arg" 2; fi ;;
  esac
done

banner
[[ -f "$RUNNER" ]] || die "python runner missing: $RUNNER" 2

if [[ -z "$EXPECTED_SHA" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no release SHA supplied. Nothing was run. This packet is default-disabled.
  usage: SHADOW_DSN=... $0 <RELEASE_SHA> --run-shadow --ack $ACK_TOKEN
         $0 <RELEASE_SHA> --self-check     # invariants only, no DB
USAGE
  exit 2
fi

# ---- exact-RC-SHA gate ----
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be exactly 40 lowercase hex chars" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected release SHA $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"

PYBIN="$PYTHON"; [[ -x "$PYBIN" ]] || PYBIN="python3"

# ---- self-check path (no DB, proves guards fire) ----
if [[ "$SELF_CHECK" == "1" ]]; then
  exec "$PYBIN" "$RUNNER" --self-check
fi

# ---- prepare-only: no --run-shadow ----
if [[ "$RUN_SHADOW" != "1" ]]; then
  note "PREPARE-ONLY: --run-shadow not supplied; the SHADOW acceptance runner stays disabled."
  note "No agent becomes OPERATIONAL. All agents remain SHADOW until explicit acceptance."
  note "To run: SHADOW_DSN=... $0 $EXPECTED_SHA --run-shadow --ack $ACK_TOKEN"
  exit 3
fi

[[ "$ACK" == "$ACK_TOKEN" ]] || die "--run-shadow requires --ack $ACK_TOKEN (typed acknowledgement)" 2
[[ -n "${SHADOW_DSN:-}" ]] || die "SHADOW_DSN not set (agentic_runtime_shadow_rw DSN; value never printed)" 2

note "handing off to SHADOW runner (agents remain SHADOW; no promotion)"
exec "$PYBIN" "$RUNNER" --run-shadow --ack "$ACK_TOKEN"
