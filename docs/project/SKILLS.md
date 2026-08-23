# Trade AI v12 — Skills & Agent Capabilities Reference
**Last updated:** 2026-08-22 (local-generation retirement)

---

## Agent Roster

### Conversational Agents (OpenClaw Gateway :18789)

| Agent | Role | LLM Config | Key Capabilities |
|-------|------|------------|------------------|
| **Maria** | Risk assessment & primary analyst | governed cloud only | Position sizing, portfolio impact, exposure analysis, correlation checks, 2-pass analysis (sentiment + fundamentals) |
| **Steph** | Technical analysis & wealth advisory | governed cloud only | Entry/exit timing, chart patterns, indicator confluence, income strategy, allocation review |
| **Alex** | Income & retirement strategy | governed cloud only | Roth conversion planning, SSDI/IRMAA impact, dividend analysis, covered call evaluation, monthly research |
| **Aegis** | Synthesis & surveillance | governed cloud only | Morning briefs, overnight synthesis, cross-agent coordination, event intelligence |
| **Risk Agent** | Portfolio risk monitoring | deterministic/governed cloud | Stop coverage, heat monitoring, concentration alerts, risk gate evaluation |
| **Tax Agent** | Tax optimization | deterministic/governed cloud | Tax-loss harvesting, lot selection, bracket analysis, IRMAA threshold monitoring |

> **Policy:** OpenClaw and Trade AI production may not use local generation. Host
> OpenClaw references discovered on 2026-08-22 are removal prerequisites, not
> available capabilities. Do not install or substitute another local chat model.

### Backend Automation Agents

| Agent | Role | Trigger |
|-------|------|---------|
| **Iris** | Content hygiene — quality gating, stale detection, duplicate removal | Scheduled + event-driven |
| **Scalp Critic** | LLM critique of incubator candidates before promotion (A-F grading) | 8:10 AM + 6:00 PM |

---

## OpenClaw Skills (14 skills in 7 groups)

Located in `~/.openclaw/skills/`

### email-calendar (3 skills)
- **email-compose** — Draft and send emails via gog/Gmail
- **calendar-query** — Check Google Calendar availability
- **calendar-create** — Create calendar events

### integrations (2 skills)
- **github** — GitHub issue/PR management
- **gog** — Gmail CLI operations (send, read, search)

### light-research (3 skills)
- **web-search** — Web research via Brave/DuckDuckGo
- **news-lookup** — Financial news search
- **ticker-research** — Symbol-specific research aggregation

### operations (1 skill)
- **tradeai-safe-ops** — Pipeline operations (run screener, check health, trigger enrichment)

### personal-productivity (3 skills)
- **note-taking** — Capture notes and reminders
- **task-management** — Task tracking
- **daily-summary** — Daily activity summary

### steph-wealth-advisor (1 skill)
- **wealth-advisor** — Steph's wealth advisory skill (96 lines, portfolio analysis, income strategy)

### Telegram Commands (via telegram_command_handler.py)
- `status` — Full system health check
- `run promoter` / `run promoter dry` — Retry incubator promoter
- `run screener <name>` — Retry a screener
- `topic status` / `topic add` / `topic url` / `topic run` — Topic management
- `add video <url>` — Add YouTube video for ingestion
- `add article <url>` — Add news article for ingestion

---

## System Skills (Automated Pipelines)

### Discovery & Scoring
| Skill | Script | Schedule |
|-------|--------|----------|
| Finviz screener | `finviz_screener_runner.py` | 10 AM + 4 PM weekdays |
| Social scalp scanner | `social_scalp_scanner.py` | 6 AM - 4 PM every 30 min |
| Pre-market watcher | `premarket_watcher.py` | 5:30 - 9:30 AM every 15 min |
| Trade AI scoring | `trade_ai_orchestrator.py` | Continuous runner |
| Incubator LLM screening | `incubator_llm_screener.py` | 8:10 AM + 6 PM |

### Execution & Position Management
| Skill | Script | Schedule |
|-------|--------|----------|
| Instant paper execution | `api_v2.py` → `proposal_paper_submitter.py` | On approval (instant) |
| Execution sweep (safety net) | `paper_execution_sweep.py` | Every 5 min market hours |
| Position monitor (trailing stops) | `paper_trade_monitor.py` | Every 5 min market hours |
| Smart order selection | `alpaca_paper_adapter.py` | On submission |

### Intelligence & Enrichment
| Skill | Script | Schedule |
|-------|--------|----------|
| LLM intelligence (5 sections) | `llm_intelligence_enrichment.py` | 7:20 AM daily |
| News ingestion (7 sources) | `news_ingestion.py` | 6:30 AM + 12:30 PM |
| Social ingestion | `social_ingest.py` | 6:30 AM + 12:35 PM |
| Topic curation (LLM-powered) | `topic_curator.py` | 7:00 AM daily |
| RAG indexing (11 sources incl. research) | `rag_indexer.py` | 4x daily |
| Research topic iteration | `iterate_research_topics.py` | Daily (overnight batch) |
| Sentiment processing | `sentiment_processor.py` | 7:00 AM + 12:00 PM |

### Research Advisory Pipeline
| Step | Detail |
|------|--------|
| **Source** | `user_research_topics` table — persistent topics created via Telegram `research <topic>` |
| **Iteration** | `iterate_research_topics.py` runs daily, calls LLM with prior findings as context |
| **Storage** | `latest_findings` column (text), `portfolio_intelligence_events` (audit) |
| **RAG Index** | Indexed as `research_finding` source type in `content_embeddings` (boost: 1.25×) |
| **Agent Injection** | Directly injected into agent prompts as "Active Research Advisories" block |
| **Morning Brief** | Top 3 findings surfaced as "RESEARCH ADVISORIES" section (priority 6) |
| **Command Center** | `Intelligence > Research Topics` page (`/v2/research-topics`) |
| **Telegram** | Iterations posted to user on completion |
| **Email** | Included in daily digest via GOG Gmail |

### Monitoring & Alerting
| Skill | Script | Schedule |
|-------|--------|----------|
| Central alert dispatcher | `alert_dispatcher.py` | On event (dedup, fatigue, tiers) |
| Missing condition alerts | `alert_missing_conditions.py` | 7:30 AM daily |
| Morning brief delivery | `aegis_morning_brief_delivery.py` | 8:00 AM daily |
| Recovery watch | `recovery_watch_daily.py` | After portfolio pipeline |
| Pipeline watchdog | `pipeline_watchdog.py` | Every 5 min |

### Learning & Feedback
| Skill | Script | Schedule |
|-------|--------|----------|
| Agent outcome scoring | `agent_outcome_scorer.py` | 5:30 AM daily |
| Agent calibration | `agent_calibration_engine.py` | On demand |
| Feedback loop processor | `feedback_loop_processor.py` | 8:30 PM daily |
| Weekly learning digest | `weekly_learning_digest.py` | Sunday 7:45 AM |
| Weekly DOCX report | `generate_weekly_docx.py` | Sunday 9:00 PM |
| Backup verification | `backup_verify.py` | 1st of month |

---

## Inference Layers (Higher-Order Reasoning Skill)

A reusable, layered reasoning pipeline on top of every other skill/agent here.
Each layer is an importable module any agent (Maria/Steph/Alex/Aegis/Risk) can call.
Advisory-only. Full design: `docs/project/INFERENCE_LAYERS.md`.

| Layer | Module | Capability |
|-------|--------|------------|
| L1 Ingestion | `inference_layers.IngestionLayer` | structure news/topics/positions/proposals/journal; region-tag news |
| L2 Features | `inference_layers.FeatureLayer` | regime (risk_on/off/high_vol), sentiment, VIX, concentration |
| L3 Regional | `inference_layers.RegionalLayer` | Asia/Europe/EM → US ETF/CEF transmission (e.g. PTY) |
| L4 Higher-order | `inference_layers.HigherOrderLayer` | journal patterns, NAV premium/discount, opportunity/risk, **risk-appropriate sizing**, proactive Hermes queries |

- Substrate: `inference_hermes_query` (governed cloud provider, no local fallback,
  RAG injection, `proactive_query` autonomy). Reuses `account_policy.compute_sizing`
  + `risk_gate` (sizing never escapes the risk envelope), `journal_analytics_engine`,
  `rag_retrieval`, `telegram_alert`.
- Run: `python scripts/inference_layer_engine.py --run`; cron
  `linux_launchers/run_inference_cycle.sh`. API: `/api/v2/inference/*`.

---

## LLM Routing

```
Request arrives
    ↓
governed cloud routing and provider-cost gate
    ↓ (provider failure)
hard labeled failure; no local fallback
```

**Model policy (2026-08-22):** zero local generative paths. Math is deterministic.
The only candidate local model is pinned `nomic-embed-text` for the existing
`content_embeddings` store, subject to embedding acceptance. Runtime flags cannot
restore local judgment.

---

## Global Agent Rules (G1-G10)

1. **G1** — Never execute live trades without explicit 6-month paper validation
2. **G2** — Income protection: SSDI awareness in all recommendations
3. **G3** — IRMAA threshold consciousness in Roth conversion planning
4. **G4** — Confidence gating: low-confidence recommendations flagged, not promoted
5. **G5** — Portfolio heat limit: 5% max, alerts above threshold
6. **G6** — Single-stock concentration: 15% max per symbol
7. **G7** — Stop-loss discipline: all positions must have stops
8. **G8** — Paper-only mode: no live broker modifications
9. **G9** — Audit trail: all decisions logged to DB
10. **G10** — Human approval required for config changes (no auto-promotion)
