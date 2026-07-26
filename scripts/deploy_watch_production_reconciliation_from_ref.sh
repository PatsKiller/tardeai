#!/usr/bin/env bash
# Watch production reconciliation — consolidated backend + static UI + packet-rebuild
# deploy/rollback. DRY-RUN BY DEFAULT. Never changes schedules/timers/cron, never
# auto-applies, never touches broker/approval/2FA/orders. An operator must set the
# exact 40-char SHA, the acknowledgement token, and APPLY=1 to mutate anything.
#
#   Preview (safe, default):
#     WATCH_RECON_SOURCE_REF=<40-hex-sha> scripts/deploy_watch_production_reconciliation_from_ref.sh
#   Apply (operator only):
#     WATCH_RECON_SOURCE_REF=<sha> WATCH_RECON_DEPLOY_ACK=WATCH_PRODUCTION_RECONCILIATION_V1 \
#       APPLY=1 scripts/deploy_watch_production_reconciliation_from_ref.sh
#   Rollback the most recent backup this script made:
#     ROLLBACK=1 scripts/deploy_watch_production_reconciliation_from_ref.sh
set -euo pipefail

readonly ACK_REQUIRED="WATCH_PRODUCTION_RECONCILIATION_V1"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_RECON_SOURCE_REF:-}"
readonly APPLY="${APPLY:-0}"
readonly ROLLBACK="${ROLLBACK:-0}"
readonly LIVE_APP="$HOST_REPO/apps/command-center-v3"
readonly LIVE_DIST="$LIVE_APP/dist"
readonly BACKUP_ROOT=/home/johnclaw/tradeai-deploy-backups/watch-production-reconciliation
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly HEALTH_URL="${WATCH_RECON_HEALTH_URL:-http://127.0.0.1:7777/api/v2/watch/decision/summary}"
readonly PYTHON="${PYTHON:-$HOST_REPO/.venv/bin/python}"

# Backend files this reconciliation ships (git-tracked; backup == a git bundle of HEAD).
readonly BACKEND_FILES=(
  scripts/api_v2.py
  scripts/strategy_ticket_reconciler.py
  scripts/strategy_ticket_validator.py
  scripts/strategy_ticket_review.py
  scripts/run_ticket_review_job.py
  scripts/watch_decision_scheduler.py
  scripts/watch_packet_quality.py
  scripts/watch_quality_policy.py
  scripts/watch_quality_projection.py
  scripts/watch_quality_projection_v2.py
  scripts/watch_quality_governed_builder.py
  scripts/watch_quality_local_scheduler.py
  scripts/watch_quality_gate3_sample_rebuild.py
  scripts/watch_quality_gate3_sample_rebuild_v2.py
  scripts/watch_quality_gate4_verify.py
  scripts/watch_quality_gate6_bound_scheduler.py
  scripts/watch_quality_gate6_selection.py
  scripts/watch_quality_audit.py
  scripts/watch_valuation_backfill.py
  config/watch_quality_policy.json
)

log()  { printf '%s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }
blocked() { echo "BLOCKED: $*" >&2; exit 2; }

# ---------------------------------------------------------------- rollback path
if [[ "$ROLLBACK" == "1" ]]; then
  step "ROLLBACK"
  latest="$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name '2*' 2>/dev/null | sort | tail -1 || true)"
  [[ -n "$latest" && -d "$latest" ]] || blocked "no backup found under $BACKUP_ROOT"
  log "restoring from: $latest"
  if [[ "$APPLY" != "1" ]]; then
    log "DRY-RUN: would restore backend git bundle and dist from $latest (set APPLY=1 to execute)"
    exit 0
  fi
  if [[ -f "$latest/backend.bundle" ]]; then
    git -C "$HOST_REPO" fetch "$latest/backend.bundle" 'refs/*:refs/recon-rollback/*'
    log "backend bundle fetched into refs/recon-rollback/* — operator must 'git checkout' the restored tree deliberately"
  fi
  if [[ -d "$latest/dist" ]]; then
    rm -rf "$LIVE_DIST.rollback-tmp"
    cp -a "$latest/dist" "$LIVE_DIST.rollback-tmp"
    rm -rf "$LIVE_DIST" && mv "$LIVE_DIST.rollback-tmp" "$LIVE_DIST"
    log "dist restored atomically"
  fi
  log "ROLLBACK complete. Service reload is a SEPARATE operator action; this script never restarts services."
  exit 0
fi

# ---------------------------------------------------------------- exact-SHA gate
step "EXACT-SHA GATE"
[[ -n "$SOURCE_REF" && "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]] || blocked "WATCH_RECON_SOURCE_REF must be an exact 40-char commit SHA"
[[ -d "$HOST_REPO/.git" ]] || blocked "repository unavailable: $HOST_REPO"
git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}" || blocked "SOURCE_REF is not a commit in $HOST_REPO"
readonly RESOLVED="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
[[ "$RESOLVED" == "$SOURCE_REF" ]] || blocked "resolved commit ($RESOLVED) differs from exact SOURCE_REF"
log "exact source commit verified: $RESOLVED"

# --------------------------------------------------------------- staged content
step "EXACT-REF STAGE (read-only export, never the dirty live checkout)"
readonly STAGE_ROOT="$(mktemp -d /tmp/watch-recon-stage.XXXXXX)"
trap 'rm -rf "$STAGE_ROOT"' EXIT
git -C "$HOST_REPO" archive "$RESOLVED" "${BACKEND_FILES[@]}" | tar -x -C "$STAGE_ROOT"
log "staged $(find "$STAGE_ROOT" -type f | wc -l | tr -d ' ') backend files from $RESOLVED"

# ------------------------------------------------------------------ static build
step "STATIC UI BUILD (candidate — not yet swapped)"
readonly CANDIDATE="$LIVE_DIST.candidate-$STAMP"
if [[ "$APPLY" == "1" ]]; then
  ( cd "$LIVE_APP" && npm run build )   # runs design-token + chip-scope guards + tsc + vite
  [[ -d "$LIVE_APP/dist" ]] || blocked "vite build produced no dist"
  cp -a "$LIVE_APP/dist" "$CANDIDATE"
  log "candidate built at $CANDIDATE"
else
  log "DRY-RUN: would run 'npm run build' (design-token + chip-scope + tsc + vite) and stage a candidate dist"
fi

# ----------------------------------------------------------------- apply gate
step "APPLY GATE"
if [[ "$APPLY" != "1" ]]; then
  log "DRY-RUN COMPLETE — no files changed. To apply: set APPLY=1 and WATCH_RECON_DEPLOY_ACK=$ACK_REQUIRED"
  log "This script NEVER: changes schedules/timers/cron, restarts services, runs DB migrations,"
  log "creates DB roles, touches broker/approval/2FA/orders, or auto-promotes anything."
  exit 0
fi
[[ "${WATCH_RECON_DEPLOY_ACK:-}" == "$ACK_REQUIRED" ]] || blocked "APPLY=1 requires WATCH_RECON_DEPLOY_ACK=$ACK_REQUIRED"

# ------------------------------------------------------------------- backup
step "BACKUP"
readonly BACKUP_DIR="$BACKUP_ROOT/${STAMP}-${RESOLVED:0:12}"
mkdir -p "$BACKUP_DIR"
git -C "$HOST_REPO" bundle create "$BACKUP_DIR/backend.bundle" --all
[[ -d "$LIVE_DIST" ]] && cp -a "$LIVE_DIST" "$BACKUP_DIR/dist"
log "backup written: $BACKUP_DIR"

# ----------------------------------------------------- install backend + static
step "INSTALL BACKEND (from exact-ref stage)"
for rel in "${BACKEND_FILES[@]}"; do
  [[ -f "$STAGE_ROOT/$rel" ]] || blocked "staged file missing: $rel"
  install -D -m 0644 "$STAGE_ROOT/$rel" "$HOST_REPO/$rel"
done
log "backend files installed from $RESOLVED"

step "ATOMIC STATIC SWAP"
rm -rf "$LIVE_DIST.old-$STAMP"
[[ -d "$LIVE_DIST" ]] && mv "$LIVE_DIST" "$LIVE_DIST.old-$STAMP"
mv "$CANDIDATE" "$LIVE_DIST"
log "static dist swapped atomically (previous kept at $LIVE_DIST.old-$STAMP)"

# ------------------------------------------------------------- packet rebuild
step "PACKET REBUILD (same governance contract; writes packets, NOT schedules)"
# Uses the exact-ref governed builder / gate3 sample rebuild. This is a data
# (decision_packets) rebuild only; it does not alter any timer or cron.
"$PYTHON" "$HOST_REPO/scripts/watch_quality_gate3_sample_rebuild_v2.py" || \
  log "packet rebuild returned non-zero — inspect before relying on new packets"

# --------------------------------------------------------------- health smoke
step "HEALTH SMOKE (loopback, read-only)"
if command -v curl >/dev/null 2>&1; then
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_URL" || echo 000)"
  log "GET $HEALTH_URL -> HTTP $code"
  [[ "$code" == "200" ]] || log "WARN: health smoke non-200 — consider ROLLBACK=1 APPLY=1"
else
  log "curl unavailable — skip smoke"
fi

log ""
log "APPLY COMPLETE for $RESOLVED. Service reload/restart is a SEPARATE operator action."
log "Rollback: ROLLBACK=1 APPLY=1 scripts/deploy_watch_production_reconciliation_from_ref.sh"
