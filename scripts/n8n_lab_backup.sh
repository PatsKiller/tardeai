#!/usr/bin/env bash
# n8n_lab_backup.sh — nightly pg_dump of the n8n LAB database (docker project m8m-n8n).
#
# Authority: READ_ONLY_ADVISORY on production. Touches only the lab containers and the
# backup directory. Writes a receipt that would not exist if the dump had not run (§0 rule 8).
#
#   bash scripts/n8n_lab_backup.sh --dry-run     # prints the plan, writes nothing
#   bash scripts/n8n_lab_backup.sh --apply       # dump + receipt + retention (keep 14)
#
# Receipt: $OUT_DIR/n8n_lab_backup_last.json  (schema N8nLabBackupReceipt@v1)
# Dump:    $OUT_DIR/n8n-lab-<UTC stamp>.dump    (pg_dump custom format, from inside the db container)
#
# The encryption key is NOT in the dump (it lives in the n8n volume and in Bitwarden SM escrow);
# a dump without that key restores workflows but not credentials. That is intended.
set -euo pipefail

MODE="${1:---dry-run}"
DB_CONTAINER="${N8N_DB_CONTAINER:-m8m-n8n-db}"
OUT_DIR="${N8N_BACKUP_DIR:-$HOME/trade-ai-releases/persistent-state/backups/n8n}"
KEEP="${N8N_BACKUP_KEEP:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="$OUT_DIR/n8n-lab-$STAMP.dump"
RECEIPT="$OUT_DIR/n8n_lab_backup_last.json"

if ! docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  echo "n8n_lab_backup: container $DB_CONTAINER not found" >&2; exit 2
fi
tables_live="$(docker exec "$DB_CONTAINER" sh -c 'psql -tA -U "$POSTGRES_USER" "$POSTGRES_DB" -c "select count(*) from information_schema.tables where table_schema='"'"'public'"'"'"' 2>/dev/null || echo 0)"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "DRY RUN: would dump $DB_CONTAINER (public tables: $tables_live) -> $DUMP ; keep $KEEP ; receipt $RECEIPT"
  exit 0
fi
[[ "$MODE" == "--apply" ]] || { echo "usage: $0 --dry-run|--apply" >&2; exit 2; }

mkdir -p "$OUT_DIR"; chmod 700 "$OUT_DIR"
docker exec "$DB_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$DUMP.part"
mv "$DUMP.part" "$DUMP"; chmod 600 "$DUMP"
bytes="$(stat -c %s "$DUMP")"
sha="$(sha256sum "$DUMP" | cut -c1-64)"
toc_tables="$(pg_restore -l "$DUMP" 2>/dev/null | grep -c 'TABLE DATA' || echo 0)"
# retention: keep newest $KEEP dumps
ls -1t "$OUT_DIR"/n8n-lab-*.dump 2>/dev/null | tail -n +$((KEEP+1)) | while read -r old; do rm -f -- "$old"; done
kept="$(ls -1 "$OUT_DIR"/n8n-lab-*.dump 2>/dev/null | wc -l)"
python3 - "$RECEIPT" "$DUMP" "$bytes" "$sha" "$tables_live" "$toc_tables" "$kept" <<'PY'
import json, sys, datetime
receipt, dump, b, sha, live, toc, kept = sys.argv[1:]
json.dump({"schema": "N8nLabBackupReceipt@v1", "as_of": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "dump": dump, "bytes": int(b), "sha256": sha, "live_public_tables": int(live),
           "toc_table_data_entries": int(toc), "dumps_kept": int(kept),
           "ok": int(toc) > 0 and int(b) > 0, "note": "encryption key not in dump; escrow in Bitwarden SM"},
          open(receipt, "w"), indent=1)
print(json.dumps({"ok": int(toc) > 0, "dump": dump, "bytes": int(b), "toc_table_data": int(toc), "kept": int(kept)}))
PY
