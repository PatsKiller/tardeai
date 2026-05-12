# Trade AI v12 — Restore Guide

**If you need to rebuild the system from scratch, follow this guide.**
**All backup files are in the git repo under the project root.**

---

## 1. Core Services

| Service | How to Start | Config Location |
|---|---|---|
| Portfolio server | `nohup .venv/bin/python scripts/portfolio_server.py &` | scripts/portfolio_server.py |
| Trade AI continuous runner | `systemctl --user start tradeai-continuous.service` | ~/.config/systemd/user/tradeai-continuous.service |
| OpenClaw gateway | `openclaw gateway restart` | ~/.openclaw/openclaw.json |
| Ollama LLM | `ollama serve` (auto-starts) | Model: qwen3:1.7b |
| PostgreSQL | `sudo systemctl start postgresql` | DB: trade_ai, user: trade_ai |

## 2. Critical Environment Variables (.env)

```
DB_PASSWORD=<your_password>
FINNHUB_API_KEY=<key>
FMP_API_KEY=<key>
FINVIZ_COOKIE=<full_elite_session_cookie>
YOUTUBE_API_KEY=<key>
ALPHA_VANTAGE_API_KEY=<key>
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<id>
XAI_API_KEY=<key>
# Optional:
#FRED_API_KEY=
#BENZINGA_API_KEY=
#BRAVE_SEARCH_API_KEY=
#TWITTER_BEARER_TOKEN=
```

## 3. Database Backup & Restore

**Backup location:** `backups/db/trade_ai_YYYYMMDD.sql.gz`
**Size:** ~3.7 MB compressed (105 MB uncompressed, 143 tables)
**Schedule:** Daily at 2 AM, keeps 7 days

### Restore DB from backup:
```bash
gunzip < backups/db/trade_ai_20260429.sql.gz | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai
```

### Create fresh backup:
```bash
DB_PW=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
PGPASSWORD="$DB_PW" pg_dump -h localhost -U trade_ai trade_ai | gzip > backups/db/trade_ai_$(date +%Y%m%d).sql.gz
```

---

## 4. Cron Jobs (restore with `crontab /path/to/crontab_backup`)

Current crontab has ~46 entries. Key ones:
- `*/15 6-19 * * 1-5` — Agent processing (market hours)
- `*/5 20-23 * * 1-5` — Agent processing (overnight)
- `0 5 * * 1-5` — Alex daily scan
- `30 6 * * 1-5` — News ingestion (Yahoo + Finnhub + Google News)
- `0 19 * * 1-5` — YouTube transcript auto-discovery
- `0 20 * * 1-5` — Overnight batch + SEC Form 4 ingestion
- `0 21 * * 1-5` — Auto-research
- `30 9 * * 0` — Watchlist hygiene

Export: `crontab -l > crontab_backup.txt`

## 4. Systemd Services

| File | Purpose |
|---|---|
| `~/.config/systemd/user/tradeai-continuous.service` | Trade AI scalp runner (4-11 AM) |
| `~/.config/systemd/user/tradeai-continuous.timer` | Timer trigger |
| `~/.config/systemd/user/aegis-overnight.service` | Aegis overnight scan |
| `~/.config/systemd/user/aegis-surveillance.service` | Aegis morning surveillance |
| `~/.config/systemd/user/portfolio-daily.service` | Daily portfolio pipeline |
| `~/.config/systemd/user/recovery-watch.service` | Recovery watch daily |

Restore: `systemctl --user daemon-reload && systemctl --user enable --now tradeai-continuous.timer`

## 5. OpenClaw Configuration

| File | Purpose |
|---|---|
| `~/.openclaw/openclaw.json` | Gateway config, agent list, model defaults, memory settings |
| `~/.openclaw/agents/steph/agent/SOUL.md` | Steph personality + portfolio context |
| `~/.openclaw/agents/aegis/SOUL.md` | Aegis surveillance personality |
| `~/.openclaw/cron/jobs.json` | 3 OpenClaw cron jobs (evening scan, weekly alloc, monthly income) |
| `~/.openclaw/workspace-steph/` | Steph workspace |
| `~/.openclaw/workspace-aegis/` | Aegis workspace |

Key settings in openclaw.json:
- `memorySearch.enabled: true`
- `gateway.port: 18789`
- Models: ollama/qwen3:1.7b (primary) → openai/gpt-5.4-mini → anthropic/claude-sonnet-4-6

## 6. Database Tables (143)

Critical tables to verify after restore:
- `ticker_strategy_classifications` — 55 active symbols
- `watchlist_agent_results` — 198 agent analyses
- `agent_handoffs` — 110 handoffs, 32 escalations
- `news_articles` — 552 articles, 50 sources
- `youtube_transcripts` — 12 transcripts (cleaned + summarized)
- `personal_situation` — 18 keys (SSDI, MFS, Medicare, income targets)
- `personal_tax_history` — 2025 + 2026 tax years
- `tax_events` — conversions, dividends, trust transfers
- `cio_decisions` — 55 proposed
- `decision_outcomes` — 88 tracked
- `daily_system_metrics` — trending data
- `sec_form4` — 4 insider filings
- `market_quotes` — yfinance data
- `fundamental_data` — Alpha Vantage metrics

## 7. Key Scripts (dependencies)

| Script | What It Does | Key Dependencies |
|---|---|---|
| `content_scoring.py` | Unified scoring + tagging | None |
| `intel_query.py` | Agent intelligence query | content_scoring, sec_data_ingest, external_market_data_ingest |
| `agent_collab.py` | Cross-agent collaboration | None |
| `process_watchlist_agent_jobs.py` | Agent processing + synthesis | llm_router, content_scoring, intel_query, agent_collab |
| `alex_retirement_advisor.py` | Alex retirement analysis | intel_query, agent_collab, llm_router |
| `run_alex_daily.py` | Daily/weekly/monthly automation | alex_retirement_advisor, llm_router |
| `telegram_smart_alerts.py` | 6 proactive alert types | alex_retirement_advisor, telegram_alert |
| `news_ingestion.py` | Yahoo + Finnhub + Google News | content_scoring |
| `youtube_transcript_ingest.py` | YouTube video transcripts | content_scoring, youtube-transcript-api |
| `transcript_processor.py` | Clean + summarize + sub-tag | llm_router, content_scoring |
| `sec_data_ingest.py` | SEC EDGAR Form 4 | content_scoring |
| `external_market_data_ingest.py` | yfinance + Alpha Vantage + FRED | yfinance |
| `overnight_batch.py` | 8 PM metrics + stale refresh | process_watchlist_agent_jobs |
| `auto_research.py` | Conflict resolution research | llm_router, intel_query, web_research |
| `system_preflight_check.py` | 23-point health check | All of the above |

## 8. Preflight Check (run after any restore)

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
python3 scripts/system_preflight_check.py
```

Must pass 21+ of 23 checks. Known acceptable fail: portfolio-server (nohup, not systemd).

## 9. Launcher Scripts

| File | Purpose |
|---|---|
| `linux_launchers/run_continuous.sh` | Trade AI runner launcher (sources .env, runs preflight, starts runner) |

## 10. Config Files

| File | Purpose |
|---|---|
| `assets/screeners.yaml` | Finviz screener URLs (MUST use /export not /export.ashx) |
| `config/agents_sec_interaction.yaml` | Agent SEC data interaction rules |
| `config/agents_data_sources.yaml` | Agent data source rules (if exists) |

---

## 11. Backup File Locations (all in git repo)

```
~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/
├── .env                                    ← API keys, DB password, cookies (NOT in git — manual restore)
├── crontab_backup.txt                      ← Full crontab (restore: crontab crontab_backup.txt)
├── backups/
│   ├── db/
│   │   └── trade_ai_20260429.sql.gz        ← DB dump 3.7 MB (restore: gunzip | psql)
│   ├── openclaw/
│   │   ├── openclaw.json                   ← Gateway + agents + models config
│   │   ├── jobs.json                       ← 3 OpenClaw cron jobs
│   │   ├── steph_SOUL.md                   ← Steph personality
│   │   └── aegis_SOUL.md                   ← Aegis personality
│   └── systemd/
│       ├── tradeai-continuous.service      ← Trade AI runner service
│       └── tradeai-continuous.timer        ← Timer trigger
├── assets/
│   └── screeners.yaml                      ← Finviz screener URLs (MUST use /export)
├── config/
│   └── agents_sec_interaction.yaml         ← Agent SEC data rules
├── linux_launchers/
│   └── run_continuous.sh                   ← Runner launcher (sources .env, runs preflight)
├── scripts/
│   └── system_preflight_check.py           ← 23-point health check
└── docs/
    ├── RESTORE_GUIDE.md                    ← This file
    └── TRADE_AI_V12_SYSTEM_BIBLE_V2_33.md  ← Latest Bible
```

### What is NOT in git (must restore manually):
- `.env` file (API keys, passwords — keep a secure copy elsewhere)
- PostgreSQL data (restore from `backups/db/` dump)
- OpenClaw live configs (restore from `backups/openclaw/` to `~/.openclaw/`)
- Systemd services (restore from `backups/systemd/` to `~/.config/systemd/user/`)
- Crontab (restore: `crontab crontab_backup.txt`)

### Full Restore Sequence:
```bash
# 1. Clone repo
git clone <repo_url>
cd trade-ai-v12-rebuild/trade-ai-v12-rebuild

# 2. Restore .env (from your secure backup)
cp /path/to/secure/.env .env

# 3. Install Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # or pip install psycopg2 yfinance requests pyyaml youtube-transcript-api

# 4. Restore DB
DB_PW=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
gunzip < backups/db/trade_ai_20260429.sql.gz | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai

# 5. Restore crontab
crontab crontab_backup.txt

# 6. Restore OpenClaw
cp backups/openclaw/openclaw.json ~/.openclaw/
cp backups/openclaw/jobs.json ~/.openclaw/cron/
cp backups/openclaw/steph_SOUL.md ~/.openclaw/agents/steph/agent/SOUL.md
cp backups/openclaw/aegis_SOUL.md ~/.openclaw/agents/aegis/SOUL.md

# 7. Restore systemd
cp backups/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-continuous.timer

# 8. Start services
nohup .venv/bin/python scripts/portfolio_server.py &
openclaw gateway restart

# 9. Verify
python3 scripts/system_preflight_check.py
```
