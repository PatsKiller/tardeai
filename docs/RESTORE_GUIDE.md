# Trade AI v12 — Restore Guide

**If you need to rebuild the system from scratch, follow this guide.**

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

## 3. Cron Jobs (restore with `crontab /path/to/crontab_backup`)

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
