# Trade AI v12 — Agent Roster

> **⚠️ Model policy (validated 2026-06-02):** gemma3:12b = primary chat, gemma3:4b = fallback, gemma3:27b = overnight; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** Any reference below to qwen3:14b as an active chat/generation model is superseded — see `MASTER_SYSTEM_DOCUMENTATION.md` §12.


Generated: 2026-05-24 | All agents documented with identity, role, model, and scheduling.

## Agent Summary

| Agent | Display | Role | Model | Platform | Schedule |
|-------|---------|------|-------|----------|----------|
| Maria | 🔬 Maria | Research analyst / catalyst verification | qwen3:14b (local) | Trade AI LLM | */10-15 via agent job worker |
| Maria Research | 🔬 Maria Research | Deep research / two-pass RAG analysis | qwen3:14b (local) | Trade AI LLM | */10-15 via agent job worker |
| Steph | 📊 Steph | Income guardian / allocation strategist | qwen3:14b (local) | Trade AI LLM | */10-15 via agent job worker |
| Risk Agent | 🛡️ Risk | Risk management / stop coverage / portfolio heat | qwen3:14b (local) | Trade AI LLM | */10-15 via agent job worker |
| Tax Agent | 💰 Tax | Tax optimization / Roth conversion / harvest | qwen3:14b (local) | Trade AI LLM | */10-15 via agent job worker |
| Alex | 👔 Alex | CIO / escalation arbiter / strategic oversight | qwen3:14b (local) | Trade AI LLM + OpenClaw | Daily 5 AM + hygiene 7:15 AM |
| Aegis | 🏛️ Aegis | Portfolio surveillance / overnight analysis | qwen3:14b (local) | Trade AI LLM + OpenClaw | Overnight 8 PM + surveillance 8 AM + social 11/3 PM + nightly 7 PM + synthesis 9 PM + transcript 9 AM + brief 8:05 AM |
| Iris | 📚 Iris | Intelligence librarian / RAG coverage / taxonomy | qwen3:14b (local) | Trade AI LLM + OpenClaw | Weekly Sun 10 AM + daily gap 7 AM |
| Social Scalp | 📡 Social Scalp | Social mention scanner / GO-WAIT-AVOID | qwen3:14b (local) | Trade AI LLM | Part of scalp pipeline |
| Scalp Critic | 🎯 Scalp Critic | Post-scan critic / catalyst validation | qwen3:14b (local) | Trade AI LLM | Part of scalp pipeline |

## Agent Detail

### Maria (Research Analyst)
- **Identity:** Research analyst specializing in catalyst verification and news analysis
- **Model:** qwen3:14b on Intel Arc B50 GPU (local Ollama)
- **Platform:** Trade AI internal LLM pipeline
- **Tasks:** Full analysis of watchlist symbols, news sentiment, catalyst detection
- **Output tables:** watchlist_agent_results, watchlist_agent_jobs
- **RACI:** R (Responsible) for daily watchlist batch, CIO analysis
- **Scripts:** process_watchlist_agent_jobs.py (agent=maria)

### Steph (Income Guardian)
- **Identity:** Allocation strategist focused on income, dividends, and account fit
- **Model:** qwen3:14b (local)
- **Platform:** Trade AI internal LLM pipeline
- **Tasks:** Income impact analysis, account allocation review, dividend strategy
- **Output tables:** watchlist_agent_results
- **RACI:** R for daily watchlist batch, C for overnight surveillance
- **Scripts:** process_watchlist_agent_jobs.py (agent=steph)

### Risk Agent
- **Identity:** Risk management agent monitoring stops, portfolio heat, and position sizing
- **Model:** qwen3:14b (local)
- **Platform:** Trade AI internal LLM pipeline
- **Tasks:** Stop coverage, risk gate validation, portfolio heat monitoring
- **Output tables:** watchlist_agent_results, risk_gate evaluations
- **RACI:** R for daily watchlist batch, C for overnight surveillance
- **Scripts:** process_watchlist_agent_jobs.py (agent=risk_agent), risk_gate.py

### Tax Agent
- **Identity:** Tax optimization agent for Roth conversion, loss harvesting, and IRMAA
- **Model:** qwen3:14b (local)
- **Platform:** Trade AI internal LLM pipeline
- **Tasks:** Tax-loss harvest identification, account type classification, wash-sale detection
- **Output tables:** watchlist_agent_results
- **RACI:** C for daily watchlist batch
- **Scripts:** process_watchlist_agent_jobs.py (agent=tax_agent)

### Alex (CIO)
- **Identity:** Chief Investment Officer — escalation arbiter and strategic oversight
- **Model:** qwen3:14b (local)
- **Platform:** Trade AI LLM + OpenClaw (Telegram/WhatsApp interface)
- **Tasks:** CIO decisions, retirement planning, strategic portfolio review, escalation handling
- **Output tables:** cio_decisions, alert_events
- **RACI:** R for Alex daily scan, portfolio governance, retirement/IRMAA review
- **Cron:** run_alex_daily.py (5 AM, 7 AM, 4 PM), alex_hygiene.py (7:15 AM)
- **OpenClaw:** ~/.openclaw/agents/alex/

### Aegis (Portfolio Surveillance)
- **Identity:** Portfolio surveillance agent — overnight analysis, morning briefs, covered calls
- **Model:** qwen3:14b (local)
- **Platform:** Trade AI LLM + OpenClaw (Telegram delivery)
- **Tasks:** Overnight surveillance, portfolio briefs, social sentiment, transcript discovery, synthesis
- **Output tables:** aegis_portfolio_briefs
- **RACI:** R for overnight surveillance, morning brief delivery
- **Cron:** aegis_overnight (8 PM), aegis_surveillance (8 AM), aegis_social_sentiment (11/3 PM), aegis_transcript_discovery (9 AM), aegis_synthesis (9 PM), aegis_nightly_ingestion (7 PM), aegis_morning_brief_delivery (8:05 AM)
- **OpenClaw:** ~/.openclaw/agents/aegis/

### Iris (Intelligence Librarian)
- **Identity:** Taxonomy intelligence agent — content coverage, channel curation, RAG hygiene
- **Model:** qwen3:14b (local)
- **Platform:** Trade AI LLM + OpenClaw
- **Tasks:** Gap analysis, channel discovery proposals, content quality monitoring, stale content removal
- **Output tables:** iris_run_log, iris_proposals
- **Coverage:** 69% (critical gaps: tax_strategy, etf_indexing)
- **Cron:** iris_taxonomy_agent.py (weekly Sun 10 AM full scan, daily 7 AM gaps)
- **OpenClaw:** ~/.openclaw/agents/iris/

## OpenClaw Agents
OpenClaw provides the Telegram/WhatsApp interface layer for agent interaction.

| Agent | OpenClaw Dir | Interface |
|-------|-------------|-----------|
| Alex | ~/.openclaw/agents/alex/ | Telegram + WhatsApp |
| Aegis | ~/.openclaw/agents/aegis/ | Telegram (brief delivery) |
| Iris | ~/.openclaw/agents/iris/ | Telegram (proposals) |
| Maria | ~/.openclaw/agents/maria/ | **Telegram DMs (bound)** — portfolio, watchlist, concierge |
| Steph | ~/.openclaw/agents/steph/ | Telegram (allocation) |
| Main | ~/.openclaw/agents/main/ | Fallback agent (not Telegram DM handler) |

## LLM Configuration
- **Primary model:** qwen3:14b on Intel Arc B50 GPU (Vulkan, 41/41 layers offloaded)
- **Ollama URL:** http://localhost:11434
- **Fallback:** gemma3:4b (light tasks), gemma3:27b (overnight deep analysis)
- **External:** Claude Sonnet 4 (escalation only, via API), Grok (demoted to fallback)
- **Budget:** Brave Search 25/day, 850/month with per-caller caps
