#!/usr/bin/env bash
# 05_close_superuser_login.sh — packet n8n-app-role-20261027, step 05 (OPTIONAL, LATER, after a soak).
#
#   bash 05_close_superuser_login.sh                              # DRY RUN: readiness + the one statement
#   N8N_APP_ROLE_GRANT=<id> bash 05_close_superuser_login.sh --apply [--soak-hours N]
#   bash 05_close_superuser_login.sh --rollback                   # DRY RUN of the rollback
#   N8N_APP_ROLE_GRANT=<id> bash 05_close_superuser_login.sh --rollback --apply
#
# Why not `ALTER ROLE n8n NOSUPERUSER`: n8n is the Postgres image's bootstrap superuser (POSTGRES_USER, OID 10).
# PostgreSQL 16 refuses to demote it — rehearsed on 16.15: "ERROR: permission denied to alter role / DETAIL: The
# bootstrap user must have the SUPERUSER attribute"; REASSIGN OWNED BY it fails too ("required by the database
# system"). Postgres needs one superuser, and the db container's own tools (nightly pg_dump, restore drill, the
# governance reads) use it over the local socket. P13 is about the role n8n CONNECTS AS, which steps 02-04 close.
#
# What this step does instead: `ALTER ROLE n8n PASSWORD NULL`. A role with no password cannot authenticate over the
# network (pg_hba `host all all all scram-sha-256`), so nothing on the lab network — the n8n container included —
# can log in as the superuser, even holding the old password. Local-socket logins inside the db container (trust)
# are unaffected, so backups, the restore drill and `docker exec ... psql -U n8n` keep working (rehearsed: TCP
# "password authentication failed", socket ok). The db container's POSTGRES_PASSWORD is not changed and a recreate
# with the existing volume does not reset the role's password.
# Rollback: set the password back from the db container's own POSTGRES_PASSWORD, read inside the container by
# psql \getenv (never on an argv, the host, stdout or the server log). 09_rollback.sh does this first automatically.
# Gates on --apply: a grant; the latest 04 PASS at least --soak-hours old (default 24) and a fresh re-check now;
# no TCP session as n8n; the network-login probe answers LOGIN_OK first (that proves the container's
# POSTGRES_PASSWORD equals the role's current password, so the rollback restores a working value).
set -euo pipefail
# shellcheck source=docs/ops/packets/n8n-app-role-20261027/_lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
APPLY=0
ROLLBACK=0
SOAK_HOURS=24
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --rollback)
      ROLLBACK=1
      shift
      ;;
    --soak-hours)
      SOAK_HOURS="${2:-}"
      shift 2
      ;;
    *) fail "usage: $0 [--rollback] [--apply] [--soak-hours N]" ;;
  esac
done
[[ "$SOAK_HOURS" =~ ^[0-9]+$ ]] || fail "--soak-hours takes a whole number"
OUT="$EVIDENCE_DIR/$STAMP-close-superuser-login"

pw_null="$(bootstrap_password_is_null)"
probe="$(bootstrap_network_login)"
say "== bootstrap role $BOOTSTRAP_ROLE: password null=$pw_null; network login probe: $probe"

if [[ $ROLLBACK == 1 ]]; then
  if [[ "$pw_null" != t ]]; then
    say "nothing to roll back: $BOOTSTRAP_ROLE has a password"
    exit 0
  fi
  say "ROLLBACK: SET log_statement/log_min_error_statement off for the session; \\getenv pw POSTGRES_PASSWORD;"
  say "          ALTER ROLE $BOOTSTRAP_ROLE PASSWORD :'pw'  (inside $DB_CONTAINER; POSTGRES_PASSWORD=$(container_env_is_set POSTGRES_PASSWORD "$DB_CONTAINER"))"
  if [[ $APPLY == 0 ]]; then
    say "DRY RUN — nothing changed"
    exit 0
  fi
  require_grant "db-write (bootstrap role password restore)"
  restore_bootstrap_password
  after="$(bootstrap_network_login)"
  write_receipt "$OUT/rollback.json" step=05_rollback at="$NOW_ISO" grant="$N8N_APP_ROLE_GRANT" \
    password_null_after="$(bootstrap_password_is_null)" network_login_after="$after"
  [[ "$after" == LOGIN_OK ]] || {
    say "ROLLBACK applied but the probe says $after; check pg_hba and the container env"
    exit 1
  }
  say "ROLLBACK OK — $BOOTSTRAP_ROLE can log in over the network again"
  exit 0
fi

if [[ "$pw_null" == t ]]; then
  say "already applied: $BOOTSTRAP_ROLE has no password (probe: $probe)"
  exit 0
fi
ready=1
nr() {
  say "NOT READY: $*"
  ready=0
}
user="$(container_env_value DB_POSTGRESDB_USER)"
[[ "$user" == "$APP_ROLE" ]] || nr "n8n connects as $user, not $APP_ROLE (steps 02-04 first)"
lv="$(cat "$EVIDENCE_DIR/LATEST_VERIFY_PASS" 2>/dev/null || true)"
if [[ -n "$lv" ]]; then
  age="$(hours_since "$(receipt_value "$EVIDENCE_DIR/$lv/verify.json" at)")"
  say "  latest 04 PASS: $lv (${age} h old; soak needs ${SOAK_HOURS} h)"
  ((age >= SOAK_HOURS)) || nr "soak not complete"
else
  nr "no 04_verify PASS receipt"
fi
sessions="$(q sessions "select usename, coalesce(host(client_addr), 'local'), count(*) from pg_stat_activity where datname = '$DB_NAME' and backend_type = 'client backend' group by 1, 2 order by 1, 2;")"
tcp_boot="$(awk -F'|' -v r="$BOOTSTRAP_ROLE" '$2 != "local" && $1 == r' <<<"$sessions" | paste -sd';')"
[[ -z "$tcp_boot" ]] || nr "TCP session(s) as $BOOTSTRAP_ROLE exist: $tcp_boot (who still uses the superuser over the network?)"
[[ "$probe" == LOGIN_OK ]] || nr "network-login probe is $probe, not LOGIN_OK (the rollback could not be proven)"
[[ "$(container_env_is_set POSTGRES_PASSWORD "$DB_CONTAINER")" == set ]] || nr "POSTGRES_PASSWORD unset in $DB_CONTAINER"
say "  statement: ALTER ROLE $BOOTSTRAP_ROLE PASSWORD NULL;  (local socket, as $BOOTSTRAP_ROLE)"

if [[ $APPLY == 0 ]]; then
  say "DRY RUN — nothing changed; ready for --apply: $([[ $ready == 1 ]] && echo yes || echo no)"
  exit 0
fi
require_grant "db-write (bootstrap role password)"
[[ $ready == 1 ]] || fail "not ready (see NOT READY lines)"
bash "$PACKET_DIR/04_verify.sh" --since "$(date -u -d '-10 min' +%Y-%m-%dT%H:%M:%SZ)" --wait 120 ||
  fail "04_verify.sh does not PASS right now"
printf '%s\n' "-- q:close_superuser_login" "ALTER ROLE $BOOTSTRAP_ROLE PASSWORD NULL;" | sql_rw
after_null="$(bootstrap_password_is_null)"
after_probe="$(bootstrap_network_login)"
socket="$(q socket_check "select 'socket-ok';" || echo socket-FAILED)"
write_receipt "$OUT/close_superuser_login.json" step=05_close_superuser_login at="$NOW_ISO" \
  grant="$N8N_APP_ROLE_GRANT" password_null="$after_null" network_login="$after_probe" local_socket="$socket"
if [[ "$after_null" == t && "$after_probe" == LOGIN_FAILED && "$socket" == socket-ok ]]; then
  say "STEP 05 OK — superuser network login closed; local socket ok. Check tomorrow's nightly backup receipt."
  exit 0
fi
say "STEP 05 UNEXPECTED: null=$after_null probe=$after_probe socket=$socket — consider --rollback --apply"
exit 1
