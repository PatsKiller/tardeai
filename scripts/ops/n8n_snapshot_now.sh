#!/usr/bin/env bash
# n8n_snapshot_now.sh - the contract behind the approval action backup_n8n (n8n program 0.2a/0.2b).
# Runs scripts/n8n_backup.py --apply (database dump + data volume + workflow export + compose, gpg, verified Drive copy)
# and prints ONE final stdout line of JSON: {"dump_bytes", "volume_bytes", "export_bytes", "drive_link"}.
# Everything else goes to stderr. Exit non-zero (and print nothing on stdout) when the backup or its Drive
# verification failed - the caller treats any missing key or non-zero exit as a refusal. No arguments, no secrets.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
python3 "$ROOT/scripts/n8n_backup.py" --apply >&2
python3 - <<'PY'
import json, os, sys
from pathlib import Path
out = Path(os.environ.get("N8N_BACKUP_DIR", str(Path.home() / "trade-ai-releases/persistent-state/backups/n8n")))
doc = json.loads((out / "n8n_backup_last.json").read_text(encoding="utf-8"))
members = (doc.get("manifest") or {}).get("members") or {}
def size(pred):
    return next((m.get("bytes") for k, m in members.items() if pred(k)), None)
obj = ((doc.get("drive") or {}).get("object") or {})
res = {"dump_bytes": size(lambda k: k.startswith("db/") and k.endswith(".dump")),
       "volume_bytes": size(lambda k: k == "volume/n8n-data.tar.gz"),
       "export_bytes": size(lambda k: k == "workflows.json"),
       "drive_link": f"https://drive.google.com/file/d/{obj['id']}/view" if obj.get("id") else None}
if not doc.get("ok") or any(v in (None, "") for v in res.values()):
    print("n8n_snapshot_now: incomplete result: " + json.dumps({k: v is not None for k, v in res.items()}), file=sys.stderr)
    sys.exit(1)
print(json.dumps(res))
PY
