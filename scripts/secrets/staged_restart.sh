#!/usr/bin/env bash
# Staged restart of protective services — ONLY outside market hours (before 09:00 or after 16:15 ET).
set -euo pipefail
export TZ=America/New_York
PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
cd "$PROJ"
now_m=$((10#$(date +%H)*60 + 10#$(date +%M)))
if (( now_m >= 9*60 && now_m < 16*60+15 )); then
  echo "REFUSE: market hours ET ($(date)). Wait until 16:15 or before 09:00."
  exit 3
fi

# holdings guard
python3 - <<'PY'
import json
from pathlib import Path
d=json.loads(Path("data/portfolios/state/holdings.json").read_text())
h=d.get("holdings") or []
t=float((d.get("portfolio_totals") or {}).get("total_value") or 0)
print(f"holdings n={len(h)} total={t}")
if len(h)<10 or t<1e5:
    raise SystemExit("HOLDINGS_ALARM")
PY

health() {
  local name="$1"
  echo "== health $name =="
  case "$name" in
    portfolio_server)
      curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7777/api/v2/broker-accounts || return 1
      ;;
    db)
      PYTHONPATH=scripts:scripts/lib .venv/bin/python -c "from db_adapter import _get_conn; c=_get_conn(); c.cursor().execute('SELECT 1'); print('db_ok')"
      ;;
    *)
      echo "skip"
      ;;
  esac
}

echo "restart portfolio_server..."
bash linux_launchers/restart_server.sh
sleep 4
health portfolio_server
health db

python3 - <<'PY'
import json
from pathlib import Path
d=json.loads(Path("data/portfolios/state/holdings.json").read_text())
print("post holdings", len(d.get("holdings") or []), (d.get("portfolio_totals") or {}).get("total_value"))
PY
echo "staged_restart_done"
