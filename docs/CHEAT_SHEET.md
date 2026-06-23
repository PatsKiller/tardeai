# Trade AI v12 -- Operator Cheat Sheet

**Last updated:** 2026-06-24
**Live counts:** `docs/LIVE_SYSTEM_FACTS.md` — `.venv/bin/python3 scripts/generate_system_facts.py`

---

## Health Checks

```bash
# Full system health (single command)
curl -s http://localhost:7777/api/v2/system-health | python3 -m json.tool

# Deep overnight queue status
curl -s http://localhost:7777/api/v2/queue/summary | python3 -m json.tool

# gemma3 calibration accuracy
curl -s http://localhost:7777/api/v2/queue/calibration | python3 -m json.tool

# Portfolio value assertion (must be > $1M)
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; assert v>1_000_000; print(f'OK: \${v:,.0f}')"

# Database health
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "SELECT COUNT(*) FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '24 hours';"

# Ollama / GPU status
curl -s http://localhost:11434/api/tags | python3 -c "import json,sys; print([m['name'] for m in json.load(sys.stdin)['models']])"

# Automated Trade Proposals status
curl -s http://localhost:7777/api/v2/paper-proposals | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Pending: {d.get(\"summary\",{}).get(\"pending\")}')"

# After-hours readiness
curl -s http://localhost:7777/api/v2/afterhours-readiness/summary | python3 -m json.tool

# Strategy-fit audit
curl -s http://localhost:7777/api/v2/strategy-fit/summary | python3 -m json.tool

# Lesson memory
curl -s http://localhost:7777/api/v2/journal/lesson-memory/summary | python3 -m json.tool

# Screener schedule
curl -s http://localhost:7777/api/v2/screener-schedule/summary | python3 -m json.tool

# Catalog lifecycle
curl -s http://localhost:7777/api/v2/ticker-catalog/summary | python3 -m json.tool
curl -s http://localhost:7777/api/v2/screener-membership/summary | python3 -m json.tool

# Journal action dashboard
curl -s http://localhost:7777/api/v2/journal/closed-trades/action-dashboard | python3 -m json.tool

# Pipeline health (44 stages)
curl -s http://localhost:7777/api/v2/pipeline-health-master | python3 -m json.tool

# Risk regime status
curl -s http://localhost:7777/api/v2/risk-regime/status | python3 -m json.tool

# Attribution alpha vs benchmark
curl -s http://localhost:7777/api/v2/attribution | python3 -c "import json,sys; d=json.load(sys.stdin).get('data',{}); print(f'Alpha: {d.get(\"alpha_annualized\")}% | Port CAGR: {d.get(\"port_cagr\")}% | Bench CAGR: {d.get(\"bench_cagr\")}%')"

# Agent queue health
.venv/bin/python scripts/run_agent_queue_health.py --verbose

# Verify paper mode (CRITICAL)
grep ALPACA_MODE .env     # Must show: paper
grep LIVE_TRADING .env    # Must show: false
```

---

## Real-Time Alert System (Telegram)

**Architecture:** Proposal alerts fire immediately on creation (inline hook). Replies detected
via long-poll daemon (1-2 sec). Stop proximity checks every 2 min. End-to-end latency: ~10 sec.

```bash
# ── Proposal Commands ──
/ptpending                          # List all PENDING proposals
/ptapprove 1234                     # Approve as proposed
/ptapprove 1234 shares=200          # Approve with share override
/ptapprove 1234 target=2.50 stop=2.08  # Approve with price overrides
/ptreject 1234 too volatile         # Reject with reason
/ptstatus 1234                      # Show proposal details

# Inline buttons on proposal alerts:
# [Approve] [Reject] [½× Shares] [2× Shares] [More Info]

# ── Stop Proximity Alert Buttons (on near-stop alerts) ──
# [🛑 Stop Out Now] [📉 Trail 5%]
# [📉 Trail 8%]     [⏸ Hold]
# Stop Out: immediately closes position at market + updates Alpaca
# Trail X%: switches to trailing stop X% below current price (stops only move UP)
# Hold: logs decision, continues monitoring

# ── Stop Decision Commands ──
/stopexit RTX                       # Honor stop, record EXIT
/stophold RTX                       # Override, record HOLD
/stopdelay RTX 30                   # Snooze alert 30 min
/stopset RTX stop=178.50            # Move stop to specific price
paper status                        # List pending proposals

# Alert throttling: 30-min cooldown per (proposal, alert_type), max 5 total
# Auto-expiry: TARGET_HIT_BEFORE_APPROVAL, OVER_ALERTED (5+ alerts, 2h+)
# Trailing stop moves send rich notification with locked profit amount

# Dedicated group: TRADEAI_PROPOSAL_ALERT_CHAT_ID in .env
# Fallback: standard TELEGRAM_CHAT_ID

# Dashboard URLs (Tailscale HTTPS — works from cellular):
# v2 Dashboard:  https://ms01-openclaw.tail163d14.ts.net/
# DOF Auctions:  https://ms01-openclaw.tail163d14.ts.net:8443/

# ── Telegram Daemon Status ──
pgrep -f 'run_telegram_callback_poller.py' || echo "NOT RUNNING"
# Manual start:
bash scripts/run_telegram_poller_daemon.sh &

# ── Trailing Stop Analysis ──
# Run for all closed trades (backfill):
.venv/bin/python scripts/trailing_stop_analyzer.py
# Results visible in Backtesting > Trail Analysis tab
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

# Run with pre-computed LLM-improved queries (from curator)
.venv/bin/python scripts/topic_ingestion.py --use-llm-queries

# Post-ingestion curation (rate quality, extract entities, improve queries, auto-ingest)
.venv/bin/python scripts/topic_curator.py --improve-queries

# Run sentiment scoring on unscored articles
.venv/bin/python scripts/sentiment_processor.py

# Run signal fusion (fuse catalyst + news + social + sentiment per symbol)
.venv/bin/python scripts/signal_fusion.py --full

# Run incubator promoter (promote qualifying candidates to proposals)
.venv/bin/python scripts/incubator_proposal_promoter.py --run

# Telegram commands
# topic status         — show all topics with gap status
# topic add SSDI trust — add new topic
# topic url <id> <url> — add saved Google search URL
# topic run ssdi       — run ingestion for one topic
# topic run all        — run all topics
# run promoter         — retry incubator promoter
# run promoter dry     — dry-run promoter
# status               — full system health check
```

## YouTube & Article Ingestion

```bash
# Add a single video
.venv/bin/python scripts/youtube_transcript_ingest.py --ingest "https://www.youtube.com/watch?v=VIDEO_ID"

# Import a channel (add to tracking + ingest recent videos)
.venv/bin/python scripts/youtube_transcript_ingest.py --import-channel "https://www.youtube.com/@handle" --strategy retirement_planning

# Ingest latest from all tracked channels
.venv/bin/python scripts/youtube_transcript_ingest.py --all-channels

# Backfill a channel (~50 videos, ~12 months)
.venv/bin/python scripts/youtube_transcript_ingest.py --backfill --max 50

# CLI: add videos or articles (same as Telegram)
.venv/bin/python scripts/telegram_command_handler.py --process "add video URL1 URL2"
.venv/bin/python scripts/telegram_command_handler.py --process "add article URL1 URL2"

# Telegram / OpenClaw (just paste URLs directly):
# add video URL1 URL2    — ingest YouTube videos + add channels
# add article URL1 URL2  — ingest article URLs
# (bare URLs auto-detect: YouTube → video, other → article)

# Check ingest queue (videos waiting for IP block to clear)
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "SELECT video_id, title, status FROM youtube_ingest_queue ORDER BY queued_at;"

# List tracked channels
PGPASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "SELECT channel_name, strategy_focus, last_checked FROM youtube_channels ORDER BY channel_name;"
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
| `.env` | All secrets, API keys, LLM config, feature flags. Values with `( ) ;` must be single-quoted |
| `.env.example` | Template with documented variables |
| `config/strategies/*.yaml` | 24 strategy definitions (dynamically loaded) |
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
| Every 2h (9-17) | Proposal promoter | `incubator_proposal_promoter.py` | Auto-expires stale, promotes new. Check `paper_trade_proposals` |
| 8:00 PM | Overnight batch | `overnight_batch.py` | Check overnight log |
| Sun 7 PM | Weekly incubator build | `weekly_incubator_builder.py` | Check incubator universe count |
| Sun 10 PM | LLM classification | `weekly_incubator_builder.py --llm` | Check strategy assignments |

---

## Common Failures & Resolution

| Failure | Symptom | Fix |
|---------|---------|-----|
| **Finviz cookie expired** | Screener returns 0 results | Manual browser login to Finviz Elite, update cookie in `.env`. **Wrap in single quotes** — value contains `( ) ;` characters |
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
| **Database size** | Growing — see `database.table_count` in LIVE_SYSTEM_FACTS | Managed DB storage costs |
| **GPU compute** | Fixed (Intel Arc B50) | GPU instance pricing ($0.50-2.00/hr) |
| **Log retention** | 7-day rolling | CloudWatch/Azure Monitor ingestion fees |

---

## Session 33 Quick Refs

```bash
# Restore strategy YAMLs from backup
cp backups/strategy_yaml_20260513_183104/*.yaml config/strategies/

# Re-run YAML validator
.venv/bin/python scripts/validate_strategy_yamls.py --config-dir config/strategies --md

# Re-run performance context refresh manually
.venv/bin/python scripts/populate_performance_context.py --apply

# Verify all required blocks present
grep -l 'vix_rules:' config/strategies/*.yaml | wc -l           # expect 23
grep -l 'technical_indicators_required:' config/strategies/*.yaml | wc -l  # expect 23
grep -l 'performance_context:' config/strategies/*.yaml | wc -l # expect 25
```

---

## Data Gap Resolver

```bash
# Check current gap registry
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) \
psql -h localhost -U trade_ai -d trade_ai -c "
SELECT gap_type, status, COUNT(*), array_agg(DISTINCT symbol) as symbols
FROM data_gap_registry WHERE detected_at > NOW() - INTERVAL '24 hours'
GROUP BY gap_type, status ORDER BY 1,2;"

# Run resolver manually
python3 scripts/data_gap_resolver.py

# Pre-overnight sweep (force close gaps before 23:00 window)
python3 scripts/data_gap_resolver.py --pre-overnight

# Weekly audit (persistent unresolvable gaps)
python3 scripts/data_gap_resolver.py --weekly-audit

# View resolver log
tail -50 logs/data_gap_resolver.log

# Verify cron scheduled (expect 3 entries)
crontab -l | grep data_gap_resolver

# Deep overnight health check
.venv/bin/python scripts/check_deep_overnight_health.py --summary

# Queue status report
.venv/bin/python scripts/report_deep_overnight_queue_status.py --summary
```

---

## Alert Dispatcher

```bash
# Check dispatch volume last 24h
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) \
psql -h localhost -U trade_ai -d trade_ai -c "
SELECT action_taken, COUNT(*) FROM alert_dispatch_log
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1 ORDER BY 2 DESC;"

# See suppressed alerts
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) \
psql -h localhost -U trade_ai -d trade_ai -c "
SELECT alert_type, symbol, COUNT(*) FROM alert_dispatch_log
WHERE action_taken IN ('suppressed_dedup','dashboard_only')
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10;"

# Send digest manually
python3 scripts/send_alert_digest.py morning
python3 scripts/send_alert_digest.py evening

# View dashboard
# http://192.168.50.16:7777/v2/alerts
```

---

## Paper Proposals

**Two execution paths** (same queue until you choose):

| Path | Where | Method |
|------|-------|--------|
| **A — Paper auto (test)** | Proposals → **Approve** | Alpaca bracket, no 2FA |
| **B — Live** | Proposals → **Promote to Broker** → **Broker Proposals** | Schwab API+2FA or **Fidelity Active Trader (FA)** manual + log fill |

Full doc: `docs/PROPOSAL_EXECUTION_PATHS.md`

```bash
# View pending proposals (JSON)
curl -s http://localhost:7777/api/v2/paper-proposals | python3 -m json.tool | head -50

# Strategy fit audit (why was this strategy assigned?)
.venv/bin/python scripts/report_proposal_strategy_fit_audit.py --verbose

# Technical/backtest evidence audit
.venv/bin/python scripts/report_proposal_technical_backtest_audit.py --verbose

# Quote trust check (which proposals have execution-eligible quotes?)
# Shown in trust_audit.quote_trust in the API response

# Pipeline run health
curl -s http://localhost:7777/api/v2/pipeline-run-health | python3 -m json.tool

# Auto-proposal diagnostics
curl -s http://localhost:7777/api/v2/auto-proposal-diagnostics | python3 -m json.tool

# Enrich all proposals (fills missing data gaps)
curl -s -X POST http://localhost:7777/api/v2/paper-proposals/enrich-all | python3 -m json.tool

# Promote from incubator
curl -s -X POST http://localhost:7777/api/v2/paper-proposals/promote-from-incubator | python3 -m json.tool
```

---

## Broker Proposals (Path B — live desk)

UI guide: `docs/BROKER_PROPOSALS_UI.md`

| Step | Action |
|------|--------|
| Account | Pick Schwab (auto+2FA or manual) or Fidelity (FA manual) |
| Thesis | Check **thesis validity bar** (drift gap / R:R band) |
| Prices | **↻ Refresh prices** on card or **Refresh all** |
| Oversight | **Run Grok+ChatGPT** + local agent reviews |
| Execute | Auto route (Schwab) or **Executed manually** after FA fill |

```bash
# Live broker queue
curl -s http://localhost:7777/api/v2/broker-proposals | python3 -m json.tool | head -40

# Refresh quote + thesis band + sizing for proposal #ID
curl -s -X POST http://localhost:7777/api/v2/broker-proposals/refresh-prices \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id": 123}' | python3 -m json.tool

# Grok+ChatGPT cloud oversight
curl -s -X POST http://localhost:7777/api/v2/broker-proposals/run-cloud-oversight \
  -H 'Content-Type: application/json' \
  -d '{"proposal_id": 123, "timeout": 120}' | python3 -m json.tool

# Log manual fill (closed-loop journal)
curl -s -X POST http://localhost:7777/api/v2/executions/log-manual \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","account":"fidelity_rollover_ira","proposal_id":123,"shares":10,"entry_price":150}' \
  | python3 -m json.tool
```

---

## Strategy Intelligence (SP-2)

```bash
# Watch horizon — candidate maturity per strategy
.venv/bin/python scripts/report_strategy_watch_horizon.py --verbose --since-days 30

# Finviz screener quality audit
.venv/bin/python scripts/report_finviz_screener_quality.py --verbose --since-days 30

# Strategy assignment engine audit (route evidence, YAML/DB sync)
.venv/bin/python scripts/report_strategy_assignment_engine_audit.py --verbose --since-days 30

# Route audit root cause
.venv/bin/python scripts/report_route_audit_root_cause.py --verbose --since-days 30

# Route audit backfill (dry-run first!)
.venv/bin/python scripts/backfill_proposal_route_audit.py --dry-run --verbose --since-days 30
# .venv/bin/python scripts/backfill_proposal_route_audit.py --apply --verbose  # operator approval required

# Invalid strategy assignments
.venv/bin/python scripts/report_invalid_strategy_assignments.py --verbose --since-days 30

# YAML/DB config drift
.venv/bin/python scripts/report_strategy_config_drift.py --verbose
```

---

## Operator Reports (PAR-1)

```bash
# Morning packet — consolidated daily status
.venv/bin/python scripts/report_operator_morning_packet.py --verbose

# Quote freshness audit
.venv/bin/python scripts/report_quote_freshness_provider_audit.py --verbose --since-days 30

# Route mismatch review (human-review-only)
.venv/bin/python scripts/report_route_mismatch_human_review.py --verbose --since-days 30

# Source attribution audit
.venv/bin/python scripts/report_proposal_source_attribution.py --verbose --since-days 30

# Watchlist BUY+ → broker proposals bridge
.venv/bin/python scripts/watchlist_proposal_bridge.py --dry-run
.venv/bin/python scripts/watchlist_proposal_bridge.py --apply --max-new 40

# Broker queue hygiene (stale Schwab/Fidelity rows)
.venv/bin/python scripts/broker_queue_hygiene.py --audit --days 7
.venv/bin/python scripts/broker_queue_hygiene.py --sweep --apply

# Bucket 2 watchpool status
.venv/bin/python scripts/report_bucket2_watchpool_status.py --verbose

# Canonical regression runner
scripts/run_tradeai_regression.sh --quick    # 10 suites
scripts/run_tradeai_regression.sh --full     # all suites + BR-2A
scripts/run_tradeai_regression.sh --frontend # includes frontend build
```

---

## Governance & Maturity

```bash
# Operator readiness summary (daily at 08:00 M-F, 18:20 Sun)
.venv/bin/python scripts/report_operator_readiness_summary.py --verbose

# Maturity control board (daily at 07:55 M-F, 18:15 Sun)
bash scripts/run_scheduled_maturity_control_board.sh

# Governance status (GOV-1: 07:50 M-F, 18:10 Sun)
.venv/bin/python scripts/report_governance_status.py --verbose

# Phase readiness gates
.venv/bin/python scripts/report_phase_readiness_gates.py --verbose

# A1A compliance check
.venv/bin/python scripts/check_a1a_compliance.py --verbose

# Strategy evidence funnel
.venv/bin/python scripts/report_strategy_evidence_funnel.py --verbose

# A-5 observation readiness
.venv/bin/python scripts/report_a5_strategy_readiness.py --verbose

# Check scheduled cron
crontab -l | sed -n '/BEGIN GOV-1/,/END GOV-1/p'
crontab -l | sed -n '/BEGIN Phase 9C/,/END Phase 9C/p'

# Rollback (if needed)
scripts/rollback_gov1_governance_cron.sh --status
scripts/rollback_phase9c_maturity_cron.sh --status
```
