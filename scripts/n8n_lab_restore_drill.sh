#!/usr/bin/env bash
# n8n_lab_restore_drill.sh — weekly proof that the newest n8n lab dump restores.
# Restores into a throwaway database INSIDE the lab db container, checks its content, drops it.
# Never touches production Postgres (127.0.0.1:5432) and never touches the live `n8n` database.
#
#   bash scripts/n8n_lab_restore_drill.sh --dry-run | --apply
# Receipt: $OUT_DIR/n8n_lab_restore_drill_last.json (schema N8nLabRestoreDrill@v2)
#
# Verdict (scripts/lib/n8n_lab_restore_verdict.py, policy config/n8n_lab_restore_drill.json): PASSED only when
# pg_restore exits 0 with no error line, the public table count equals live, workflow_entity is non-empty and
# matches the dump's manifest (<dump>.manifest.json from scripts/n8n_lab_backup.sh), credentials_entity matches,
# the fabric workflow ids and every manifest workflow id are present, execution_entity is readable, one restored
# credential decrypts with the n8n key (probe runs inside $N8N_APP_CONTAINER; prints one word, never the key), the
# dump's sha256 matches the manifest, and the drill database was dropped. Anything else -> state FAILED, exit 1.
# DR audit finding A (2026-10-15): the v1 verdict at the old line 35 was `restored == live and restored > 0`,
# so pg_restore errors and an empty workflow_entity passed, and a false verdict exited 0.
# An abort mid-drill (a docker/psql step that fails) still writes a FAILED receipt (trap) and drops the drill DB.
# scripts/n8n_incident_fanin.py raises state FAILED as a P1 (source n8n_lab_restore_drill).
set -euo pipefail
MODE="${1:---dry-run}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DB_CONTAINER="${N8N_DB_CONTAINER:-m8m-n8n-db}"
APP_CONTAINER="${N8N_APP_CONTAINER:-m8m-n8n}"
KEYPROBE="$ROOT/scripts/lib/n8n_credential_key_probe.js"
OUT_DIR="${N8N_BACKUP_DIR:-$HOME/trade-ai-releases/persistent-state/backups/n8n}"
POLICY="${N8N_RESTORE_DRILL_POLICY:-$ROOT/config/n8n_lab_restore_drill.json}"
VERDICT="$ROOT/scripts/lib/n8n_lab_restore_verdict.py"
RECEIPT="$OUT_DIR/n8n_lab_restore_drill_last.json"
DRILL_DB="n8n_drill_$(date -u +%Y%m%d%H%M%S)"
latest="$(find "$OUT_DIR" -maxdepth 1 -name 'n8n-lab-*.dump' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2- || true)"
[[ -n "$latest" ]] || { echo "no dump in $OUT_DIR" >&2; exit 2; }

# SQL goes in on stdin (no shell quoting of SQL); the database name is passed as an argument.
q_live() { docker exec -i "$DB_CONTAINER" sh -c 'psql -v ON_ERROR_STOP=1 -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }
q_db()   { docker exec -i "$DB_CONTAINER" sh -c 'psql -v ON_ERROR_STOP=1 -tA -U "$POSTGRES_USER" -d "$1"' sh "$1"; }
TABLES_SQL="select count(*) from information_schema.tables where table_schema='public';"

live_tables="$(printf '%s\n' "$TABLES_SQL" | q_live)"
if [[ "$MODE" == "--dry-run" ]]; then
  echo "DRY RUN: would restore $latest into $DRILL_DB inside $DB_CONTAINER, check content against live ($live_tables tables) and ${latest}.manifest.json (policy $POLICY), then DROP $DRILL_DB"; exit 0
fi
[[ "$MODE" == "--apply" ]] || { echo "usage: $0 --dry-run|--apply" >&2; exit 2; }

FACTS="$(mktemp -d)"
created=0
finalized=0
fact() { printf '%s\n' "$2" > "$FACTS/$1"; }
# Run a query against the drill DB and record value + rc as facts. Never aborts the drill.
probe() {
  local name="$1" sql="$2" out rc
  set +e
  out="$(printf '%s\n' "$sql" | q_db "$DRILL_DB" 2>>"$FACTS/probe_stderr.txt")"
  rc=$?
  set -e
  printf '%s\n' "$out" > "$FACTS/$name"
  printf '%s\n' "$rc" > "$FACTS/$name.rc"
}
drop_drill() {
  if [[ "$created" == "1" ]]; then
    set +e
    printf 'drop database if exists "%s";\n' "$DRILL_DB" | q_db postgres >/dev/null 2>&1
    printf '%s\n' "$?" > "$FACTS/drop_rc"
    docker exec "$DB_CONTAINER" rm -f /tmp/drill.dump >/dev/null 2>&1
    set -e
    created=0
  fi
}
finalize() {
  local rc=0
  [[ "$finalized" == "1" ]] && return 0
  finalized=1
  drop_drill
  local args=(--facts "$FACTS" --policy "$POLICY" --receipt "$RECEIPT")
  [[ -f "${latest}.manifest.json" ]] && args+=(--manifest "${latest}.manifest.json")
  python3 "$VERDICT" "${args[@]}" || rc=$?
  rm -rf -- "$FACTS"
  return "$rc"
}
# shellcheck disable=SC2329  # invoked by `trap on_exit EXIT`
on_exit() {
  local rc=$?
  if [[ "$finalized" != "1" ]]; then
    fact aborted_at "rc=$rc"
    finalize || true
    exit 1   # an aborted drill is never a success
  fi
}
trap on_exit EXIT

fact started "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fact dump "$latest"
fact drill_db "$DRILL_DB"
fact live_tables "$live_tables"
fact dump_sha256 "$(sha256sum "$latest" | cut -c1-64)"
docker cp "$latest" "$DB_CONTAINER:/tmp/drill.dump"
printf 'create database "%s";\n' "$DRILL_DB" | q_db postgres >/dev/null
created=1
set +e
docker exec "$DB_CONTAINER" sh -c 'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-privileges /tmp/drill.dump' sh "$DRILL_DB" \
  >/dev/null 2>"$FACTS/restore_stderr.txt"
fact restore_rc "$?"
set -e
probe restored_tables "$TABLES_SQL"
probe workflow_count "select count(*) from workflow_entity;"
probe workflow_ids "select id from workflow_entity order by id;"
probe credentials_count "select count(*) from credentials_entity;"
probe execution_count "select count(*) from execution_entity;"
# Key check (DD10): one restored credential ciphertext -> the probe inside the n8n app container -> one word.
# The ciphertext stays in a shell variable (never written to the facts dir); the key never leaves the container.
set +e
cipher="$(printf '%s\n' "select data from credentials_entity order by id limit 1;" | q_db "$DRILL_DB" 2>/dev/null)"
key_word="$(printf '%s' "$cipher" | docker exec -i "$APP_CONTAINER" node -e "$(cat "$KEYPROBE")" 2>/dev/null | head -1)"
set -e
unset cipher
fact key_check "${key_word:-PROBE_FAILED}"
set +e
finalize
rc=$?
set -e
exit "$rc"
