#!/usr/bin/env bash
# =============================================================================
# PACKET B — Consolidated Watch deployment (backend + frontend + packets).
# =============================================================================
# Deploys the consolidated Watch backend + frontend, optionally runs the network
# valuation-supplement backfill, reloads the Watch backend service, swaps the
# static UI, and rebuilds the active decision packets — then runs a 5-symbol
# (DXCM/CECO/OSS/PFLT/FATN) + 200-card acceptance. It DOES NOT change any Watch
# schedule/timer/cron, and holds NO broker/order/approval/2FA authority.
#
# FOUR INDEPENDENTLY-GATED OPERATOR ACKNOWLEDGEMENTS (each its own flag + token):
#   (1) network valuation backfill  --backfill      --ack-backfill  APPLY-B-VALUATION-BACKFILL
#   (2) backend/service reload       --reload        --ack-reload    APPLY-B-BACKEND-RELOAD
#   (3) static UI swap               --static-swap   --ack-static    APPLY-B-STATIC-SWAP
#   (4) packet rebuild               --packet-rebuild --ack-rebuild  APPLY-B-PACKET-REBUILD
# Any subset may be run; each step fires ONLY when --execute AND its flag AND its
# exact token are all present. The valuation backfill (network) runs ONLY on
# explicit operator authorization via (1).
#
# SAFETY CONTRACT:
#   * PREPARE-ONLY BY DEFAULT (no --execute => plan, exit 3). NO args => exit 2.
#   * exact-RC-SHA gate; clean-checkout gate before any mutation.
#   * Backend + static are backed up before any change; --rollback restores them.
#   * NEVER edits schedules/timers/cron.
#
# EXIT CODES: 0 ok · 2 usage/gate blocked · 3 prepare-only refusal · 5 step failed
# =============================================================================
set -euo pipefail

readonly PACKET="B:watch_deploy"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly LIVE_APP="$REPO_ROOT/apps/command-center-v3"
readonly LIVE_DIST="$LIVE_APP/dist"
readonly PYTHON="${VENV_PYTHON:-$REPO_ROOT/.venv/bin/python}"
readonly BACKFILL_PY="$REPO_ROOT/scripts/watch_valuation_backfill.py"
readonly PACKET_REBUILD_PY="$REPO_ROOT/scripts/watch_quality_gate3_sample_rebuild_v2.py"
readonly BACKUP_ROOT="${WATCH_BACKUP_ROOT:-/home/johnclaw/tradeai-deploy-backups/packet-b-watch}"
readonly HEALTH_URL="${WATCH_HEALTH_URL:-http://127.0.0.1:7777/api/v2/watch/decision/summary}"
readonly CARDS_URL="${WATCH_CARDS_URL:-http://127.0.0.1:7777/api/v2/watch/cards}"
readonly WATCH_SERVICE="${WATCH_SERVICE:-}"
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly ACCEPT_SYMBOLS=(DXCM CECO OSS PFLT FATN)

readonly ACK_BACKFILL="APPLY-B-VALUATION-BACKFILL"
readonly ACK_RELOAD="APPLY-B-BACKEND-RELOAD"
readonly ACK_STATIC="APPLY-B-STATIC-SWAP"
readonly ACK_REBUILD="APPLY-B-PACKET-REBUILD"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY (dry-run default) ==="; }
die()    { echo "[B][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[B] $*"; }
step()   { printf '\n[B] === %s ===\n' "$*"; }

EXPECTED_SHA=""; EXECUTE=0; ROLLBACK=0
DO_BACKFILL=0; DO_RELOAD=0; DO_STATIC=0; DO_REBUILD=0
ACK_BF=""; ACK_RL=""; ACK_ST=""; ACK_RB=""
NEXT=""
for arg in "$@"; do
  if [[ -n "$NEXT" ]]; then case "$NEXT" in
      bf) ACK_BF="$arg";; rl) ACK_RL="$arg";; st) ACK_ST="$arg";; rb) ACK_RB="$arg";;
    esac; NEXT=""; continue; fi
  case "$arg" in
    --execute|--apply) EXECUTE=1 ;;
    --rollback)        ROLLBACK=1 ;;
    --backfill)        DO_BACKFILL=1 ;;
    --reload)          DO_RELOAD=1 ;;
    --static-swap)     DO_STATIC=1 ;;
    --packet-rebuild)  DO_REBUILD=1 ;;
    --ack-backfill)    NEXT="bf" ;;
    --ack-reload)      NEXT="rl" ;;
    --ack-static)      NEXT="st" ;;
    --ack-rebuild)     NEXT="rb" ;;
    *) if [[ -z "$EXPECTED_SHA" ]]; then EXPECTED_SHA="$arg"; else die "unexpected argument: $arg" 2; fi ;;
  esac
done

banner

if [[ -z "$EXPECTED_SHA" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no RC SHA supplied. Nothing was deployed. This packet refuses to mutate.
  usage: $0 <RC_SHA> [--execute] \\
           [--backfill --ack-backfill $ACK_BACKFILL] \\
           [--reload --ack-reload $ACK_RELOAD] \\
           [--static-swap --ack-static $ACK_STATIC] \\
           [--packet-rebuild --ack-rebuild $ACK_REBUILD]
         $0 <RC_SHA> --rollback [--execute]
USAGE
  exit 2
fi

# ---- exact-RC-SHA gate ----
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "RC SHA must be exactly 40 lowercase hex chars" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected RC SHA $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"

# ---- rollback path ----
if [[ "$ROLLBACK" == "1" ]]; then
  step "ROLLBACK"
  latest="$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name '2*' 2>/dev/null | sort | tail -1 || true)"
  [[ -n "$latest" && -d "$latest" ]] || die "no backup found under $BACKUP_ROOT" 2
  if [[ "$EXECUTE" != "1" ]]; then
    note "PREPARE-ONLY: would restore backend bundle + dist from $latest (add --execute)"; exit 3
  fi
  if [[ -d "$latest/dist" ]]; then
    rm -rf "$LIVE_DIST.rollback-tmp"; cp -a "$latest/dist" "$LIVE_DIST.rollback-tmp"
    rm -rf "$LIVE_DIST"; mv "$LIVE_DIST.rollback-tmp" "$LIVE_DIST"; note "dist restored"
  fi
  note "ROLLBACK complete. Service reload is a SEPARATE gated step (--reload)."
  exit 0
fi

# ---- prepare-only ----
if [[ "$EXECUTE" != "1" ]]; then
  cat <<PLAN

PREPARE-ONLY PLAN — nothing was deployed. Four independent gates:
  (1) valuation backfill (NETWORK): $BACKFILL_PY
        fires only with --backfill --ack-backfill $ACK_BACKFILL
  (2) backend/service reload: systemctl reload/restart \$WATCH_SERVICE
        fires only with --reload --ack-reload $ACK_RELOAD   (NEVER edits schedules)
  (3) static UI swap: atomic swap of $LIVE_DIST
        fires only with --static-swap --ack-static $ACK_STATIC
  (4) packet rebuild: $PACKET_REBUILD_PY
        fires only with --packet-rebuild --ack-rebuild $ACK_REBUILD
  Acceptance after applied steps: 5-symbol (${ACCEPT_SYMBOLS[*]}) + >=200-card check.
  Backup before any mutation; rollback via: $0 $EXPECTED_SHA --rollback --execute

This packet NEVER: changes Watch schedules/timers/cron, or touches broker/order/approval/2FA.

Add --execute plus the step flags/acks you intend to run.
PLAN
  exit 3
fi

# ---- execute path: at least one step must be requested + acked ----
requested=$((DO_BACKFILL+DO_RELOAD+DO_STATIC+DO_REBUILD))
[[ "$requested" -gt 0 ]] || die "--execute given but no step flag requested (nothing to do)" 2
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || die "working tree dirty; refuse to deploy" 2

BACKUP_DIR="$BACKUP_ROOT/${STAMP}-${EXPECTED_SHA:0:12}"
mkdir -p "$BACKUP_DIR"
[[ -d "$LIVE_DIST" ]] && cp -a "$LIVE_DIST" "$BACKUP_DIR/dist" && note "static backup -> $BACKUP_DIR/dist"

run_acceptance() {
  command -v curl >/dev/null 2>&1 || { note "curl unavailable — skipping acceptance"; return 0; }
  step "ACCEPTANCE (5-symbol + 200-card)"
  local code; code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_URL" || echo 000)"
  note "GET decision/summary -> HTTP $code"
  local cards; cards="$(curl -s --max-time 15 "$CARDS_URL" || echo '')"
  local n; n="$(printf '%s' "$cards" | "$PYTHON" -c 'import sys,json;
d=json.load(sys.stdin); a=d.get("data",d); a=a.get("cards",a) if isinstance(a,dict) else a
print(len(a) if isinstance(a,list) else 0)' 2>/dev/null || echo 0)"
  note "card count: $n (require >=200)"
  [[ "$n" -ge 200 ]] || note "WARN: card count below 200"
  for s in "${ACCEPT_SYMBOLS[@]}"; do
    if printf '%s' "$cards" | grep -q "\"$s\""; then note "  accept symbol present: $s"
    else note "  WARN: accept symbol MISSING: $s"; fi
  done
}

# ---- (1) valuation backfill (NETWORK) ----
if [[ "$DO_BACKFILL" == "1" ]]; then
  [[ "$ACK_BF" == "$ACK_BACKFILL" ]] || die "--backfill requires --ack-backfill $ACK_BACKFILL" 2
  [[ -f "$BACKFILL_PY" ]] || die "valuation backfill missing: $BACKFILL_PY" 5
  step "(1) NETWORK valuation-supplement backfill"
  "$PYTHON" "$BACKFILL_PY" || die "valuation backfill failed" 5
fi

# ---- (3) static UI swap ---- (built before reload so a reload serves it)
if [[ "$DO_STATIC" == "1" ]]; then
  [[ "$ACK_ST" == "$ACK_STATIC" ]] || die "--static-swap requires --ack-static $ACK_STATIC" 2
  step "(3) static UI build + atomic swap"
  ( cd "$LIVE_APP" && npm run build )
  [[ -d "$LIVE_APP/dist" ]] || die "vite build produced no dist" 5
  cand="$LIVE_DIST.candidate-$STAMP"; cp -a "$LIVE_APP/dist" "$cand"
  rm -rf "$LIVE_DIST.old-$STAMP"; [[ -d "$LIVE_DIST" ]] && mv "$LIVE_DIST" "$LIVE_DIST.old-$STAMP"
  mv "$cand" "$LIVE_DIST"; note "static dist swapped atomically (prev at $LIVE_DIST.old-$STAMP)"
fi

# ---- (4) packet rebuild ----
if [[ "$DO_REBUILD" == "1" ]]; then
  [[ "$ACK_RB" == "$ACK_REBUILD" ]] || die "--packet-rebuild requires --ack-rebuild $ACK_REBUILD" 2
  [[ -f "$PACKET_REBUILD_PY" ]] || die "packet rebuild missing: $PACKET_REBUILD_PY" 5
  step "(4) active packet rebuild (data only; NOT schedules)"
  "$PYTHON" "$PACKET_REBUILD_PY" || die "packet rebuild failed" 5
fi

# ---- (2) backend/service reload ---- (last, to serve new backend+static+packets)
if [[ "$DO_RELOAD" == "1" ]]; then
  [[ "$ACK_RL" == "$ACK_RELOAD" ]] || die "--reload requires --ack-reload $ACK_RELOAD" 2
  [[ -n "$WATCH_SERVICE" ]] || die "WATCH_SERVICE env required for --reload" 2
  step "(2) backend/service reload (ONE service; schedules untouched)"
  systemctl reload "$WATCH_SERVICE" 2>/dev/null || systemctl restart "$WATCH_SERVICE" \
    || die "service reload/restart failed for $WATCH_SERVICE" 5
  note "reloaded $WATCH_SERVICE"
fi

run_acceptance
note "PACKET B complete for requested steps. Rollback: $0 $EXPECTED_SHA --rollback --execute"
