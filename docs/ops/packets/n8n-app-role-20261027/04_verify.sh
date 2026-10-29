#!/usr/bin/env bash
# 04_verify.sh — packet n8n-app-role-20261027, step 04. READ-ONLY. The receipt for AGENTS.md §23.10 P13.
#
#   bash 04_verify.sh [--since <ISO-8601>] [--wait <seconds>]
#
# PASS needs every one of:
#   1. GET /healthz → {"status":"ok"}
#   2. the n8n container's DB_POSTGRESDB_USER is n8n_app, DB_POSTGRESDB_PASSWORD is unset, the _FILE form is set
#   3. pg_roles for the role n8n CONNECTS AS (read from the container, not assumed): rolsuper=f and no
#      createrole / createdb / replication / bypassrls; and that role may CONNECT to database n8n and not to
#      postgres or template1 (a database created later, e.g. the restore drill's, is reported, not failed)
#   4. every TCP session to database n8n is n8n_app (none as the superuser n8n)
#   5. scripts/ops/n8n_db_app_role.py --verify → PASS (ownership of every public object, privileges, login)
#   6. the active workflow ids equal the step-00 snapshot
#   7. a relay `op: due` line newer than --since (default: step 03's up_at) appears within --wait (default 300 s)
# Writes only $EVIDENCE_DIR/<UTC>-verify/verify.json. Exit 0 PASS / 1 FAIL / 2 cannot run.
set -euo pipefail
# shellcheck source=docs/ops/packets/n8n-app-role-20261027/_lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
SINCE=""
WAIT="$RELAY_WAIT"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --since)
      SINCE="${2:-}"
      shift 2
      ;;
    --wait)
      WAIT="${2:-}"
      shift 2
      ;;
    *) fail "usage: $0 [--since <ISO-8601>] [--wait <seconds>]" ;;
  esac
done
[[ "$WAIT" =~ ^[0-9]+$ ]] || fail "--wait takes seconds"
if [[ -z "$SINCE" ]]; then
  sw="$(cat "$EVIDENCE_DIR/LATEST_SWITCH" 2>/dev/null || true)"
  [[ -n "$sw" ]] && SINCE="$(receipt_value "$EVIDENCE_DIR/$sw/switch_compose.json" up_at)"
  [[ -n "$SINCE" ]] || SINCE="$NOW_ISO"
fi
OUT="$EVIDENCE_DIR/$STAMP-verify"
mkdir -p "$OUT"
failures=()
check() { # check NAME OK? DETAIL
  if [[ "$2" == 1 ]]; then say "  PASS $1: $3"; else
    say "  FAIL $1: $3"
    failures+=("$1")
  fi
}
say "== n8n-app-role verify $NOW_ISO (relay since $SINCE)"

ok=0
healthz_ok && ok=1
check healthz "$ok" "$HEALTHZ_URL"

user="$(container_env_value DB_POSTGRESDB_USER)"
pw="$(container_env_is_set DB_POSTGRESDB_PASSWORD)"
pwf="$(container_env_is_set DB_POSTGRESDB_PASSWORD_FILE)"
ok=0
[[ "$user" == "$APP_ROLE" && "$pw" == unset && "$pwf" == set ]] && ok=1
check container_env "$ok" "DB_POSTGRESDB_USER=$user DB_POSTGRESDB_PASSWORD=$pw DB_POSTGRESDB_PASSWORD_FILE=$pwf"

row=""
if valid_role_name "$user"; then
  row="$(q connect_role "select rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls from pg_roles where rolname = '$user';")"
fi
ok=0
[[ "$row" == "f|f|f|f|f" ]] && ok=1
check rolsuper "$ok" "role $user (super|createrole|createdb|replication|bypassrls) = ${row:-absent}"

connect_dbs=""
if valid_role_name "$user"; then
  connect_dbs="$(q app_connect_dbs "select coalesce(string_agg(datname, ',' order by datname), '') from pg_database where datallowconn and exists (select 1 from pg_roles where rolname = '$user') and has_database_privilege('$user', datname, 'CONNECT');")"
fi
ok=1
[[ ",$connect_dbs," == *",$DB_NAME,"* ]] || ok=0
for d in "${OTHER_DBS[@]}"; do [[ ",$connect_dbs," == *",$d,"* ]] && ok=0; done
check databases "$ok" "role $user may connect to: ${connect_dbs:-nothing} (want $DB_NAME, and none of ${OTHER_DBS[*]})"
# A database created later gets PostgreSQL's default ACL (PUBLIC may connect), e.g. the weekly restore drill's
# n8n_drill_<UTC> for the minutes it exists. Reported, not failed: n8n_app owns nothing there and has no table grant.
extra="$(tr ',' '\n' <<<"$connect_dbs" | grep -vx -e "$DB_NAME" -e postgres -e template1 | paste -sd',' || true)"
[[ -z "$extra" ]] || say "  note: $user may also connect to $extra (created after step 02; default PUBLIC CONNECT)"

sessions="$(q sessions "select usename, coalesce(host(client_addr), 'local'), count(*) from pg_stat_activity where datname = '$DB_NAME' and backend_type = 'client backend' group by 1, 2 order by 1, 2;")"
printf '%s\n' "$sessions" >"$OUT/sessions.txt"
tcp_other="$(awk -F'|' -v r="$APP_ROLE" '$2 != "local" && $1 != r' <<<"$sessions" | paste -sd';')"
tcp_app="$(awk -F'|' -v r="$APP_ROLE" '$2 != "local" && $1 == r {n += $3} END {print n + 0}' <<<"$sessions")"
ok=0
[[ -z "$tcp_other" && "$tcp_app" -gt 0 ]] && ok=1
check sessions "$ok" "TCP sessions as $APP_ROLE: $tcp_app; other TCP sessions: ${tcp_other:-none}"

set +e
role_verify="$("$PY" "$ROLE_SCRIPT" --verify --password-file "$PASSWORD_FILE" --db-container "$DB_CONTAINER" --n8n-container "$N8N_CONTAINER" 2>&1)"
rv=$?
set -e
printf '%s\n' "$role_verify" >"$OUT/role_script_verify.txt"
ok=0
[[ $rv -eq 0 ]] && ok=1
check role_script "$ok" "$(head -n 1 <<<"$role_verify")"

snap="$(latest_preflight_snapshot || true)"
ok=0
if [[ -n "$snap" ]] && compare_active_workflows "$snap"; then ok=1; fi
check active_workflows "$ok" "snapshot ${snap:-missing}"

ok=0
wait_relay_due_after "$SINCE" "$WAIT" && ok=1
check relay_due "$ok" "op:due after $SINCE within ${WAIT}s ($RELAY_LOG)"

verdict=PASS
((${#failures[@]} == 0)) || verdict=FAIL
write_receipt "$OUT/verify.json" step=04_verify at="$NOW_ISO" verdict="$verdict" connects_as="$user" \
  role_attrs="$row" failures="${failures[*]:-}" relay_since="$SINCE"
if [[ $verdict == PASS ]]; then
  printf '%s\n' "$STAMP-verify" >"$EVIDENCE_DIR/LATEST_VERIFY_PASS"
  say "VERIFY PASS — P13 receipt: $OUT/verify.json. Quote it in the closing PR; step 05 is optional, after a soak."
  exit 0
fi
say "VERIFY FAIL: ${failures[*]} — decide: fix forward, or N8N_APP_ROLE_GRANT=... bash 09_rollback.sh --apply"
exit 1
