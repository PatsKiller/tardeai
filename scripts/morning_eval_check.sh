#!/usr/bin/env bash
# Morning verification of the overnight AI Trade Eval batch + setup-quality prior.
# READ-ONLY. Writes a report to logs/morning_eval_check.log and best-effort Telegram.
set -uo pipefail
PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
cd "$PROJ"
LOG="$PROJ/logs/morning_eval_check.log"
PY="$PROJ/.venv/bin/python"
B=http://localhost:7777
ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }

REPORT="$(
echo "===== Morning eval check — $(ts) ====="

# 1) daemon no longer running
if pgrep -f "trade_close_llm_analyzer.py --structured" >/dev/null 2>&1; then
  echo "⚠ eval daemon STILL RUNNING (overnight batch not finished)"
else
  echo "✓ eval daemon finished"
fi

# 2) structured eval count + verdicts
curl -s --max-time 10 "$B/api/v2/backtesting/trade-evaluations" | "$PY" -c "
import sys,json
try:
  d=json.load(sys.stdin); x=d.get('data',{})
  ev=x.get('evaluations',[]); vd=x.get('verdict_distribution',[])
  print(f'  structured evals: {len(ev)}')
  for v in vd: print(f'    - {v[\"eval_verdict\"]}: {v[\"n\"]} (avg {v[\"avg_score\"]})')
except Exception as e: print('  ERROR reading trade-evaluations:', e)
"

# 3) cron ran last night? (look for today's-ish entries)
for f in structured_eval setup_quality_prior; do
  L="$PROJ/logs/$f.log"
  if [ -f "$L" ]; then echo "  $f.log last line: $(tail -1 "$L" 2>/dev/null | cut -c1-120)"
  else echo "  $f.log: NOT FOUND (cron may not have run)"; fi
done

# 4) refreshed prior + advisory counts
curl -s --max-time 10 "$B/api/v2/atm/setup-advisory" | "$PY" -c "
import sys,json
try:
  d=json.load(sys.stdin); x=d.get('data',{})
  print('  prior bands:')
  for p in x.get('prior',[]):
    sc=p.get('llm_score') or p.get('grade_score')
    print(f\"    RSI {p['band']}: score~{sc} {p.get('dominant_verdict') or ''} (n={p['n']}, {p['confidence']})\")
  print(f\"  proposal advisories: {len(x.get('advisories',[]))}\")
except Exception as e: print('  ERROR reading setup-advisory:', e)
"
for ent in incubator watchlist; do
  curl -s --max-time 10 "$B/api/v2/setup-advisory/candidates?entity=$ent" | "$PY" -c "
import sys,json
try:
  d=json.load(sys.stdin); a=d.get('data',{}).get('advisories',[])
  caut=sum(1 for x in a if x.get('advisory_flag')=='caution')
  print(f'  $ent advisories: {len(a)} ({caut} caution)')
except Exception as e: print('  ERROR $ent:', e)
"
done

# 5) flag model_error rows
"$PY" - <<'PYEOF'
from pathlib import Path; import os
for l in Path('.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'): k,v=l.split('=',1); os.environ.setdefault(k.strip(),v.strip())
import psycopg2
c=psycopg2.connect(host='127.0.0.1',dbname='trade_ai',user='trade_ai',password=os.environ['DB_PASSWORD']).cursor()
c.execute("select count(*) from trade_llm_reviews where review_stage='structured_backtest_eval' and status='model_error'")
n=c.fetchone()[0]
print(f"  model_error rows: {n}" + ("  ⚠ investigate" if n else "  ✓ none"))
PYEOF
echo "===== end ====="
)"

echo "$REPORT" | tee -a "$LOG"

# Best-effort Telegram via the safe shell sender (stdin body → central chokepoint).
# No raw curl / token interpolation — routes + dedupes like every other producer.
if printf '%s' "$REPORT" | "$PY" "$PROJ/scripts/send_operator_alert.py" --quiet; then
  echo "(telegram accepted)"
else
  echo "(telegram skipped — report logged only)"
fi
