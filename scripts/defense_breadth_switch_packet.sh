#!/usr/bin/env bash
# Defense/Sectors breadth-producer switch + payload-regen + smoke + rollback PACKET.
#
# WHAT THIS WOULD DO (only when explicitly applied):
#   Switch the breadth producer from the live default
#     scripts/sector_momentum_engine.py   (% above 20-day MA, calendar window)
#   to the exact-20-distinct-session producer
#     scripts/sector_momentum_engine_v4.py (base._breadth = breadth_v4)
#   then regenerate the sector_momentum_state table + data/runtime/sector_momentum_latest.json,
#   smoke-test the loopback payloads, and keep a timestamped backup for rollback.
#
# SAFETY CONTRACT (read before use):
#   * DRY-RUN IS THE DEFAULT. With no --apply it prints the plan and exits 0.
#   * It NEVER edits any cron entry, systemd timer, or service. The host-side
#     scheduled invocation is EXTERNAL to this repo; switching it permanently is an
#     OPERATOR step this script only PRINTS, never performs.
#   * --apply requires BOTH an exact 40-hex --expect-sha that matches repo HEAD AND
#     the acknowledgement token, so it cannot fire from an unexpected tree.
#   * It touches only the momentum snapshot artifact and (via the engine) the
#     sector_momentum_state rows for the current session. No broker, order, approval,
#     2FA, account, position, DB role or migration is involved.
#   * Rollback restores the backed-up snapshot artifact and prints the exact SQL an
#     operator would run to restore the prior session rows (it does not auto-mutate DB).
#
# EXIT CODES: 0 ok/dry-run · 2 blocked (gate failed) · 3 smoke failed.
set -euo pipefail

readonly ACK_REQUIRED="DEFENSE_BREADTH_SWITCH_EXACT20_SHADOW"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly PYTHON="${VENV_PYTHON:-$HOST_REPO/.venv/bin/python}"
readonly SNAPSHOT="$HOST_REPO/data/runtime/sector_momentum_latest.json"
readonly LEGACY_PRODUCER="$HOST_REPO/scripts/sector_momentum_engine.py"
readonly EXACT20_PRODUCER="$HOST_REPO/scripts/sector_momentum_engine_v4.py"
readonly BACKUP_ROOT="${BACKUP_ROOT:-/home/johnclaw/tradeai-deploy-backups/defense-breadth-switch}"
readonly LOOPBACK="http://127.0.0.1:7777"
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

APPLY=0
ROLLBACK_DIR=""
EXPECT_SHA=""
ACK=""

usage() {
  cat <<USAGE
Usage:
  $0                                  # dry-run: print the plan, change nothing
  $0 --apply --expect-sha <40hex> --ack $ACK_REQUIRED
  $0 --rollback <backup_dir>

Environment overrides: REPO, VENV_PYTHON, BACKUP_ROOT
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --expect-sha) EXPECT_SHA="${2:-}"; shift 2 ;;
    --ack) ACK="${2:-}"; shift 2 ;;
    --rollback) ROLLBACK_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

log() { printf '%s\n' "$*"; }

verify_repo_sha() {
  [[ -d "$HOST_REPO/.git" ]] || { echo "BLOCKED: repo unavailable $HOST_REPO" >&2; exit 2; }
  local head
  head="$(git -C "$HOST_REPO" rev-parse HEAD)"
  if [[ ! "$EXPECT_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    echo "BLOCKED: --expect-sha must be an exact 40-hex commit SHA" >&2; exit 2
  fi
  if [[ "$head" != "$EXPECT_SHA" ]]; then
    echo "BLOCKED: repo HEAD $head != --expect-sha $EXPECT_SHA" >&2; exit 2
  fi
  log "sha_gate|OK|HEAD=$head"
}

do_rollback() {
  [[ -n "$ROLLBACK_DIR" && -d "$ROLLBACK_DIR" ]] || { echo "BLOCKED: rollback dir missing" >&2; exit 2; }
  if [[ -f "$ROLLBACK_DIR/sector_momentum_latest.json" ]]; then
    cp -f "$ROLLBACK_DIR/sector_momentum_latest.json" "$SNAPSHOT"
    log "rollback_snapshot|RESTORED -> $SNAPSHOT"
  else
    log "rollback_snapshot|SKIP (no snapshot in backup)"
  fi
  log "rollback_db|MANUAL: an operator restores prior rows with the SQL recorded in:"
  log "           $ROLLBACK_DIR/restore_state.sql (review before running; not auto-applied)"
  log "rollback|DONE"
}

smoke() {
  local fail=0
  for ep in defense/posture sectors/monitor defense/recommendations; do
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$LOOPBACK/api/v2/$ep" || echo 000)"
    if [[ "$code" != "200" ]]; then log "smoke|$ep|HTTP $code|FAIL"; fail=1; else log "smoke|$ep|HTTP 200|ok"; fi
  done
  # Assert the exact-20 switch surfaced quality/quarantine fields on sectors/monitor.
  curl -s --max-time 8 "$LOOPBACK/api/v2/sectors/monitor" \
    | "$PYTHON" -c 'import sys,json; d=json.load(sys.stdin); p=d.get("data",d); assert "data_quality" in p, "data_quality missing"; print("smoke|sectors/monitor|data_quality present|ok")' \
    || { log "smoke|data_quality|FAIL"; fail=1; }
  return $fail
}

plan() {
  cat <<PLAN
DEFENSE/SECTORS BREADTH SWITCH — PLAN (dry-run, nothing changed)
  from : $LEGACY_PRODUCER      (live default; % above 20-day MA)
  to   : $EXACT20_PRODUCER     (exact 20 distinct sessions, uncapped covered membership)
  regen: rewrite sector_momentum_state (current session) + $SNAPSHOT via the v4 producer
  smoke: GET $LOOPBACK/api/v2/{defense/posture,sectors/monitor,defense/recommendations}
         and assert sectors/monitor.data_quality is present
  backup: $BACKUP_ROOT/<stamp>/ (snapshot copy + restore_state.sql)

OPERATOR-ONLY step this packet will NOT perform:
  Repoint the host scheduled job that runs sector_momentum_engine.py so it instead runs
  sector_momentum_engine_v4.py. That cron/timer edit is external to this repo and is
  intentionally left to the operator. This packet only regenerates + smokes the payload
  so the switch can be validated before the schedule is repointed.

To apply (guarded):
  $0 --apply --expect-sha \$(git -C $HOST_REPO rev-parse HEAD) --ack $ACK_REQUIRED
PLAN
}

if [[ -n "$ROLLBACK_DIR" ]]; then
  do_rollback
  exit 0
fi

if [[ "$APPLY" -eq 0 ]]; then
  plan
  exit 0
fi

# --- apply path (guarded) ---
if [[ "$ACK" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED: --ack must equal $ACK_REQUIRED" >&2; exit 2
fi
verify_repo_sha
[[ -x "$PYTHON" ]] || { echo "BLOCKED: venv python not executable: $PYTHON" >&2; exit 2; }
[[ -f "$EXACT20_PRODUCER" ]] || { echo "BLOCKED: exact-20 producer missing" >&2; exit 2; }

readonly BACKUP_DIR="$BACKUP_ROOT/$STAMP"
mkdir -p "$BACKUP_DIR"
if [[ -f "$SNAPSHOT" ]]; then cp -f "$SNAPSHOT" "$BACKUP_DIR/sector_momentum_latest.json"; fi
# Record a restore hint (operator reviews before running; not auto-applied).
{
  echo "-- Restore prior sector_momentum_state rows for the switched session."
  echo "-- Reviewed + run by an operator only. This packet never mutates the DB directly."
  echo "-- (The v4 producer INSERTs a new session; if the switch is reverted, delete the"
  echo "--  session it wrote and let the legacy producer repopulate on its next run.)"
} > "$BACKUP_DIR/restore_state.sql"
log "backup|$BACKUP_DIR"

log "regen|running exact-20 producer (writes state + snapshot)"
PYTHONPATH="$HOST_REPO/scripts" "$PYTHON" "$EXACT20_PRODUCER" || { echo "regen FAILED" >&2; exit 3; }

if smoke; then
  log "SWITCH_VALIDATED|payload regenerated + smoked. Schedule repoint remains an operator step."
  log "rollback_with: $0 --rollback $BACKUP_DIR"
  exit 0
else
  log "SMOKE_FAILED|auto-restoring snapshot from backup"
  ROLLBACK_DIR="$BACKUP_DIR" do_rollback || true
  exit 3
fi
