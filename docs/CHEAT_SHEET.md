# Trade AI v12 -- Cheat Sheet

Quick reference for operating Trade AI v12 on `ms01-openclaw`.

---

## Health Checks

```bash
# System status
curl -s http://localhost:7777/api/v2/system-health | python3 -m json.tool

# Portfolio value
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); print(f'\${d[\"portfolio_totals\"][\"total_value\"]:,.0f}')"

# DB connection
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "SELECT COUNT(*) FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '24 hours';"

# Ollama status
curl -s http://localhost:11434/api/tags | python3 -c "import json,sys; print([m['name'] for m in json.load(sys.stdin)['models']])"

# Paper proposals
curl -s http://localhost:7777/api/v2/paper-proposals | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Pending: {d.get(\"summary\",{}).get(\"pending\")}')"
```

---

## Common Commands

```bash
# Restart portfolio server
pkill -f portfolio_server.py; sleep 2; nohup .venv/bin/python scripts/portfolio_server.py &

# Run orchestrator manually
.venv/bin/python scripts/trade_ai_orchestrator.py --run-label manual

# Run incubator promoter
.venv/bin/python3 scripts/incubator_proposal_promoter.py --dry-run
.venv/bin/python3 scripts/incubator_proposal_promoter.py --run --limit 10

# Run multi-strategy classifier
.venv/bin/python3 scripts/multi_strategy_classifier.py --symbol NNE
.venv/bin/python3 scripts/multi_strategy_classifier.py --batch --limit 20 --llm

# Rebuild frontend
cd apps/command-center-v2 && npm run build && cd ../..

# Check cron
crontab -l | grep -v "^#" | wc -l
```

---

## Key File Locations

| File | Purpose |
|------|---------|
| `.env` | All secrets, API keys, LLM config |
| `config/strategies/*.yaml` | 20 strategy definitions |
| `assets/screeners.yaml` | Finviz screener URLs + run windows |
| `data/portfolios/state/holdings.json` | Portfolio state |
| `data/state/ticker_enrichment_cache.json` | Enriched symbol data |
| `scripts/api_v2.py` | All API endpoints |
| `scripts/local_llm_config.py` | LLM configuration hub |
| `logs/` | Runtime logs |
| `backups/` | Session backups |

---

## Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/system-health` | GET | System health dashboard |
| `/api/v2/paper-proposals` | GET | All pending proposals |
| `/api/v2/paper-proposals/promote-from-incubator` | POST | Promote incubator to proposals |
| `/api/v2/pipeline-health-master` | GET | 31-stage pipeline status |
| `/api/v2/agent-pipeline` | GET | Agent job status |
| `/api/v2/incubator` | GET | Incubator universe |
| `/api/v2/strategy-configs` | GET | All strategy configs |

---

## Emergency Procedures

```bash
# Verify holdings untouched
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; assert v>1_000_000; print(f'OK: \${v:,.0f}')"

# Verify paper mode
grep ALPACA_MODE .env  # Must show: paper
grep LIVE_TRADING .env  # Must show: false

# Restore from backup
cp backups/session25/.env.bak .env

# Restore DB
gunzip < backups/db/trade_ai_LATEST.sql.gz | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai
```

---

## Daily Workflow

| Time | What | Script |
|------|------|--------|
| 5:45 AM | Indicator refresh | `indicator_cache_refresh.py` |
| 6:30 AM | News ingestion | `news_ingestion.py` |
| 7:00 AM | Finviz enrichment | `finviz_enrichment.py` |
| 04:00 / 07:00 / 09:00 / 10:00 | Orchestrator runs | `trade_ai_orchestrator.py` |
| 8:15 AM | Incubator refresh | `daily_incubator_refresh.py` |
| 8:20 AM | Proposal promoter | `incubator_proposal_promoter.py` |
| 8:00 PM | Overnight batch | `overnight_batch.py` |
| Sun 7:00 PM | Weekly incubator build | `weekly_incubator_builder.py` |
| Sun 10:00 PM | LLM classification | `weekly_incubator_builder.py --llm` |
