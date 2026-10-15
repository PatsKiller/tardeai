#!/usr/bin/env bash
# Read-only preflight: maturity-remeasure is on the live list, its cron line is active, the registry keeps it dry_run.
set -u
P="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE="${CODE:-$(cd "$P/../../../.." && pwd)}"
F="${LIVE_LANES_FILE:-$HOME/.config/tradeai/n8n-live-lanes.env}"
LANE=maturity-remeasure
ok=1
echo "file: $F"
stat -c '%A %U %s bytes mtime=%y' "$F" || ok=0
python3 "$P/edit_live_lanes.py" --file "$F" --remove "$LANE" || ok=0   # dry run: prints before/after, writes nothing
echo "cron line (expect one active, uncommented line; L1005 on 2026-10-14):"
crontab -l 2>/dev/null | grep -n 'maturity_remeasure.py' || echo "  no cron line found"
python3 - "$CODE" <<'PY' || ok=0
import json, sys
reg = {l["lane_id"]: l for l in json.load(open(sys.argv[1] + "/config/lane_registry.json"))["lanes"]}
d = reg["maturity-remeasure"].get("dispatch") or {}
print("registry dispatch.mode:", d.get("mode"), d.get("cron"))
sys.exit(0 if d.get("mode") == "dry_run" else 1)
PY
for u in tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service; do
  printf '%s: %s since %s\n' "$u" "$(systemctl --user is-active "$u")" \
    "$(systemctl --user show -p ActiveEnterTimestamp --value "$u")"
done
if [ "$ok" = 1 ]; then echo "PREFLIGHT OK"; else echo "PREFLIGHT FAILED"; exit 1; fi
