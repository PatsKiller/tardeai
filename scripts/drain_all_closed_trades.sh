#!/usr/bin/env bash
# Drain the ENTIRE canonical closed-trade reflection backlog via --drain-closed-trades (operator-approved
# "complete all max drain left"). Loops until backlog==0, stalls (no progress 3x), or safety cap. Each
# challenger run is health-gated + singleton-locked; research-only writes.
set -a; . ./.env 2>/dev/null; set +a
Q="select count(*) from trade_instances ti where lower(coalesce(status,''))='closed' and symbol ~ '^[A-Z]{1,5}\$' and not exists(select 1 from hermes_research_intelligence h where h.trade_instance_id=ti.id)"
unlinked(){ .venv/bin/python -c "import os,psycopg2;c=psycopg2.connect(host=os.getenv('DB_HOST'),port=os.getenv('DB_PORT'),dbname=os.getenv('DB_NAME'),user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'));cur=c.cursor();cur.execute(\"$Q\");print(cur.fetchone()[0])"; }
START=$(unlinked); echo "[drain-all] start backlog=$START"
prev=-1; stuck=0
for i in $(seq 1 60); do
  R=$(unlinked); echo "[drain-all] iter $i backlog=$R"
  [ "$R" -eq 0 ] && { echo "[drain-all] DONE backlog=0"; break; }
  if [ "$R" -eq "$prev" ]; then stuck=$((stuck+1)); else stuck=0; fi
  if [ "$stuck" -ge 3 ]; then echo "[drain-all] STALLED at $R (3 no-progress iters; remaining symbols likely fail LLM validation or dedupe)"; break; fi
  prev=$R
  timeout 540 .venv/bin/python scripts/hermes_autonomous_loop.py --loop ticker_challenger --apply --max-rows 5 --drain-closed-trades >/tmp/drain_all_iter_$i.log 2>&1
  echo "[drain-all]   iter $i: rc=$? committed=$(grep -c COMMITTED /tmp/drain_all_iter_$i.log 2>/dev/null) rejected=$(grep -c 'VALIDATION FAILED' /tmp/drain_all_iter_$i.log 2>/dev/null)"
done
echo "[drain-all] END backlog=$(unlinked) (was $START)"
