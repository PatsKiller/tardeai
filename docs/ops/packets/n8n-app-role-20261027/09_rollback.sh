#!/usr/bin/env bash
# 09_rollback.sh — packet n8n-app-role-20261027, rollback: n8n connects as n8n again.
#
#   bash 09_rollback.sh                                       # DRY RUN: which backup, the diff, config --quiet
#   N8N_APP_ROLE_GRANT=<ids> bash 09_rollback.sh --apply [--also-role]
#
# --apply:
#   1. if step 05 was applied (the bootstrap role has no password), restore it first from the db container's own
#      POSTGRES_PASSWORD (psql \getenv inside the container; never printed) — n8n's old config logs in with it;
#   2. archive the live compose file by rename (docker-compose.n8n.yml.rolledback-<UTC>) and copy the newest
#      docker-compose.n8n.yml.bak-*-pre-n8n-app-role back in its place (the backup itself is kept);
#   3. config --quiet, then `docker compose up -d --no-deps n8n` (never `down`, never `-v`), wait for /healthz;
#   4. check DB_POSTGRESDB_USER=n8n, active workflows vs the step-00 snapshot, a relay op:due after the restart.
#   --also-role then runs `scripts/ops/n8n_db_app_role.py --rollback --apply`: n8n_app NOLOGIN and ownership back to
#   n8n (REASSIGN OWNED BY n8n_app TO n8n). Optional: the superuser works whatever the owner is. n8n_app is never
#   dropped and the password file is left in place (archive it by rename if you want, README).
# Not gated by the quiet minute or market session (a rollback is urgent); it warns instead.
# Restoring the step-01 dump is NOT scripted: it is a last resort, into a NEW database, by hand (README).
set -euo pipefail
# shellcheck source=docs/ops/packets/n8n-app-role-20261027/_lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
APPLY=0
ALSO_ROLE=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --also-role) ALSO_ROLE=1 ;;
    *) fail "usage: $0 [--apply] [--also-role]" ;;
  esac
done
[[ -f "$LIVE_COMPOSE" ]] || fail "compose file $LIVE_COMPOSE not found"
BAK="$(newest "$LAB_DIR" "$COMPOSE_FILE.bak-*-$BACKUP_TAG")"
user_now="$(container_env_value DB_POSTGRESDB_USER)"
pw_null="$(bootstrap_password_is_null)"
say "== rollback plan $NOW_ISO: n8n connects as ${user_now:-?}; bootstrap password null=$pw_null"
if [[ -z "$BAK" ]]; then
  if grep -q 'DB_POSTGRESDB_USER: n8n_app' "$LIVE_COMPOSE"; then
    fail "the live file names n8n_app but no $COMPOSE_FILE.bak-*-$BACKUP_TAG exists in $LAB_DIR; stop and report"
  fi
  say "nothing to roll back: no $BACKUP_TAG compose backup and the live file does not name n8n_app"
  exit 0
fi
say "  restore source: $BAK (sha256 $(sha256_of "$BAK"))"
grep -q 'DB_POSTGRESDB_USER: n8n$' "$BAK" || warn "the backup does not contain 'DB_POSTGRESDB_USER: n8n'; read the diff"
diff -u --label "live $COMPOSE_FILE" --label "restore $(basename "$BAK")" -- "$LIVE_COMPOSE" "$BAK" | sed 's/^/  /' || true
config_ok=1
compose_config_quiet "$BAK" || config_ok=0
say "  config --quiet on the backup: $([[ $config_ok == 1 ]] && echo ok || echo FAILED)"
quiet_minute_now || warn "not a quiet minute; a rollback goes ahead anyway"
say "  market session: $(market_state)"

if [[ $APPLY == 0 ]]; then
  say "DRY RUN — nothing changed. --apply: $([[ "$pw_null" == t ]] && echo 'restore the bootstrap password, then ')archive live -> $LIVE_COMPOSE.rolledback-<UTC>, copy $BAK -> $LIVE_COMPOSE, up -d --no-deps $N8N_SERVICE$([[ $ALSO_ROLE == 1 ]] && echo ', then the role-script rollback')"
  exit 0
fi
require_grant "config-write (compose) + service (recreate)$([[ "$pw_null" == t || $ALSO_ROLE == 1 ]] && echo ' + db-write (role)')"
[[ $config_ok == 1 ]] || fail "the backup fails config --quiet; stop and report"
OUT="$EVIDENCE_DIR/$STAMP-rollback"
mkdir -p "$OUT"
if [[ "$pw_null" == t ]]; then
  say "== restoring the bootstrap password first (step 05 rollback)"
  restore_bootstrap_password
  [[ "$(bootstrap_network_login)" == LOGIN_OK ]] || fail "bootstrap password restore did not give a network login; n8n left as is"
fi
ARCH="$LIVE_COMPOSE.rolledback-$STAMP"
[[ ! -e "$ARCH" ]] || fail "$ARCH exists"
mv -- "$LIVE_COMPOSE" "$ARCH"
cp -p -- "$BAK" "$LIVE_COMPOSE"
compose_config_quiet "$LIVE_COMPOSE" || fail "restored file fails config --quiet (archived copy at $ARCH)"
up_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
compose up -d --no-deps "$N8N_SERVICE"
results=()
if wait_healthz 180; then results+=("healthz=ok"); else results+=("healthz=DOWN"); fi
results+=("connects_as=$(container_env_value DB_POSTGRESDB_USER)")
snap="$(latest_preflight_snapshot || true)"
if [[ -n "$snap" ]] && compare_active_workflows "$snap"; then results+=("active_workflows=match"); else results+=("active_workflows=DIFFER"); fi
if wait_relay_due_after "$up_at" 300; then results+=("relay_due=ok"); else results+=("relay_due=MISSING"); fi
if [[ $ALSO_ROLE == 1 ]]; then
  set +e
  "$PY" "$ROLE_SCRIPT" --rollback --apply --db-container "$DB_CONTAINER" --n8n-container "$N8N_CONTAINER" | tee "$OUT/role_rollback.txt"
  results+=("role_rollback_rc=${PIPESTATUS[0]}")
  set -e
fi
write_receipt "$OUT/rollback.json" step=09_rollback at="$NOW_ISO" up_at="$up_at" grant="$N8N_APP_ROLE_GRANT" \
  restored_from="$BAK" archived_live="$ARCH" results="${results[*]}"
say "ROLLBACK: ${results[*]}"
[[ " ${results[*]} " == *" healthz=ok "* && " ${results[*]} " == *" connects_as=$BOOTSTRAP_ROLE "* ]] || exit 1
