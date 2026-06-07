#!/usr/bin/env bash
# Drain the Hermes paper-loop backlog: loop the ticker_challenger until every closed paper trade has a
# related_trade_id reflection, or a safety cap is hit. Research-only (writes hermes_research_intelligence).
set -a; . ./.env 2>/dev/null; set +a
Q="select count(*) from paper_trades p where (lower(coalesce(status,''))='closed' or exit_time is not null) and symbol ~ '^[A-Z]{1,5}\$' and not exists(select 1 from hermes_research_intelligence h where h.related_trade_id=p.id)"
unlinked(){ .venv/bin/python -c "import os,psycopg2;c=psycopg2.connect(host=os.getenv('DB_HOST'),port=os.getenv('DB_PORT'),dbname=os.getenv('DB_NAME'),user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'));cur=c.cursor();cur.execute(\"$Q\");print(cur.fetchone()[0])"; }
START=$(unlinked); echo "[drain] start: $START unlinked"
for i in $(seq 1 10); do
  R=$(unlinked); echo "[drain] iter $i: $R unlinked"
  [ "$R" -eq 0 ] && { echo "[drain] DONE — backlog empty"; break; }
  .venv/bin/python scripts/hermes_autonomous_loop.py --loop ticker_challenger --apply --max-rows 20 >/tmp/drain_iter_$i.log 2>&1
  echo "[drain]   iter $i: $(grep -c COMMITTED /tmp/drain_iter_$i.log) committed, $(grep -c 'VALIDATION FAILED' /tmp/drain_iter_$i.log) rejected"
done
echo "[drain] end: $(unlinked) unlinked (was $START)"
