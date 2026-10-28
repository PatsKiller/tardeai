#!/usr/bin/env bash
# 09_rollback.sh — packet n8n-app-role-20261027, rollback: n8n connects as n8n again.
#
#   bash 09_rollback.sh                                       # DRY RUN: which backup, the diff, config --quiet
#   N8N_APP_ROLE_GRANT=<ids> bash 09_rollback.sh --apply [--also-role]
#
# --apply:
#   1. if step 05 was applied (the bootstrap role has no password), restore it first from the db container's own
#      POSTGRES_PASSWORD (psql \getenv inside the container; never printed) — n8n's old config logs in with it.
#      That is a DB change (one ALTER ROLE), made only when 05 ran.
#   2. archive the live compose file by rename (docker-compose.n8n.yml.rolledback-<UTC>) and copy back the
#      docker-compose.n8n.yml.bak-<UTC>-pre-n8n-app-role whose <UTC> in the NAME is newest (mtime is not used:
#      `cp -p` keeps the source's time). The backup itself is kept.
#   3. config --quiet, then `docker compose up -d --no-deps n8n` (never `down`, never `-v`), wait for /healthz;
#   4. check DB_POSTGRESDB_USER=n8n, active workflows vs the step-00 snapshot, a relay op:due after the restart.
#   --also-role then undoes step 02 in the database (DB changes): `scripts/ops/n8n_db_app_role.py --rollback --apply`
#   (n8n_app NOLOGIN, REASSIGN OWNED BY n8n_app TO n8n) and GRANT CONNECT, TEMPORARY ON DATABASE postgres, template1
#   TO PUBLIC. Optional: the superuser works whatever the owner is. n8n_app is never dropped; the password file is
#   left in place (archive it by rename if you want, README).
# Without 05 and without --also-role the rollback makes NO database change. It takes no new backup: the step-01 dump
# exists from before the change, and nothing here writes to the database's contents.
# Already rolled back (the live file does not name n8n_app and n8n connects as n8n, with nothing else asked): no-op.
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
BAK="$(newest_by_name "$LAB_DIR" "$COMPOSE_FILE.bak-*-$BACKUP_TAG")"
user_now="$(container_env_value DB_POSTGRESDB_USER)"
pw_null="$(bootstrap_password_is_null)"
live_names_app=0
grep -q 'DB_POSTGRESDB_USER: n8n_app' "$LIVE_COMPOSE" && live_names_app=1
compose_done=0
[[ $live_names_app == 0 && "$user_now" == "$BOOTSTRAP_ROLE" ]] && compose_done=1
config_ok=0
GRANT_SQL=("BEGIN;")
for d in "${OTHER_DBS[@]}"; do GRANT_SQL+=("GRANT CONNECT, TEMPORARY ON DATABASE $d TO PUBLIC;"); done
GRANT_SQL+=("COMMIT;")
say "== rollback plan $NOW_ISO: n8n connects as ${user_now:-?}; live file names n8n_app: $live_names_app; bootstrap password null=$pw_null"

if [[ $compose_done == 1 && "$pw_null" != t && $ALSO_ROLE == 0 ]]; then
  say "already rolled back: the live compose file does not name n8n_app and n8n connects as $BOOTSTRAP_ROLE; nothing to do"
  say "(to also undo step 02 in the database: --also-role)"
  exit 0
fi
if [[ $compose_done == 0 ]]; then
  if [[ -z "$BAK" ]]; then
    [[ $live_names_app == 1 ]] && fail "the live file names n8n_app but no $COMPOSE_FILE.bak-*-$BACKUP_TAG exists in $LAB_DIR; stop and report"
    fail "n8n connects as ${user_now:-?} but the live file does not name n8n_app and no backup exists; stop and report"
  fi
  say "  restore source (newest by the <UTC> in its name): $BAK (sha256 $(sha256_of "$BAK"))"
  grep -q 'DB_POSTGRESDB_USER: n8n$' "$BAK" || warn "the backup does not contain 'DB_POSTGRESDB_USER: n8n'; read the diff"
  diff -u --label "live $COMPOSE_FILE" --label "restore $(basename "$BAK")" -- "$LIVE_COMPOSE" "$BAK" | sed 's/^/  /' || true
  config_ok=1
  compose_config_quiet "$BAK" || config_ok=0
  say "  config --quiet on the backup: $([[ $config_ok == 1 ]] && echo ok || echo FAILED)"
else
  say "  compose part already rolled back; only the database part runs"
fi
quiet_minute_now || warn "not a quiet minute; a rollback goes ahead anyway"
say "  market session: $(market_state)"
plan=()
[[ "$pw_null" == t ]] && plan+=("restore the bootstrap password (DB change)")
[[ $compose_done == 0 ]] && plan+=("archive live -> $LIVE_COMPOSE.rolledback-<UTC>, copy $BAK -> $LIVE_COMPOSE, up -d --no-deps $N8N_SERVICE")
[[ $ALSO_ROLE == 1 ]] && plan+=("role-script rollback + ${GRANT_SQL[*]} (DB changes)")

if [[ $APPLY == 0 ]]; then
  say "DRY RUN — nothing changed. --apply would:"
  printf '  - %s\n' "${plan[@]}"
  exit 0
fi
tiers=()
[[ $compose_done == 0 ]] && tiers+=("config-write (compose) + service (recreate)")
[[ "$pw_null" == t || $ALSO_ROLE == 1 ]] && tiers+=("db-write (role)")
require_grant "${tiers[*]}"
[[ $compose_done == 1 || $config_ok == 1 ]] || fail "the backup fails config --quiet; stop and report"
OUT="$EVIDENCE_DIR/$STAMP-rollback"
mkdir -p "$OUT"
results=()
if [[ "$pw_null" == t ]]; then
  say "== restoring the bootstrap password first (step 05 rollback)"
  restore_bootstrap_password
  [[ "$(bootstrap_network_login)" == LOGIN_OK ]] || fail "bootstrap password restore did not give a network login; n8n left as is"
  results+=("bootstrap_password=restored")
fi
ARCH=""
up_at=""
if [[ $compose_done == 0 ]]; then
  ARCH="$LIVE_COMPOSE.rolledback-$STAMP"
  [[ ! -e "$ARCH" ]] || fail "$ARCH exists"
  mv -- "$LIVE_COMPOSE" "$ARCH"
  cp -p -- "$BAK" "$LIVE_COMPOSE"
  compose_config_quiet "$LIVE_COMPOSE" || fail "restored file fails config --quiet (archived copy at $ARCH)"
  up_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  compose up -d --no-deps "$N8N_SERVICE"
  if wait_healthz "$HEALTHZ_WAIT"; then results+=("healthz=ok"); else results+=("healthz=DOWN"); fi
  snap="$(latest_preflight_snapshot || true)"
  if [[ -n "$snap" ]] && compare_active_workflows "$snap"; then results+=("active_workflows=match"); else results+=("active_workflows=DIFFER"); fi
  if wait_relay_due_after "$up_at" "$RELAY_WAIT"; then results+=("relay_due=ok"); else results+=("relay_due=MISSING"); fi
else
  if healthz_ok; then results+=("healthz=ok"); else results+=("healthz=DOWN"); fi
fi
results+=("connects_as=$(container_env_value DB_POSTGRESDB_USER)")
if [[ $ALSO_ROLE == 1 ]]; then
  if [[ " ${results[*]} " == *" connects_as=$BOOTSTRAP_ROLE "* ]]; then
    set +e
    "$PY" "$ROLE_SCRIPT" --rollback --apply --db-container "$DB_CONTAINER" --n8n-container "$N8N_CONTAINER" | tee "$OUT/role_rollback.txt"
    results+=("role_rollback_rc=${PIPESTATUS[0]}")
    printf '%s\n' "-- q:grant_public_other_dbs" "${GRANT_SQL[@]}" | sql_rw
    results+=("public_connect_restored_rc=$?")
    set -e
  else
    results+=("role_rollback=SKIPPED_n8n_not_on_superuser")
  fi
fi
write_receipt "$OUT/rollback.json" step=09_rollback at="$NOW_ISO" up_at="$up_at" grant="$N8N_APP_ROLE_GRANT" \
  restored_from="${BAK:-}" archived_live="$ARCH" results="${results[*]}"
say "ROLLBACK: ${results[*]}"
[[ " ${results[*]} " == *" healthz=ok "* && " ${results[*]} " == *" connects_as=$BOOTSTRAP_ROLE "* ]] || exit 1
