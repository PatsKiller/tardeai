# Monday ATM Burn-In Checklist

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

## Mode (1 min)
- [ ] `grep ALPACA_MODE .env` → paper
- [ ] `grep LLM_DISABLE_LIVE_EXECUTION .env` → true

## If anything fails
- DO NOT let ATM scanner run until the failing item is understood
- Telegram both IDs: "ATM burn-in DELAYED — <reason>"
- Investigate, then re-run checklist
