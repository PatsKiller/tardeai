# Trade AI v12 -- Operator Cheat Sheet

**Last updated:** 2026-05-09

---

## Health Checks

```bash
# Full system health (single command)
curl -s http://localhost:7777/api/v2/system-health | python3 -m json.tool

# Portfolio value assertion (must be > $1M)
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; assert v>1_000_000; print(f'OK: \${v:,.0f}')"

# Database health
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "SELECT COUNT(*) FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '24 hours';"

# Ollama / GPU status
curl -s http://localhost:11434/api/tags | python3 -c "import json,sys; print([m['name'] for m in json.load(sys.stdin)['models']])"

# Paper proposals status
curl -s http://localhost:7777/api/v2/paper-proposals | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Pending: {d.get(\"summary\",{}).get(\"pending\")}')"

# Pipeline health (31 stages)
curl -s http://localhost:7777/api/v2/pipeline-health-master | python3 -m json.tool

# Verify paper mode (CRITICAL)
grep ALPACA_MODE .env     # Must show: paper
grep LIVE_TRADING .env    # Must show: false
```

---

## Topic Intelligence

```bash
# Run topic ingestion for all gaps
.venv/bin/python scripts/topic_ingestion.py --gaps-only --no-llm

# Run with LLM curation (generates targeted queries from personal situation)
.venv/bin/python scripts/topic_ingestion.py --curate

# Run for single topic
.venv/bin/python scripts/topic_ingestion.py --topic ssdi

# Post-ingestion curation (rate quality, extract entities, improve queries)
.venv/bin/python scripts/topic_curator.py --improve-queries

# Telegram commands
# topic status         — show all topics with gap status
# topic add SSDI trust — add new topic
# topic url <id> <url> — add saved Google search URL
# topic run ssdi       — run ingestion for one topic
# topic run all        — run all topics
```

## Common Operator Actions

```bash
# Restart portfolio server
pkill -f portfolio_server.py; sleep 2; nohup .venv/bin/python scripts/portfolio_server.py &

# Run orchestrator manually
.venv/bin/python scripts/trade_ai_orchestrator.py --run-label manual

# Run incubator promoter (dry-run first, then live)
.venv/bin/python3 scripts/incubator_proposal_promoter.py --dry-run
.venv/bin/python3 scripts/incubator_proposal_promoter.py --run --limit 10

# Run multi-strategy classifier
.venv/bin/python3 scripts/multi_strategy_classifier.py --symbol NNE
.venv/bin/python3 scripts/multi_strategy_classifier.py --batch --limit 20 --llm

# Rebuild frontend
cd apps/command-center-v2 && npm run build && cd ../..

# Run system preflight check (23 points)
.venv/bin/python scripts/system_preflight_check.py

# Check cron count
crontab -l | grep -v "^#" | wc -l

# Tail orchestrator logs
tail -50 logs/orchestrator.log

# Tail proposal enrichment
tail -50 logs/proposal_enrichment.log
```

---

## Key File Locations

| File | Purpose |
|------|---------|
| `.env` | All secrets, API keys, LLM config, feature flags |
| `.env.example` | Template with documented variables |
| `config/strategies/*.yaml` | 20 strategy definitions (dynamically loaded) |
| `assets/screeners.yaml` | Finviz screener URLs + run windows |
| `data/portfolios/state/holdings.json` | Portfolio state (~50 positions) |
| `data/state/ticker_enrichment_cache.json` | Enriched symbol data (1,139 symbols) |
| `scripts/api_v2.py` | All API endpoints (11,700+ lines) |
| `scripts/local_llm_config.py` | LLM configuration hub |
| `logs/` | Runtime logs (100+ log files) |
| `backups/db/` | Database backups (7-day rolling) |
| `crontab_backup.txt` | Full cron schedule backup |

---

## Key API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/system-health` | GET | System health dashboard |
| `/api/v2/paper-proposals` | GET | All pending proposals |
| `/api/v2/paper-proposals/promote-from-incubator` | POST | Promote incubator to proposals |
| `/api/v2/pipeline-health-master` | GET | 31-stage pipeline status |
| `/api/v2/agent-pipeline` | GET | Agent job status |
| `/api/v2/incubator` | GET | Incubator universe |
| `/api/v2/strategy-configs` | GET | All strategy configs |
| `/api/v2/portfolio-summary` | GET | Portfolio totals and allocation |
| `/api/v2/execution-quality` | GET | TCA metrics |
| `/api/v2/broker-reconciliation` | GET | Recon items |

---

## Emergency Procedures

### Verify System Integrity

```bash
# 1. Holdings value check
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; assert v>1_000_000; print(f'OK: \${v:,.0f}')"

# 2. Paper mode verification
grep ALPACA_MODE .env     # MUST be: paper
grep LIVE_TRADING .env    # MUST be: false

# 3. Database connectivity
pg_isready -h localhost -p 5432 -U trade_ai

# 4. Ollama responsiveness
curl -s --max-time 5 http://localhost:11434/api/tags
```

### Database Restore

```bash
# From most recent backup
gunzip < backups/db/trade_ai_LATEST.sql.gz | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai

# From specific date
gunzip < backups/db/trade_ai_20260509.sql.gz | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai
```

### Configuration Restore

```bash
# Restore .env from session backup
cp backups/session25/.env.bak .env
```

### Restart All Services

```bash
# 1. PostgreSQL (system service)
sudo systemctl restart postgresql

# 2. Ollama (system service with GPU override)
sudo systemctl restart ollama

# 3. Portfolio Server
pkill -f portfolio_server.py; sleep 2; nohup .venv/bin/python scripts/portfolio_server.py &

# 4. Verify
curl -s http://localhost:7777/api/v2/system-health | python3 -m json.tool
```

---

## Daily Workflow Timeline

| Time | What | Script | Verify |
|------|------|--------|--------|
| 5:45 AM | Indicator refresh | `indicator_cache_refresh.py` | Check `indicator_confluence_cache` freshness |
| 6:30 AM | News ingestion | `news_ingestion.py` | `SELECT COUNT(*) FROM news_articles WHERE ...` |
| 7:00 AM | Finviz enrichment | `finviz_enrichment.py` | Check enrichment cache timestamps |
| 04/07/09/10 | Orchestrator runs | `trade_ai_orchestrator.py` | Check `pipeline_runs` for completion |
| 8:15 AM | Incubator refresh | `daily_incubator_refresh.py` | Check incubator scores updated |
| 8:20 AM | Proposal promoter | `incubator_proposal_promoter.py` | Check `paper_trade_proposals` |
| 8:00 PM | Overnight batch | `overnight_batch.py` | Check overnight log |
| Sun 7 PM | Weekly incubator build | `weekly_incubator_builder.py` | Check incubator universe count |
| Sun 10 PM | LLM classification | `weekly_incubator_builder.py --llm` | Check strategy assignments |

---

## Common Failures & Resolution

| Failure | Symptom | Fix |
|---------|---------|-----|
| **Finviz cookie expired** | Screener returns 0 results | Manual browser login to Finviz Elite, update cookie in `.env` |
| **Ollama GPU fallback to CPU** | Classification takes 300s instead of 15s | `sudo systemctl restart ollama`; verify Vulkan override |
| **Portfolio server 502** | React SPA shows connection error | `pkill -f portfolio_server.py && nohup .venv/bin/python scripts/portfolio_server.py &` |
| **DB connection refused** | All API calls fail | `sudo systemctl restart postgresql` |
| **Stale enrichment data** | Pipeline watchdog alert | Run `finviz_enrichment.py` manually |
| **LLM toll gate stuck** | Classification jobs queued indefinitely | Check for zombie flock process; remove lock file |
| **News ingestion timeout** | `news_articles` not updating | Check API key limits; re-run `news_ingestion.py` |
| **Cron not running** | No pipeline_runs entries | `systemctl --user status tradeai-continuous.timer`; check loginctl linger |

---

## Cost Levers (What Makes Bills Go Up)

| Lever | Current Impact | Cloud Impact |
|-------|---------------|--------------|
| **Cloud LLM fallback frequency** | Low (local GPU handles most) | High -- each fallback costs $0.01-0.10/call |
| **News API call volume** | 7 sources, 2x/day | API tier costs scale with call volume |
| **Finviz Elite subscription** | Fixed $39.95/mo | Same |
| **Alpaca data subscription** | Free tier (paper) | Paid tier for live market data |
| **Symbol enrichment breadth** | 1,139 symbols | API costs scale linearly with symbol count |
| **Agent processing volume** | 10-25 jobs/cycle | LLM inference cost per job |
| **Database size** | Growing (256 tables) | Managed DB storage costs |
| **GPU compute** | Fixed (Intel Arc B50) | GPU instance pricing ($0.50-2.00/hr) |
| **Log retention** | 7-day rolling | CloudWatch/Azure Monitor ingestion fees |
