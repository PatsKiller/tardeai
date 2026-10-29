#!/usr/bin/env bash
# 02_create_app_role.sh — packet n8n-app-role-20261027, step 02: create n8n_app and give it n8n's schema.
#
#   bash 02_create_app_role.sh                         # DRY RUN (default): the role script's read-only PLAN + its SQL
#   N8N_APP_ROLE_GRANT=<id> bash 02_create_app_role.sh --apply [--reuse-password-file] [--ignore-window]
#
# Reuses scripts/ops/n8n_db_app_role.py (packet n8n-platform-hardening-20261022 FW-P2, rehearsed 2026-10-22 against
# the live schema in throwaway containers), it does not re-implement it. In ONE transaction (lock_timeout 15 s) that
# script creates
#   n8n_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 40
# grants CONNECT, TEMPORARY on database n8n and USAGE, CREATE on schema public, and moves ownership of every
# non-extension table, view, free-standing sequence, function and type in public from n8n to n8n_app (n8n runs its
# migrations at start and ALTERs its own tables, which only the owner may do). The password is generated into
# $PASSWORD_FILE (mode 600, dir 700) and never printed; Postgres receives only its SCRAM-SHA-256 verifier.
# Then, in a second transaction, PUBLIC loses CONNECT and TEMPORARY on the other databases (postgres, template1), so
# of the databases that exist n8n_app can connect to n8n only (by default every role may connect to postgres and make
# temp tables there; a database created later gets that default again). Only the superuser n8n, which bypasses these
# checks, and n8n_app exist. 09_rollback.sh --also-role grants them back. The ACLs before are saved as evidence.
# n8n keeps running as n8n until step 03; nothing restarts here. The role n8n is untouched; no role is ever dropped.
# Gates on --apply: a grant id, an ok step-01 backup receipt and a step-00 receipt from the last 6 h, the dump's sha256
# still matching, a quiet minute (ALTER ... OWNER takes a short ACCESS EXCLUSIVE lock per table; a busy table makes the
# transaction time out and roll back, harmlessly).
set -euo pipefail
# shellcheck source=docs/ops/packets/n8n-app-role-20261027/_lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
APPLY=0
IGNORE_WINDOW=0
PASS_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --ignore-window) IGNORE_WINDOW=1 ;;
    --reuse-password-file) PASS_ARGS+=(--reuse-password-file) ;;
    *) fail "usage: $0 [--apply] [--reuse-password-file] [--ignore-window]" ;;
  esac
done
[[ -f "$ROLE_SCRIPT" ]] || fail "role script $ROLE_SCRIPT not found"
ROLE_ARGS=(--password-file "$PASSWORD_FILE" --db-container "$DB_CONTAINER" --n8n-container "$N8N_CONTAINER")
REVOKE_SQL=("BEGIN;" "SET LOCAL lock_timeout = '15s';")
for d in "${OTHER_DBS[@]}"; do REVOKE_SQL+=("REVOKE CONNECT, TEMPORARY ON DATABASE $d FROM PUBLIC;"); done
REVOKE_SQL+=("COMMIT;")
db_acls() {
  q db_acls "select datname || '|' || coalesce(datacl::text, '(default: PUBLIC=Tc)') from pg_database where datname in ('$DB_NAME', 'postgres', 'template1') order by datname;"
}

if [[ $APPLY == 0 ]]; then
  say "DRY RUN — the role script's read-only PLAN (nothing written, nothing executed):"
  "$PY" "$ROLE_SCRIPT" "${ROLE_ARGS[@]}" "${PASS_ARGS[@]}"
  say "On --apply: $PY $ROLE_SCRIPT ${ROLE_ARGS[*]} ${PASS_ARGS[*]} --apply"
  say "Then, as a second transaction (other databases closed to PUBLIC, so n8n_app reaches database n8n only):"
  printf '  %s\n' "${REVOKE_SQL[@]}"
  say "Database ACLs now (datname|datacl):"
  db_acls | sed 's/^/  /'
  exit 0
fi

require_grant "db-write: the role DDL is an operator DB act (AGENTS §17; role script AUTHORITY line)"
pf="$(cat "$EVIDENCE_DIR/LATEST_PREFLIGHT" 2>/dev/null || true)"
bk="$(cat "$EVIDENCE_DIR/LATEST_BACKUP" 2>/dev/null || true)"
[[ -n "$pf" && -f "$EVIDENCE_DIR/$pf/preflight.json" ]] || fail "no step 00 receipt; run 00_preflight.sh first"
[[ "$(receipt_value "$EVIDENCE_DIR/$pf/preflight.json" problems)" == 0 ]] || fail "the latest preflight reported NOT READY items"
(($(hours_since "$(receipt_value "$EVIDENCE_DIR/$pf/preflight.json" at)") < 6)) || fail "the preflight is older than 6 h; re-run 00"
[[ -n "$bk" && -f "$EVIDENCE_DIR/$bk/backup.json" ]] || fail "no step 01 receipt; run 01_backup.sh --apply first"
[[ "$(receipt_value "$EVIDENCE_DIR/$bk/backup.json" ok)" == true ]] || fail "the latest backup receipt is not ok:true; re-run 01 --apply"
(($(hours_since "$(receipt_value "$EVIDENCE_DIR/$bk/backup.json" at)") < 6)) || fail "the backup is older than 6 h; re-run 01 --apply"
bk_dump="$(receipt_value "$EVIDENCE_DIR/$bk/backup.json" dump)"
[[ -f "$bk_dump" && "$(sha256_of "$bk_dump")" == "$(receipt_value "$EVIDENCE_DIR/$bk/backup.json" sha256)" ]] ||
  fail "the step-01 dump $bk_dump is missing or its sha256 does not match the receipt"
if [[ $IGNORE_WINDOW == 1 ]]; then warn "--ignore-window: quiet-minute check skipped"; else
  quiet_minute_now || fail "not a quiet minute (hh:05-hh:09 or hh:35-hh:39), or pass --ignore-window"
fi

OUT="$EVIDENCE_DIR/$STAMP-create-app-role"
mkdir -p "$OUT"
db_acls >"$OUT/db_acls_before.txt"
set +e
"$PY" "$ROLE_SCRIPT" "${ROLE_ARGS[@]}" "${PASS_ARGS[@]}" --apply 2>&1 | tee "$OUT/apply.txt"
rc=${PIPESTATUS[0]}
set -e
revoke_rc=skipped
if [[ $rc -eq 0 ]]; then
  set +e
  printf '%s\n' "-- q:revoke_public_other_dbs" "${REVOKE_SQL[@]}" | sql_rw
  revoke_rc=$?
  set -e
fi
db_acls | tee "$OUT/db_acls_after.txt" | sed 's/^/  acl /'
connect_dbs="$(q app_connect_dbs "select coalesce(string_agg(datname, ',' order by datname), '') from pg_database where datallowconn and exists (select 1 from pg_roles where rolname = '$APP_ROLE') and has_database_privilege('$APP_ROLE', datname, 'CONNECT');")"
say "  $APP_ROLE may connect to: ${connect_dbs:-nothing}"
q role_rows "select rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin from pg_roles where rolname in ('$BOOTSTRAP_ROLE', '$APP_ROLE') order by rolname;" | tee "$OUT/roles.txt" | sed 's/^/  /'
q owners "select pg_get_userbyid(relowner) || ':' || relkind::text, count(*) from pg_class where relnamespace = 'public'::regnamespace group by 1 order by 1;" | tee "$OUT/owners.txt" | sed 's/^/  /'
write_receipt "$OUT/create_app_role.json" step=02_create_app_role at="$NOW_ISO" grant="$N8N_APP_ROLE_GRANT" \
  role_script_rc="$rc" revoke_public_rc="$revoke_rc" app_connect_dbs="$connect_dbs" password_file="$PASSWORD_FILE"
if [[ $rc -ne 0 ]]; then
  say "STEP 02 NOT COMPLETE (role script exit $rc). Postgres rolled the transaction back if it failed mid-way."
  say "Re-run after the cause is fixed; if the password file now exists use --reuse-password-file."
  exit "$rc"
fi
closed=1
[[ ",$connect_dbs," == *",$DB_NAME,"* ]] || closed=0
for d in "${OTHER_DBS[@]}"; do [[ ",$connect_dbs," == *",$d,"* ]] && closed=0; done
if [[ "$revoke_rc" != 0 || $closed == 0 ]]; then
  say "STEP 02 PARTIAL: the role is done but the PUBLIC revoke on ${OTHER_DBS[*]} did not land (rc $revoke_rc;"
  say "  n8n_app may connect to: ${connect_dbs:-?}). Re-run 02 with --reuse-password-file before step 03."
  exit 1
fi
say "STEP 02 OK — n8n still connects as $(container_env_value DB_POSTGRESDB_USER). Next: bash 03_switch_compose.sh"
