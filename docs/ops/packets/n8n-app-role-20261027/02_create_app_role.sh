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
# n8n keeps running as n8n until step 03; nothing restarts here. The role n8n is untouched; no role is ever dropped.
# Gates on --apply: a grant id, step 00 and step 01 receipts from the last 6 h, a quiet minute (ALTER ... OWNER takes
# a short ACCESS EXCLUSIVE lock per table; a busy table makes the transaction time out and roll back, harmlessly).
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

if [[ $APPLY == 0 ]]; then
  say "DRY RUN — the role script's read-only PLAN (nothing written, nothing executed):"
  "$PY" "$ROLE_SCRIPT" "${ROLE_ARGS[@]}" "${PASS_ARGS[@]}"
  say "On --apply: $PY $ROLE_SCRIPT ${ROLE_ARGS[*]} ${PASS_ARGS[*]} --apply"
  exit 0
fi

require_grant "db-write: the role DDL is an operator DB act (AGENTS §17; role script AUTHORITY line)"
pf="$(cat "$EVIDENCE_DIR/LATEST_PREFLIGHT" 2>/dev/null || true)"
bk="$(cat "$EVIDENCE_DIR/LATEST_BACKUP" 2>/dev/null || true)"
[[ -n "$pf" && -f "$EVIDENCE_DIR/$pf/preflight.json" ]] || fail "no step 00 receipt; run 00_preflight.sh first"
[[ "$(receipt_value "$EVIDENCE_DIR/$pf/preflight.json" problems)" == 0 ]] || fail "the latest preflight reported NOT READY items"
(($(hours_since "$(receipt_value "$EVIDENCE_DIR/$pf/preflight.json" at)") < 6)) || fail "the preflight is older than 6 h; re-run 00"
[[ -n "$bk" && -f "$EVIDENCE_DIR/$bk/backup.json" ]] || fail "no step 01 receipt; run 01_backup.sh --apply first"
(($(hours_since "$(receipt_value "$EVIDENCE_DIR/$bk/backup.json" at)") < 6)) || fail "the backup is older than 6 h; re-run 01 --apply"
if [[ $IGNORE_WINDOW == 1 ]]; then warn "--ignore-window: quiet-minute check skipped"; else
  quiet_minute_now || fail "not a quiet minute (hh:05-hh:09 or hh:35-hh:39), or pass --ignore-window"
fi

OUT="$EVIDENCE_DIR/$STAMP-create-app-role"
mkdir -p "$OUT"
set +e
"$PY" "$ROLE_SCRIPT" "${ROLE_ARGS[@]}" "${PASS_ARGS[@]}" --apply 2>&1 | tee "$OUT/apply.txt"
rc=${PIPESTATUS[0]}
set -e
q role_rows "select rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin from pg_roles where rolname in ('$BOOTSTRAP_ROLE', '$APP_ROLE') order by rolname;" | tee "$OUT/roles.txt" | sed 's/^/  /'
q owners "select pg_get_userbyid(relowner) || ':' || relkind::text, count(*) from pg_class where relnamespace = 'public'::regnamespace group by 1 order by 1;" | tee "$OUT/owners.txt" | sed 's/^/  /'
write_receipt "$OUT/create_app_role.json" step=02_create_app_role at="$NOW_ISO" grant="$N8N_APP_ROLE_GRANT" \
  role_script_rc="$rc" password_file="$PASSWORD_FILE"
if [[ $rc -ne 0 ]]; then
  say "STEP 02 NOT COMPLETE (role script exit $rc). Postgres rolled the transaction back if it failed mid-way."
  say "Re-run after the cause is fixed; if the password file now exists use --reuse-password-file."
  exit "$rc"
fi
say "STEP 02 OK — n8n still connects as $(container_env_value DB_POSTGRESDB_USER). Next: bash 03_switch_compose.sh"
