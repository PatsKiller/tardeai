#!/usr/bin/env bash
# n8n_lab_restore_drill.sh — weekly proof that the newest n8n lab dump restores.
# Restores into a throwaway database INSIDE the lab db container, counts tables, drops it.
# Never touches production Postgres (127.0.0.1:5432) and never touches the live `n8n` database.
#
#   bash scripts/n8n_lab_restore_drill.sh --dry-run | --apply
# Receipt: $OUT_DIR/n8n_lab_restore_drill_last.json (schema N8nLabRestoreDrill@v1)
set -euo pipefail
MODE="${1:---dry-run}"
DB_CONTAINER="${N8N_DB_CONTAINER:-m8m-n8n-db}"
OUT_DIR="${N8N_BACKUP_DIR:-$HOME/trade-ai-releases/persistent-state/backups/n8n}"
RECEIPT="$OUT_DIR/n8n_lab_restore_drill_last.json"
DRILL_DB="n8n_drill_$(date -u +%Y%m%d%H%M%S)"
latest="$(ls -1t "$OUT_DIR"/n8n-lab-*.dump 2>/dev/null | head -1 || true)"
[[ -n "$latest" ]] || { echo "no dump in $OUT_DIR" >&2; exit 2; }
live_tables="$(docker exec "$DB_CONTAINER" sh -c 'psql -tA -U "$POSTGRES_USER" "$POSTGRES_DB" -c "select count(*) from information_schema.tables where table_schema='"'"'public'"'"'"')"
if [[ "$MODE" == "--dry-run" ]]; then
  echo "DRY RUN: would restore $latest into $DRILL_DB inside $DB_CONTAINER, compare table count to live ($live_tables), then DROP $DRILL_DB"; exit 0
fi
[[ "$MODE" == "--apply" ]] || { echo "usage: $0 --dry-run|--apply" >&2; exit 2; }
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker cp "$latest" "$DB_CONTAINER:/tmp/drill.dump"
docker exec "$DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d postgres -qc "create database '"$DRILL_DB"'"'
set +e
docker exec "$DB_CONTAINER" sh -c 'pg_restore -U "$POSTGRES_USER" -d '"$DRILL_DB"' --no-owner --no-privileges /tmp/drill.dump' >/dev/null 2>&1
rc=$?
set -e
restored="$(docker exec "$DB_CONTAINER" sh -c 'psql -tA -U "$POSTGRES_USER" -d '"$DRILL_DB"' -c "select count(*) from information_schema.tables where table_schema='"'"'public'"'"'"')"
wf="$(docker exec "$DB_CONTAINER" sh -c 'psql -tA -U "$POSTGRES_USER" -d '"$DRILL_DB"' -c "select count(*) from workflow_entity"' 2>/dev/null || echo -1)"
docker exec "$DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d postgres -qc "drop database '"$DRILL_DB"'"; rm -f /tmp/drill.dump'
python3 - "$RECEIPT" "$latest" "$started" "$rc" "$live_tables" "$restored" "$wf" <<'PY'
import json, sys, datetime
r, dump, started, rc, live, restored, wf = sys.argv[1:]
ok = int(restored) == int(live) and int(restored) > 0
json.dump({"schema": "N8nLabRestoreDrill@v1", "started": started,
           "finished": datetime.datetime.now(datetime.timezone.utc).isoformat(), "dump": dump,
           "pg_restore_rc": int(rc), "live_tables": int(live), "restored_tables": int(restored),
           "workflows_in_restore": int(wf), "counts_equal": ok, "dropped_drill_db": True,
           "production_postgres_touched": False, "ok": ok}, open(r, "w"), indent=1)
print(json.dumps({"ok": ok, "live": int(live), "restored": int(restored), "workflows": int(wf), "rc": int(rc)}))
PY
