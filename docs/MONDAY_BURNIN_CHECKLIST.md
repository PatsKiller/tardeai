# Monday ATM Burn-In Checklist

Status:      ACTIVE
as_of:       2026-05-23T15:34:57-04:00
Measured at: efcc51365 / not measured

Run at 09:00 ET (35 min before market open).

## Health (5 min)
- [ ] Pipeline: `curl -s localhost:7777/api/v2/pipeline-health-master | python3 -c "import sys,json;print(json.load(sys.stdin).get('data',{}).get('summary',{}))"`
  - healthy >= 28, critical == 0
- [ ] Aegis morning brief in both Telegram IDs (check phone)
- [ ] No unread approvals (Approvals badge in Command Center)

## State (3 min)
- [ ] Holdings: `python3 -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'],len(d.get('holdings',[])))"`
  - ~$1.2M, 47 positions
- [ ] Open positions all have stops: `psql -c "SELECT symbol, stop_loss, stop_order_id IS NOT NULL FROM paper_trades WHERE status='open';"`
- [ ] ATM caps: `psql -c "SELECT COUNT(*) FILTER (WHERE status='open' AND atm_decision_id IS NOT NULL) as atm_open FROM paper_trades;"`
  - atm_open ≤ 6

## Inputs (5 min)
- [ ] Agent results from Friday: `psql -c "SELECT agent, MAX(created_at)::date FROM watchlist_agent_results WHERE created_at > NOW()-INTERVAL '72 hours' GROUP BY 1;"`
- [ ] News articles recent: `psql -c "SELECT COUNT(*) FROM news_articles WHERE created_at > NOW()-INTERVAL '72 hours';"`
  - Should be >50. If 0, run manually: `.venv/bin/python scripts/news_ingestion.py --priority`
- [ ] Verify news cron fired this morning: check `logs/news_ingestion.log` mtime

## Known degraded inputs (acknowledged for burn-in week)
- News gap 5/21-5/22 (system reboot, articles lost). See docs/_findings/news_ingestion_gap_2026-05-24.md
- 192 fresh articles ingested 5/23 via manual run. Monitor cron on Monday.

## Mode (1 min)
- [ ] `grep ALPACA_MODE .env` → paper
- [ ] `grep LLM_DISABLE_LIVE_EXECUTION .env` → true

## If anything fails
- DO NOT let ATM scanner run until the failing item is understood
- Telegram both IDs: "ATM burn-in DELAYED — <reason>"
- Investigate, then re-run checklist
