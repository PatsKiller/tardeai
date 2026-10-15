#!/usr/bin/env bash
# n8n_lab_backup.sh — nightly pg_dump of the n8n LAB database (docker project m8m-n8n).
#
# Authority: READ_ONLY_ADVISORY on production. Touches only the lab containers and the
# backup directory. Writes a receipt that would not exist if the dump had not run (§0 rule 8).
#
#   bash scripts/n8n_lab_backup.sh --dry-run     # prints the plan, writes nothing
#   bash scripts/n8n_lab_backup.sh --apply       # dump + manifest + receipt + retention (keep 14)
#
# Receipt:  $OUT_DIR/n8n_lab_backup_last.json   (schema N8nLabBackupReceipt@v1; + manifest fields 2026-10-15)
# Dump:     $OUT_DIR/n8n-lab-<UTC stamp>.dump     (pg_dump custom format, from inside the db container)
# Manifest: $OUT_DIR/n8n-lab-<UTC stamp>.dump.manifest.json (schema N8nLabDumpManifest@v1): sha256 of the dump and
#           the live workflow_entity / credentials_entity counts and workflow ids read just BEFORE and just AFTER
#           the dump (pg_dump takes its own snapshot; the drill accepts a count inside [before, after] and requires
#           the ids present both times). scripts/n8n_lab_restore_drill.sh checks a restore against it (DR audit A).
#
# Exit 1 when the receipt says ok:false (empty dump, empty TOC, manifest counts unreadable), so the platform
# maintenance step records a failure instead of a silent bad night.
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
# SQL on stdin, so no SQL is shell-quoted.
q_live() { docker exec -i "$DB_CONTAINER" sh -c 'psql -v ON_ERROR_STOP=1 -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }
tables_live="$(printf '%s\n' "select count(*) from information_schema.tables where table_schema='public';" | q_live 2>/dev/null || echo 0)"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "DRY RUN: would dump $DB_CONTAINER (public tables: $tables_live) -> $DUMP (+ .manifest.json) ; keep $KEEP ; receipt $RECEIPT"
  exit 0
fi
[[ "$MODE" == "--apply" ]] || { echo "usage: $0 --dry-run|--apply" >&2; exit 2; }

mkdir -p "$OUT_DIR"; chmod 700 "$OUT_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
# One fact per file; a failed query leaves the file empty, which the manifest records as null (never a number).
snap() {
  local tag="$1"
  printf '%s\n' "select count(*) from workflow_entity;" | q_live > "$WORK/wf_$tag" 2>/dev/null || : > "$WORK/wf_$tag"
  printf '%s\n' "select count(*) from credentials_entity;" | q_live > "$WORK/cred_$tag" 2>/dev/null || : > "$WORK/cred_$tag"
  printf '%s\n' "select id from workflow_entity order by id;" | q_live > "$WORK/ids_$tag" 2>/dev/null || : > "$WORK/ids_$tag"
}
snap before
docker exec "$DB_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$DUMP.part"
snap after
mv "$DUMP.part" "$DUMP"; chmod 600 "$DUMP"
bytes="$(stat -c %s "$DUMP")"
sha="$(sha256sum "$DUMP" | cut -c1-64)"
# grep -c prints 0 AND exits 1 on no match; `|| echo 0` then produced "0\n0" and crashed int(). Count in one step.
toc_tables="$( { pg_restore -l "$DUMP" 2>/dev/null || true; } | awk '/TABLE DATA/ {n++} END {print n+0}')"
# retention: keep newest $KEEP dumps (and their manifests)
find "$OUT_DIR" -maxdepth 1 -name 'n8n-lab-*.dump' -printf '%T@ %p\n' 2>/dev/null | sort -rn | tail -n +$((KEEP+1)) | cut -d' ' -f2- |
  while read -r old; do rm -f -- "$old" "$old.manifest.json"; done
kept="$(find "$OUT_DIR" -maxdepth 1 -name 'n8n-lab-*.dump' 2>/dev/null | wc -l)"
set +e
python3 - "$RECEIPT" "$DUMP" "$bytes" "$sha" "$tables_live" "$toc_tables" "$kept" "$WORK" <<'PY'
import json, sys, datetime, re, os
receipt, dump, b, sha, live, toc, kept, work = sys.argv[1:]
def num(name):
    try:
        raw = open(os.path.join(work, name)).read().strip()
    except OSError:
        return None
    return int(raw) if re.fullmatch(r"\d+", raw) else None
def ids(name):
    try:
        return sorted({x.strip() for x in open(os.path.join(work, name)).read().splitlines() if x.strip()})
    except OSError:
        return None
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
wb, wa, cb, ca = num("wf_before"), num("wf_after"), num("cred_before"), num("cred_after")
ib, ia = ids("ids_before"), ids("ids_after")
counts_ok = None not in (wb, wa, cb, ca) and (wb or 0) > 0
man = {"schema": "N8nLabDumpManifest@v1", "as_of": now, "dump": dump, "bytes": int(b), "sha256": sha,
       "workflow_count_before": wb, "workflow_count_after": wa,
       "credentials_count_before": cb, "credentials_count_after": ca,
       # ids present at BOTH reads: a workflow created or deleted during the dump is not required of the restore
       "workflow_ids": sorted(set(ib or []) & set(ia or [])) if (ib and ia) else None,
       "toc_table_data_entries": int(toc)}
tmp = dump + ".manifest.json.tmp"
json.dump(man, open(tmp, "w"), indent=1)
os.replace(tmp, dump + ".manifest.json")
ok = int(toc) > 0 and int(b) > 0 and counts_ok and man["workflow_ids"] is not None
json.dump({"schema": "N8nLabBackupReceipt@v1", "as_of": now,
           "dump": dump, "bytes": int(b), "sha256": sha, "live_public_tables": int(live or 0),
           "toc_table_data_entries": int(toc), "dumps_kept": int(kept),
           "manifest": dump + ".manifest.json", "workflow_count": wa, "credentials_count": ca,
           "manifest_counts_ok": bool(counts_ok),
           "ok": bool(ok), "note": "encryption key not in dump; escrow in Bitwarden SM"},
          open(receipt, "w"), indent=1)
print(json.dumps({"ok": bool(ok), "dump": dump, "bytes": int(b), "toc_table_data": int(toc), "kept": int(kept),
                  "workflows": wa, "credentials": ca}))
sys.exit(0 if ok else 1)
PY
rc=$?
set -e
exit "$rc"
