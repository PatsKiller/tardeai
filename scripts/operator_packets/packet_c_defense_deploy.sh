#!/usr/bin/env bash
# =============================================================================
# PACKET C — Defense/Sectors deployment.
# =============================================================================
# Ordered, independently-gated deployment:
#   (1) deploy UI + api_v2 annotations                 [--deploy  --ack-deploy]
#   (2) validate live payloads (posture/monitor/recs)  [runs after (1); no ack]
#   (3) ONLY AFTERWARD switch the breadth producer to v4 [--switch-breadth --ack-switch]
#       (wraps scripts/defense_breadth_switch_packet.sh; NEVER edits schedules)
#   (4) the v10 recommendation producer stays DISABLED pending separate review
#       (hard guard: this packet refuses to enable it)
#
# The UI/API deploy (1) and the schedule/producer switch (3) are DISTINCT acks and
# can be run in separate operator sessions. Payload validation (2) gates the switch:
# --switch-breadth refuses unless the live payloads validate.
#
# ROLLBACK restores INDEPENDENTLY:
#   --rollback-static   prior static release
#   --rollback-backend  prior backend files (git bundle recorded at deploy)
#   --rollback-breadth  prior breadth-producer state (delegates to inner --rollback)
#   --rollback-payload  prior payload snapshot (sector_momentum_latest.json)
#
# SAFETY CONTRACT:
#   * PREPARE-ONLY BY DEFAULT (no --execute => plan, exit 3). NO args => exit 2.
#   * exact-RC-SHA gate; clean-checkout gate before mutation.
#   * NEVER edits schedules/timers/cron; NO broker/order/approval/2FA authority.
#   * HARD-REFUSES any attempt to enable defense_recommendations_v10.py.
#
# EXIT CODES: 0 ok · 2 usage/gate blocked · 3 prepare-only refusal · 5 step failed
# =============================================================================
set -euo pipefail

readonly PACKET="C:defense_deploy"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly LIVE_APP="$REPO_ROOT/apps/command-center-v3"
readonly LIVE_DIST="$LIVE_APP/dist"
readonly PYTHON="${VENV_PYTHON:-$REPO_ROOT/.venv/bin/python}"
readonly SWITCH_INNER="$REPO_ROOT/scripts/defense_breadth_switch_packet.sh"
readonly SNAPSHOT="$REPO_ROOT/data/runtime/sector_momentum_latest.json"
readonly V10_PRODUCER="scripts/defense_recommendations_v10.py"
readonly BACKUP_ROOT="${DEFENSE_BACKUP_ROOT:-/home/johnclaw/tradeai-deploy-backups/packet-c-defense}"
readonly LOOPBACK="${DEFENSE_LOOPBACK:-http://127.0.0.1:7777}"
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

readonly ACK_DEPLOY="APPLY-C-UI-API-DEPLOY"
readonly ACK_SWITCH="DEFENSE_BREADTH_SWITCH_EXACT20_SHADOW"   # inner script's token

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY (dry-run default) ==="; }
die()    { echo "[C][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[C] $*"; }
step()   { printf '\n[C] === %s ===\n' "$*"; }

EXPECTED_SHA=""; EXECUTE=0
DO_DEPLOY=0; DO_SWITCH=0
RB_STATIC=0; RB_BACKEND=0; RB_BREADTH=0; RB_PAYLOAD=0
ACK_DP=""; ACK_SW=""; RB_BREADTH_DIR=""
NEXT=""
for arg in "$@"; do
  if [[ -n "$NEXT" ]]; then case "$NEXT" in
      dp) ACK_DP="$arg";; sw) ACK_SW="$arg";; rbdir) RB_BREADTH_DIR="$arg";;
    esac; NEXT=""; continue; fi
  case "$arg" in
    --execute|--apply) EXECUTE=1 ;;
    --deploy)          DO_DEPLOY=1 ;;
    --switch-breadth)  DO_SWITCH=1 ;;
    --ack-deploy)      NEXT="dp" ;;
    --ack-switch)      NEXT="sw" ;;
    --rollback-static)  RB_STATIC=1 ;;
    --rollback-backend) RB_BACKEND=1 ;;
    --rollback-breadth) RB_BREADTH=1; NEXT="rbdir" ;;
    --rollback-payload) RB_PAYLOAD=1 ;;
    *) if [[ -z "$EXPECTED_SHA" ]]; then EXPECTED_SHA="$arg"; else die "unexpected argument: $arg" 2; fi ;;
  esac
done

banner

# HARD GUARD: v10 recommendation producer must stay disabled.
if [[ -n "${DEFENSE_ENABLE_V10:-}" ]]; then
  die "REFUSED: v10 recommendation producer ($V10_PRODUCER) must stay DISABLED pending separate review" 2
fi

if [[ -z "$EXPECTED_SHA" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no RC SHA supplied. Nothing was deployed. This packet refuses to mutate.
  usage: $0 <RC_SHA> --execute --deploy --ack-deploy $ACK_DEPLOY
         $0 <RC_SHA> --execute --switch-breadth --ack-switch $ACK_SWITCH   (after (1)+(2))
         $0 <RC_SHA> --execute --rollback-static|--rollback-backend|--rollback-payload
         $0 <RC_SHA> --execute --rollback-breadth <backup_dir>
  v10 recommendation producer stays DISABLED (no flag enables it).
USAGE
  exit 2
fi

# ---- exact-RC-SHA gate ----
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "RC SHA must be exactly 40 lowercase hex chars" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected RC SHA $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"
note "v10 recommendation producer: DISABLED (unchanged; separate result review pending)"

# ---- rollback paths (independent) ----
if [[ $((RB_STATIC+RB_BACKEND+RB_BREADTH+RB_PAYLOAD)) -gt 0 ]]; then
  latest="$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name '2*' 2>/dev/null | sort | tail -1 || true)"
  if [[ "$EXECUTE" != "1" ]]; then
    note "PREPARE-ONLY: would roll back selected planes from ${latest:-<none>} (add --execute)"; exit 3
  fi
  [[ -n "$latest" && -d "$latest" ]] || die "no backup found under $BACKUP_ROOT" 2
  if [[ "$RB_STATIC" == "1" && -d "$latest/dist" ]]; then
    rm -rf "$LIVE_DIST.rb-tmp"; cp -a "$latest/dist" "$LIVE_DIST.rb-tmp"
    rm -rf "$LIVE_DIST"; mv "$LIVE_DIST.rb-tmp" "$LIVE_DIST"; note "static release restored"
  fi
  if [[ "$RB_BACKEND" == "1" && -f "$latest/backend.bundle" ]]; then
    git -C "$REPO_ROOT" fetch "$latest/backend.bundle" 'refs/*:refs/packet-c-rollback/*'
    note "backend bundle fetched into refs/packet-c-rollback/* — operator checks out deliberately"
  fi
  if [[ "$RB_PAYLOAD" == "1" && -f "$latest/sector_momentum_latest.json" ]]; then
    cp -f "$latest/sector_momentum_latest.json" "$SNAPSHOT"; note "payload snapshot restored"
  fi
  if [[ "$RB_BREADTH" == "1" ]]; then
    [[ -n "$RB_BREADTH_DIR" ]] || die "--rollback-breadth needs the inner backup dir" 2
    "$SWITCH_INNER" --rollback "$RB_BREADTH_DIR"; note "breadth producer state rolled back (inner)"
  fi
  note "ROLLBACK complete for requested planes."
  exit 0
fi

# ---- prepare-only ----
if [[ "$EXECUTE" != "1" ]]; then
  cat <<PLAN

PREPARE-ONLY PLAN — nothing was deployed:
  (1) --deploy --ack-deploy $ACK_DEPLOY : build+swap Command Center static (UI) and
      back up api_v2 backend (git bundle). Distinct from the schedule switch.
  (2) validate live payloads: GET $LOOPBACK/api/v2/{defense/posture,sectors/monitor,
      defense/recommendations} == 200 with expected fields. Gates step (3).
  (3) --switch-breadth --ack-switch $ACK_SWITCH : delegate to
      $SWITCH_INNER --apply --expect-sha $EXPECTED_SHA --ack $ACK_SWITCH
      (regenerates + smokes v4 payload; the host schedule repoint stays an operator step).
  (4) v10 recommendation producer stays DISABLED (hard-guarded; no enable path here).
  Independent rollback: --rollback-static | --rollback-backend | --rollback-breadth <dir>
                        | --rollback-payload

This packet NEVER: edits schedules/timers/cron, enables v10, or touches broker/order/approval/2FA.
PLAN
  exit 3
fi

# ---- execute ----
requested=$((DO_DEPLOY+DO_SWITCH))
[[ "$requested" -gt 0 ]] || die "--execute given but neither --deploy nor --switch-breadth requested" 2
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || die "working tree dirty; refuse to deploy" 2
BACKUP_DIR="$BACKUP_ROOT/${STAMP}-${EXPECTED_SHA:0:12}"; mkdir -p "$BACKUP_DIR"

validate_payloads() {
  command -v curl >/dev/null 2>&1 || { note "curl unavailable — cannot validate payloads"; return 1; }
  local fail=0
  for ep in defense/posture sectors/monitor defense/recommendations; do
    local code; code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$LOOPBACK/api/v2/$ep" || echo 000)"
    if [[ "$code" == "200" ]]; then note "  payload $ep -> 200 ok"; else note "  payload $ep -> $code FAIL"; fail=1; fi
  done
  return $fail
}

# ---- (1) UI + api_v2 annotations deploy ----
if [[ "$DO_DEPLOY" == "1" ]]; then
  [[ "$ACK_DP" == "$ACK_DEPLOY" ]] || die "--deploy requires --ack-deploy $ACK_DEPLOY" 2
  step "(1) UI build + api_v2 backend backup + atomic static swap"
  "$PYTHON" -m py_compile "$REPO_ROOT/scripts/api_v2.py" || die "api_v2.py failed syntax check" 5
  git -C "$REPO_ROOT" bundle create "$BACKUP_DIR/backend.bundle" --all
  [[ -d "$LIVE_DIST" ]] && cp -a "$LIVE_DIST" "$BACKUP_DIR/dist"
  [[ -f "$SNAPSHOT" ]] && cp -f "$SNAPSHOT" "$BACKUP_DIR/sector_momentum_latest.json"
  ( cd "$LIVE_APP" && npm run build )
  [[ -d "$LIVE_APP/dist" ]] || die "vite build produced no dist" 5
  cand="$LIVE_DIST.candidate-$STAMP"; cp -a "$LIVE_APP/dist" "$cand"
  rm -rf "$LIVE_DIST.old-$STAMP"; [[ -d "$LIVE_DIST" ]] && mv "$LIVE_DIST" "$LIVE_DIST.old-$STAMP"
  mv "$cand" "$LIVE_DIST"; note "static swapped atomically (prev at $LIVE_DIST.old-$STAMP)"
  step "(2) validate live payloads"
  validate_payloads || note "WARN: payload validation FAILED — do NOT proceed to breadth switch"
fi

# ---- (3) breadth producer switch — ONLY after (1)+(2) ----
if [[ "$DO_SWITCH" == "1" ]]; then
  [[ "$ACK_SW" == "$ACK_SWITCH" ]] || die "--switch-breadth requires --ack-switch $ACK_SWITCH" 2
  [[ -x "$SWITCH_INNER" ]] || die "breadth switch inner script missing: $SWITCH_INNER" 2
  step "(2) re-validate live payloads BEFORE switch (gate)"
  validate_payloads || die "payloads did not validate; refusing breadth switch" 5
  [[ -f "$SNAPSHOT" ]] && cp -f "$SNAPSHOT" "$BACKUP_DIR/sector_momentum_latest.json"
  step "(3) switch breadth producer -> v4 (inner packet; schedules untouched)"
  "$SWITCH_INNER" --apply --expect-sha "$EXPECTED_SHA" --ack "$ACK_SWITCH" \
    || die "breadth switch failed (inner)" 5
  note "breadth switch validated. Host schedule repoint remains an operator step."
fi

note "PACKET C complete for requested steps. v10 remains DISABLED. Backups: $BACKUP_DIR"
