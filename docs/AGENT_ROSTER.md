# Trade AI v12 — Agent Roster

> **⚠️ Model policy (validated 2026-08-09):** DeepSeek V4 Pro = primary CIO/synthesis; DeepSeek V4 Flash = routine agents; gemma3:12b = local chat primary; gemma3:4b = local fallback; gemma3:27b = overnight deep; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** All agent model references below have been updated. See `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` and `docs/v4_1_deployment_log.md`.


**Generated:** 2026-05-24 | **Updated:** 2026-08-09 (model policy, CIO Phase 3, Wealth Advisor, Wave-3 agent_runtime)
**Related:** `docs/architecture/cio/` (38 CIO architecture docs) · `docs/wealth-advisor/STEPH_WEALTH_ADVISOR.md` · `docs/agent_runtime/FLEET_STATUS_2026-07-30.md`

## Agent Summary

| Agent | Display | Role | Model | Platform | Schedule | Authority |
|-------|---------|------|-------|----------|----------|-----------|
| Maria | 🔬 Maria | Research analyst / catalyst verification | gemma3:12b (local) | Trade AI LLM | */10-15 via agent job worker | advisory |
| Maria Research | 🔬 Maria Research | Deep research / two-pass RAG analysis | gemma3:12b (local) | Trade AI LLM | */10-15 via agent job worker | advisory |
| Steph | 📊 Steph | Wealth & Income Advisor | DeepSeek V4 Flash → Pro | OpenClaw + Trade AI Wave-3 | OpenClaw cron: weekly Sun 9am + monthly 1st 9am | READ_ONLY_ADVISORY |
| Risk Agent | 🛡️ Risk | Risk management / stop coverage / portfolio heat | gemma3:12b (local) | Trade AI LLM | */10-15 via agent job worker | advisory |
| Tax Agent (Ledger) | 💰 Tax | Tax optimization / Roth conversion / harvest | gemma3:12b (local) | Trade AI LLM + Wave-3 | */10-15 via agent job worker | advisory |
| Alex | 👔 Alex | Chief Investment & Wealth Officer | DeepSeek V4 Pro (PRO) / V4 Flash (FAST) | OpenClaw + Trade AI Wave-3 (SHADOW) | 30-min heartbeat + 5-min wake worker + scheduled briefs | READ_ONLY_ADVISORY |
| Aegis | 🏛️ Aegis | Portfolio surveillance / overnight analysis | gemma3:27b (overnight) | Trade AI LLM + OpenClaw | Overnight 8 PM + surveillance 8 AM + social 11/3 PM + nightly 7 PM + synthesis 9 PM + transcript 9 AM + brief 8:05 AM | advisory |
| Iris | 📚 Iris | Intelligence librarian / RAG coverage / taxonomy | gemma3:12b (local) | Trade AI LLM + OpenClaw | Weekly Sun 10 AM + daily gap 7 AM | advisory |
| Morgan | 🏦 Morgan | Senior Wealth Advisor — total financial life planning | Ollama gemma3:12b | Trade AI Wave-3 + OpenClaw | CIO scheduled briefs + material changes + behavioral flags | READ_ONLY_ADVISORY (SHADOW) |
| Social Scalp | 📡 Social Scalp | Social mention scanner / GO-WAIT-AVOID | gemma3:12b (local) | Trade AI LLM | Part of scalp pipeline | advisory |
| Scalp Critic | 🎯 Scalp Critic | Post-scan critic / catalyst validation | gemma3:12b (local) | Trade AI LLM | Part of scalp pipeline | advisory |

## Agent Detail

### Maria (Research Analyst)
- **Identity:** Research analyst specializing in catalyst verification and news analysis
- **Model:** gemma3:12b on Intel Arc B50 GPU (local Ollama)
- **Platform:** Trade AI internal LLM pipeline
- **Tasks:** Full analysis of watchlist symbols, news sentiment, catalyst detection
- **Output tables:** watchlist_agent_results, watchlist_agent_jobs
- **RACI:** R (Responsible) for daily watchlist batch, CIO analysis
- **Scripts:** process_watchlist_agent_jobs.py (agent=maria)

### Steph (Wealth & Income Advisor)
- **Identity:** Direct practical financial and wealth advisor — separate from Maria, shared-channel explicit routing
- **Model:** DeepSeek V4 Flash (FAST) → V4 Pro (complex); fallback: deepseek-chat → gpt-5.4
- **Platform:** OpenClaw (primary dialogue) + Trade AI Wave-3 agent_runtime (SHADOW, DISABLED pending CIO maturity)
- **Tasks:** Portfolio snapshot, ticker/sector performance, portfolio vs benchmark, Roth conversion headroom, concentration risk, rebalancing, analyst/technical summaries, watchlist summary
- **OpenClaw workspace:** `~/.openclaw/workspace-steph/` · agent: `~/.openclaw/agents/steph/`
- **Skills:** `steph-wealth-advisor` (primary) · `daily-portfolio-brief` ("steph, brief me")
- **Cron (OpenClaw):** `steph-weekly-allocation-review` (Sun 9am ET) · `steph-income-progress` (1st of month 9am ET)
- **Trade AI Wave-3:** `scripts/agent_runtime/agents/definitions.py` — id `steph`, "Senior Portfolio Advisor", denied: trade.authorize, rebalance.execute, broker.*
- **Data priority:** local portfolio JSON → PostgreSQL → Finviz → Yahoo → free APIs → external LLM (permission required)
- **Validation toolkit:** `~/.openclaw/skills/wealth/steph-wealth-advisor/scripts/` (cache audit)
- **Docs:** `docs/wealth-advisor/STEPH_WEALTH_ADVISOR.md`

### Risk Agent
- **Identity:** Risk management agent monitoring stops, portfolio heat, and position sizing
- **Model:** gemma3:12b (local)
- **Platform:** Trade AI internal LLM pipeline
- **Tasks:** Stop coverage, risk gate validation, portfolio heat monitoring
- **Output tables:** watchlist_agent_results, risk_gate evaluations
- **RACI:** R for daily watchlist batch, C for overnight surveillance
- **Scripts:** process_watchlist_agent_jobs.py (agent=risk_agent), risk_gate.py

### Tax Agent (Ledger)
- **Identity:** Tax optimization agent for Roth conversion, loss harvesting, and IRMAA
- **Model:** gemma3:12b (local)
- **Platform:** Trade AI internal LLM pipeline + Wave-3 agent_runtime (SHADOW, DISABLED)
- **Tasks:** Tax-loss harvest identification, account type classification, wash-sale detection
- **Output tables:** watchlist_agent_results
- **RACI:** C for daily watchlist batch
- **Scripts:** process_watchlist_agent_jobs.py (agent=tax_agent)
- **Wave-3:** `scripts/agent_runtime/agents/definitions.py` — id `ledger`, "Tax Optimization & Lot Selection", DISABLED pending CIO maturity

### Alex (Chief Investment & Wealth Officer)
- **Identity:** Chief Investment & Wealth Officer — autonomous advisory synthesis, escalation arbiter, strategic oversight
- **Model:** DeepSeek V4 Pro (PRO) for CIO synthesis/complex escalation; DeepSeek V4 Flash (FAST) for routine; secondary: ChatGPT/gpt-5.4 (free OAuth lane, material disagreement only)
- **Platform:** HYBRID — OpenClaw (agent identity, Telegram dialogue, delegation contracts) + Trade AI Wave-3 agent_runtime (SHADOW, durable state, action ledger, governance)
- **Tasks:** CIO synthesis (watchlist committee: Maria/Steph/Risk → final verdict), portfolio governance, retirement/IRMAA review, specialist delegation (Steph/Guardian/Ledger), Hermes research challenge, action ledger management, operator communication
- **Trade AI Wave-3:** `scripts/agent_runtime/agents/definitions.py` — id `alex`, "Chief Investment & Wealth Officer — autonomous advisory synthesis", SHADOW, enabled, 4 triggers (CIO_SCHEDULED_BRIEF, MATERIAL_PORTFOLIO_CHANGE, WATCH_ARTIFACT_CHANGED, SCHEDULED_SWEEP), denied: broker.write, order.*, risk_policy.write, position.*, config.promote, 2fa.*, secret.*, broker.submit, stop.*, approval.*
- **Durable state (Trade AI):** action ledger (`data/cio/cio_action_ledger.jsonl`, 104 entries), heartbeat snapshots (`cio_heartbeat_snapshots.jsonl`, 51 snapshots), wake jobs (`cio_wake_jobs.jsonl`), handoff queue (`agent_handoff_queue.jsonl`), notification outbox (`operator_notification_outbox.jsonl`), Hermes challenge queue (`hermes_challenge_queue.jsonl`), Darwin scorecards (`darwin_scorecards.jsonl`, 88 graded), sentinel reviews (`sentinel_reviews.jsonl`, 5 reviews), event bus (`cio_events.jsonl`, 15 event types, 5 agents routed: alex/steph/hermes/morgan/sentinel)
- **Data Broker domains (13):** portfolio, risk, watch, rotation, income, reconciliation, hermes_research, investment_policy, model_portfolio, cost_basis, **transactions** (trade history — 121 closed, 102 open lots), **sectors** (computed sector weights with concentration flags), **holdings_detail** (per-position sector, weight, cost basis, unrealized P&L)
- **Runtime:** 30-min heartbeat (`cio_heartbeat.py` — 17-domain financial snapshot, material change detection, deterministic, zero model calls) · 5-min wake worker (`CIORunWorker mode=shadow`) · agent_runtime@alex.timer (~2.5-min cadence) · overnight dual-consensus backfill (`rerun_cio_dual_consensus.py` 9:30 PM, cap CIO_DUAL_CHATGPT_CAP=1100)
- **Legacy cron (ALL DISABLED 2026-08-08):** run_alex_daily.py, alex_hygiene.py, alex_gov_research.py, alex_retirement_advisor.py — replaced by agent_runtime@alex.timer
- **API:** `/api/v3/cio` (Command Center dashboard — snapshot, actions, delegation, Hermes research; zero model calls) · `/api/v3/agent-runtime` · `/api/v3/agent-maturity`
- **OpenClaw:** `~/.openclaw/agents/alex/` — IDENTITY.md, SOUL.md (read-only advisory, tradeai-readonly skill)
- **Hermes bridge:** `cio_hermes_challenge_queue.py` — Hermes (16,152 research rows) challenges Alex via governed challenge queue
- **CIO synthesis pipeline:** `scripts/process_watchlist_agent_jobs.py` — Maria/Steph/Risk committee → Grok+ChatGPT dual-consensus → Alex CIO synthesis (DeepSeek V4 Pro) → `cio_decisions` table → Telegram delivery
- **Operator feedback:** `scripts/cio_commands.py` — `/cio ack <id>` (acknowledge action), `/cio rate <id> <useful|notuseful>` (rate usefulness, feeds gate 10). Writes to action ledger + outcome store.
- **Event bus:** `scripts/lib/cio_event_bus.py` — 15 event types, agent routing (alex: 12 types, steph: 4, hermes: 4, morgan: 5). Heartbeat emits on material change. Foundation for event-driven autonomy (Phase 0 complete).
- **Docs:** `docs/architecture/cio/` (39 files) — CIO Phase 3 delivery, ADRs, lab docs, platform readiness, quality metrics, run budgets, specialist maturity catalog · `docs/CIO_PROMPT_INPUT_AUDIT_2026_07_01.md` · `docs/architecture/cio/OPENCLAW_CIO_ARCHITECTURE_FEEDBACK_2026-08-08.md` · `docs/wealth-advisor/STEPH_WEALTH_ADVISOR.md`
- **Authority:** READ_ONLY_ADVISORY — no broker/order/risk/approval/2FA/secret/config authority. All outputs are advisory.
- **12-Gate Maturity:** 11/12 PASS. Only g1 remains: 78/100 artifacts (~1.5 days to 100). All quality gates pass: g2 (provenance 100%), g3/g4 (Darwin scored 78/78 = 100% coverage), g5 (sentinel review: 0 contradictions), g6-g9 (deterministic guarantees), g10 (usefulness proxy 0.78), g11 (4/4 rollback tests pass), g12 (zero violations). Run `python scripts/cio_gate_measurement_bridge.py` for live status. Gate measurement scripts: `scripts/darwin_outcome_scorer.py`, `scripts/backfill_cio_actions.py`, `scripts/sentinel_artifact_review.py`, `tests/test_cio_rollback.py`.
- **Current state:** Autonomous. Heartbeat: 30-min event-driven (13 domains → emits events to CIO event bus → actions on material change). Event bus: `data/cio/cio_events.jsonl` (15 event types, agent routing table). Wake worker: 5-min poll + event-driven wake. agent_runtime@alex.timer: ~2.5-min shadow cadence. Darwin: hourly scoring. Hermes: 3,385 promoted, 15-min Chief Coordinator, 11 self-learning loops (advisory-only). Dual-consensus backfill: nightly 9:30 PM (Grok+ChatGPT). Provider module: `agent_runtime_live_providers.py` (DeepSeek V4 + Ollama gemma3, **ACTIVE** — reads wake jobs + event bus).

### Aegis (Portfolio Surveillance)
- **Identity:** Portfolio surveillance agent — overnight analysis, morning briefs, covered calls
- **Model:** gemma3:27b (overnight deep)
- **Platform:** Trade AI LLM + OpenClaw (Telegram delivery)
- **Tasks:** Overnight surveillance, portfolio briefs, social sentiment, transcript discovery, synthesis
- **Output tables:** aegis_portfolio_briefs
- **RACI:** R for overnight surveillance, morning brief delivery
- **Cron:** aegis_overnight (8 PM), aegis_surveillance (8 AM), aegis_social_sentiment (11/3 PM), aegis_transcript_discovery (9 AM), aegis_synthesis (9 PM), aegis_nightly_ingestion (7 PM), aegis_morning_brief_delivery (8:05 AM)
- **OpenClaw:** ~/.openclaw/agents/aegis/

### Iris (Intelligence Librarian)
- **Identity:** Taxonomy intelligence agent — content coverage, channel curation, RAG hygiene
- **Model:** gemma3:12b (local)
- **Platform:** Trade AI LLM + OpenClaw
- **Tasks:** Gap analysis, channel discovery proposals, content quality monitoring, stale content removal
- **Output tables:** iris_run_log, iris_proposals
- **Coverage:** 69% (critical gaps: tax_strategy, etf_indexing)
- **Cron:** iris_taxonomy_agent.py (weekly Sun 10 AM full scan, daily 7 AM gaps)
- **OpenClaw:** ~/.openclaw/agents/iris/

## OpenClaw Agents
OpenClaw provides the Telegram/WhatsApp interface layer for agent interaction.

| Agent | OpenClaw Dir | Interface | Heartbeat | State |
|-------|-------------|-----------|-----------|-------|
| Alex (CIO) | ~/.openclaw/agents/alex/ | Telegram + WhatsApp (via Maria→Concierge router) | 30-min (Trade AI cio_heartbeat.py) | LIVE — advisory only |
| Steph (Wealth) | ~/.openclaw/agents/steph/ | Telegram (shared-channel: "ask Steph") | DISABLED | LIVE — 2 cron jobs |
| Aegis | ~/.openclaw/agents/aegis/ | Telegram (brief delivery) | Has file | LIVE — 7 cron jobs |
| Iris | ~/.openclaw/agents/iris/ | Telegram (proposals) | Has file | LIVE — weekly+daily cron |
| Maria | ~/.openclaw/agents/maria/ | **Telegram DMs (bound)** — portfolio, watchlist, concierge front door | No file found | LIVE |
| Guardian/Risk | risk_agent workspace | — | No evidence | SKELETON |
| Ledger/Tax | NO WORKSPACE | — | — | DOES NOT EXIST |
| Vega | NO WORKSPACE | — | — | DOES NOT EXIST |
| Darwin | Exists (minimal) | — | No evidence | SKELETON |
| Sentinel | Exists (minimal) | — | No evidence | SKELETON |
| Concierge | Exists (minimal) | — | No evidence | SKELETON |
| Morgan (Wealth) | ~/.openclaw/agents/morgan/ | — | DISABLED | LIVE — SHADOW, 5-min timer, OpenClaw registered, event bus subscribed |
| Main | ~/.openclaw/agents/main/ | Fallback agent | — | Fallback |

**Note:** Guardian, Ledger, Vega, Darwin, Sentinel, and Concierge OpenClaw agents are skeletal or non-existent — the CIO architecture prompt's 9-agent team has 3 fully operational members (Maria, Steph, Aegis) plus Alex (CIO) with Trade AI durable-state heartbeat. See `docs/architecture/cio/OPENCLAW_CIO_ARCHITECTURE_FEEDBACK_2026-08-08.md` §11 for full gap analysis.

## Wave-3 Agent Runtime (Trade AI — SHADOW/LAB only)

| Agent | Wave | DeploymentState | Enabled | OutputKinds | Reviewer | Scorer |
|-------|------|-----------------|---------|-------------|----------|--------|
| alex (CIO) | 3 | SHADOW | ✅ | CIO_SYNTHESIS, ACTION_ITEM | iris | darwin |
| steph (Allocation) | 3 | SHADOW | ❌ (pending CIO maturity) | ALLOCATION_REVIEW | sentinel | darwin |
| ledger (Tax) | 3 | SHADOW | ❌ (pending CIO maturity) | TAX_LOT_REVIEW | sentinel | darwin |
| morgan (Wealth) | 3 | SHADOW | ✅ (enabled 2026-08-09) | WEALTH_SYNTHESIS, IMPROVEMENT_PROPOSAL | iris | darwin |

**Wave-1 agents** (sentinel, darwin, iris, reflection): defined in `agent_runtime/agents/definitions.py`, SHADOW, enabled but **not producing evidence** (needs provider module + root timer enable). See `docs/agent_runtime/FLEET_STATUS_2026-07-30.md`.
**Wave-2 agents** (maria, vega, risk_agent, aegis): DESIGNED, disabled — no acceptance evidence (0 runs). Gated behind wave-1 acceptance.

## LLM Configuration
- **CIO/Synthesis:** DeepSeek V4 Pro (PRO, thinking ON for complex escalation) · DeepSeek V4 Flash (FAST, routine) · ChatGPT/gpt-5.4 (free OAuth lane, secondary — material disagreement only)
- **Routine agents (watchlist batch):** gemma3:12b on Intel Arc B50 GPU (local Ollama, primary chat)
- **Fallback:** gemma3:4b (light tasks)
- **Overnight deep:** gemma3:27b
- **Embeddings:** qwen3-embedding:8b (active)
- **Ollama URL:** http://localhost:11434
- **External:** Grok (free OAuth lane, :8645, CIOrity secondary), ChatGPT (free OAuth lane, :8646)
- **LLM cost cap:** $0.25/day (`LLM_GLOBAL_DAILY_USD_CAP`)
- **CIO dual-consensus cap:** `CIO_DUAL_CHATGPT_CAP=1100` (overnight backfill)
- **Governed routing:** `scripts/lib/cio_governed_model_bridge.py` — Trade AI model registry → OpenClaw provider config (migration in progress)
- **Budget:** Brave Search 25/day, 850/month with per-caller caps
- **Gemma4 re-evaluation:** gated for 2026-08-11 (`docs/v4_1_deployment_log.md`)
