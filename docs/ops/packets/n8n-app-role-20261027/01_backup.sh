#!/usr/bin/env bash
# 01_backup.sh — packet n8n-app-role-20261027, step 01: a fresh pg_dump of the n8n database before the role change.
#
#   bash 01_backup.sh            # DRY RUN (default): prints the plan, writes nothing
#   bash 01_backup.sh --apply    # dump + role-attribute snapshot + manifest + receipt
#
# Writes to the existing n8n backup directory ($BACKUP_DIR, mode 700):
#   n8n-pre-app-role-<UTC>.dump              pg_dump custom format of database n8n, from inside the db container
#   n8n-pre-app-role-<UTC>.roles.sql         pg_dumpall --roles-only --no-role-passwords (role attributes, no hashes)
#   n8n-pre-app-role-<UTC>.manifest.json     sha256, bytes, TOC table-data entries, workflow count, active ids
# The name does not match the nightly `n8n-lab-*.dump` retention glob, so scripts/n8n_lab_backup.sh never prunes it
# and the weekly restore drill keeps testing the nightly dumps. Nothing is deleted or overwritten. The encryption key
# is not in the dump (same as the nightly backup). Exit 0 ok / 1 the dump looks wrong / 2 cannot run or refused.
set -euo pipefail
# shellcheck source=docs/ops/packets/n8n-app-role-20261027/_lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
APPLY=0
case "${1:-}" in
  "") ;;
  --apply) APPLY=1 ;;
  *) fail "usage: $0 [--apply]" ;;
esac

BASE="$BACKUP_DIR/n8n-$BACKUP_TAG-$STAMP"
DUMP="$BASE.dump"
ROLES="$BASE.roles.sql"
MANIFEST="$BASE.manifest.json"
docker inspect "$DB_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q true || fail "$DB_CONTAINER is not running"
tables="$(q public_tables "select count(*) from information_schema.tables where table_schema = 'public';")"
workflows="$(q workflow_count "select count(*) from workflow_entity;")"
size="$(q db_size "select pg_size_pretty(pg_database_size('$DB_NAME'));")"
free="$(df -h --output=avail "$(dirname "$BACKUP_DIR")" 2>/dev/null | tail -n 1 | tr -d ' ' || echo '?')"

if [[ $APPLY == 0 ]]; then
  say "DRY RUN — nothing written"
  say "  would dump $DB_CONTAINER:$DB_NAME ($tables public tables, $workflows workflows, $size; free $free) as $BOOTSTRAP_ROLE over the local socket"
  say "  -> $DUMP (mode 600)"
  say "  -> $ROLES (role attributes only, --no-role-passwords)"
  say "  -> $MANIFEST"
  say "  then pg_restore -l inside the container to count TABLE DATA entries; no retention, no delete"
  exit 0
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
[[ ! -e "$DUMP" ]] || fail "$DUMP exists; never overwritten"
umask 077
ids_before="$(active_workflows | paste -sd',')"
docker exec "$DB_CONTAINER" pg_dump -U "$BOOTSTRAP_ROLE" -d "$DB_NAME" -Fc >"$DUMP.part"
mv -- "$DUMP.part" "$DUMP"
docker exec "$DB_CONTAINER" pg_dumpall -U "$BOOTSTRAP_ROLE" --roles-only --no-role-passwords >"$ROLES"
chmod 600 "$DUMP" "$ROLES"
bytes="$(stat -c %s "$DUMP")"
sha="$(sha256_of "$DUMP")"
toc_list="$(docker exec -i "$DB_CONTAINER" pg_restore -l <"$DUMP" 2>/dev/null || true)"
toc="$(awk '/TABLE DATA/ {n++} END {print n+0}' <<<"$toc_list")"
toc_has_workflows=0
grep -Eq 'TABLE DATA public workflow_entity( |$)' <<<"$toc_list" && toc_has_workflows=1
roles_have_app="$(grep -c "ROLE $APP_ROLE" "$ROLES" || true)"
# ok only when the dump is non-empty, its TOC lists table data, and workflow_entity's data is in it.
ok=false
[[ "$bytes" -gt 0 && "$toc" -gt 0 && $toc_has_workflows == 1 ]] && ok=true
write_receipt "$MANIFEST" schema_note=N8nPreAppRoleDump step=01_backup at="$NOW_ISO" ok="$ok" dump="$DUMP" \
  bytes="$bytes" sha256="$sha" toc_table_data_entries="$toc" toc_has_workflow_entity="$toc_has_workflows" \
  public_tables="$tables" workflow_count="$workflows" active_workflow_ids="$ids_before" roles_snapshot="$ROLES" \
  roles_snapshot_names_n8n_app="$roles_have_app" \
  note="encryption key not in the dump; restore only into a NEW database (README, last resort)"
chmod 600 "$MANIFEST"
write_receipt "$EVIDENCE_DIR/$STAMP-backup/backup.json" step=01_backup at="$NOW_ISO" ok="$ok" dump="$DUMP" \
  sha256="$sha" bytes="$bytes" toc_table_data_entries="$toc" toc_has_workflow_entity="$toc_has_workflows" \
  manifest="$MANIFEST"
if [[ $ok == true ]]; then
  # the pointer 02 reads moves only for a backup that passed
  printf '%s\n' "$STAMP-backup" >"$EVIDENCE_DIR/LATEST_BACKUP"
  say "BACKUP OK: $DUMP ($bytes bytes, sha256 $sha, $toc TABLE DATA entries) — next: bash 02_create_app_role.sh"
  exit 0
fi
say "BACKUP SUSPECT: bytes=$bytes toc=$toc workflow_entity_data=$toc_has_workflows — do not continue."
say "LATEST_BACKUP not moved; the files are kept for inspection. Re-run 01_backup.sh --apply after the cause is fixed."
exit 1
