# Trade AI v12 -- Master System Documentation

**Owner:** John W. Whiting
**Server:** ms01-openclaw (Linux, Ubuntu)
**Document version:** 2026-06-22 (A1A consolidation — scale figures via `docs/LIVE_SYSTEM_FACTS.md`; regenerate with `scripts/generate_system_facts.py`. Prior: 2026-06-02 audit)
**Status:** Paper trading validation -- 6-month window before live consideration


---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Service Architecture](#2-service-architecture)
3. [Runtime Topology](#3-runtime-topology)
4. [Database Layer](#4-database-layer)
5. [Pipeline Architecture](#5-pipeline-architecture)
6. [External Research & Signal Ingestion](#6-external-research--signal-ingestion)
7. [Screener System](#7-screener-system)
8. [Strategy Engine](#8-strategy-engine)
9. [Incubator Pipeline](#9-incubator-pipeline)
10. [Proposal Lifecycle](#10-proposal-lifecycle)
11. [Agent Layer](#11-agent-layer)
12. [LLM Subsystem](#12-llm-subsystem)
13. [API Layer](#13-api-layer)
14. [Frontend](#14-frontend)
15. [Notification & Alerting](#15-notification--alerting)
16. [Scheduling & Orchestration](#16-scheduling--orchestration)
17. [Security & Access Control](#17-security--access-control)
18. [Failure Modes & Recovery](#18-failure-modes--recovery)
19. [Safety Rules (Non-Negotiable)](#19-safety-rules-non-negotiable)
20. [Key File Locations](#20-key-file-locations)
21. [Known Constraints](#21-known-constraints)
22. [Glossary](#22-glossary)

---

## 1. Executive Summary

Trade AI v12 is an automated trading intelligence and portfolio management platform. It operates as a single-tenant, self-hosted service on a dedicated Linux server, combining:

- **Data ingestion** from 15+ external sources (market data, news, SEC filings, transcripts, social, economic indicators)
- **31-stage pipeline** organized into 7 groups running pre-market through overnight
- **23 dynamically loaded strategies** (YAML-driven, multi-assignment capable — see `config/strategies/*.yaml`; live count: `docs/LIVE_SYSTEM_FACTS.md`)
- **LLM-assisted classification** with a local-first model routing (gemma3:12b primary chat, gemma3:4b fallback, gemma3:27b overnight batch; qwen3-embedding:8b for embeddings). **qwen3:14b (chat) is disabled + uninstalled.**
- **6 AI agents** accessible via Telegram/WhatsApp (Maria, Steph, Alex, Aegis, Risk Agent, Tax Agent)
- **Iris backend agent** for content hygiene + Scalp Critic for incubator gating
- **Paper trading execution** via Alpaca with bracket orders, TCA, and reconciliation
- **React dashboard — Command Center v3 (canonical):** 11 consolidated hubs, ~37/39 tabs live, every value traced to a verified API field. Command Center v2 (63 pages) is **frozen** (legacy fallback, not maintained).
- **Feedback loop closure** with proposal outcome chains, alert effectiveness scoring, and agent calibration
- **LLM intelligence enrichment** generating daily narratives across 5 surfaces via gemma3:12b

The platform manages a portfolio (see dashboard for current value) (taxable + IRA, ~50 positions) in **paper-only mode**. Live trading is locked behind a 6-month validation gate requiring 55% win rate and 1.3 profit factor.

### System Scale

> **Live counts:** `docs/LIVE_SYSTEM_FACTS.md` — regenerate via `scripts/generate_system_facts.py`. Do not patch hard-coded numbers here.

| Metric | Live key / notes |
|--------|------------------|
| Python scripts | `codebase.python_script_count` |
| Cron jobs | `codebase.cron_job_count` (flock-protected schedules) |
| API endpoints | 280+ (`api_v2.py` + `portfolio_server.py`) |
| Database tables | `database.table_count` (public schema) |
| SQL migrations | `codebase.sql_migration_count` |
| Strategies | `codebase.strategy_count` (`config/strategies/*.yaml`) |
| Frontend | Command Center **v3** — 11 hubs / ~37–39 tabs (canonical); v2 frozen |
| Agents | 6 conversational (Maria, Steph, Alex, Aegis, Risk, Tax) + 2 backend (Iris, Scalp Critic) |
| External data sources | 15+ |
| Research topics | DB-driven (`topic_monitor`) |
| Health scoring | `scripts/health_agent.py` — 0–100 score, 5 categories |
| LLM intelligence sections | 5 (generated daily via gemma3:12b) |

---

## 2. Service Architecture

Trade AI v12 has 6 distinct service boundaries:

### Service Boundary Map

```
+-------------------------------------------------------------------+
|                          ms01-openclaw                              |
|                                                                    |
|  +------------------+    +------------------+    +---------------+ |
|  | Portfolio Server  |    | Ollama LLM       |    | OpenClaw GW   | |
|  | :7777 (HTTP+Auth) |<-->| :11434           |<-->| :18789        | |
|  | 275+ API endpoints|    | gemma3:12b        |    | 6 agents      | |
|  | React SPA @ /v2/  |    | Intel Arc B50    |    | Telegram/WA   | |
|  +--------+----------+    +------------------+    +---------------+ |
|           |                                                        |
|  +--------v---------+    +------------------+    +---------------+ |
|  | PostgreSQL 15     |    | Cron Scheduler   |    | Alert Dispatch| |
|  | :5432             |    | 184 jobs         |    | Dedup+Fatigue | |
|  | 426 tbl + 23 view |    | flock-protected  |    | 3 tiers       | |
|  +-------------------+    +------------------+    +---------------+ |
+-------------------------------------------------------------------+
                    |                    |
     +--------------+--------------------+--------------+
     |              |              |              |      |
+----v----+  +------v-----+  +----v----+  +------v---+  |
| Finviz  |  | News APIs  |  | Broker  |  | Cloud LLM|  |
| Elite   |  | 7 sources  |  | Alpaca  |  | xAI/Anth/|  |
|         |  |            |  | (paper) |  | OpenAI   |  |
+---------+  +------------+  +---------+  +----------+  |
                                                         |
                              +----v----+  +------v---+  |
                              | SEC/FRED|  | YouTube  |  |
                              | Gov Data|  | Transcr. |  |
                              +---------+  +----------+  |
```

### Cloud-Equivalent Mapping

| Current (Self-Hosted) | AWS Equivalent | Azure Equivalent |
|----------------------|----------------|------------------|
| Portfolio Server (Flask :7777) | ECS Fargate + ALB | Azure Container Apps + App Gateway |
| PostgreSQL 15 (:5432) | RDS PostgreSQL | Azure Database for PostgreSQL |
| Ollama LLM (:11434) | EC2 g5 instance / Bedrock | Azure ML GPU VM / Azure OpenAI |
| OpenClaw Gateway (:18789) | ECS Fargate | Azure Container Apps |
| Cron Scheduler | EventBridge Scheduler | Azure Logic Apps / Timer Triggers |
| React SPA | S3 + CloudFront | Azure Blob + CDN |
| Scalp WebSocket | API Gateway WebSocket | Azure Web PubSub |

### Deployment Model

**Current:** Single-tenant, single-server deployment. All services co-located on `ms01-openclaw`.

**Cloud target:** Single-tenant, multi-service deployment:
- Compute services containerized (Docker)
- Database as managed service
- LLM inference as GPU-accelerated container or managed API
- Static frontend served from object storage + CDN
- Cron replaced by managed scheduler

---

## 3. Runtime Topology

| Service | Port | Process | Health Check |
|---------|------|---------|-------------|
| Portfolio Server | 7777 | `scripts/portfolio_server.py` | `GET /api/v2/system-health` |
| PostgreSQL 15 | 5432 | `postgresql` | `pg_isready` |
| Ollama LLM | 11434 | `ollama serve` | `GET /api/tags` |
| OpenClaw Gateway | 18789 | OpenClaw daemon | `GET /health` |
| Scalp WebSocket | 7778/7779 | Scalp feed server | TCP connect |
| Frontend (Vite) | via 7777 | Served as static from Portfolio Server | `GET /v2/` |

**Project root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`

### Systemd Services

| Unit | Type | Purpose |
|------|------|---------|
| `tradeai-continuous.service` | user | Portfolio server + continuous runner |
| `tradeai-continuous.timer` | user | Auto-restart timer |
| `aegis-overnight.service` | user | Aegis synthesis jobs |
| `aegis-surveillance.service` | user | Aegis overnight monitoring |
| `portfolio-daily.service` | user | Daily portfolio operations |
| `recovery-watch.service` | user | Stop-out detection loop |
| `ollama.service` (override) | system | GPU-accelerated LLM server |

---

## 4. Database Layer

- **Engine:** PostgreSQL 15
- **Table count:** see `database.table_count` in `docs/LIVE_SYSTEM_FACTS.md` (regenerate with `generate_system_facts.py`)
- **Connection:** `localhost:5432`, database `trade_ai`, user `trade_ai`
- **Backup:** 7-day rolling `pg_dump` to `backups/db/trade_ai_*.sql.gz`

### Schema Groups

| Group | Key Tables | Purpose |
|-------|-----------|---------|
| **Trading Core** | `trade_ai_scans`, `paper_trade_proposals`, `paper_trades` | Screener results, proposals, executed trades |
| **Incubator** | `incubator_universe`, `ticker_strategy_classifications` | Symbol lifecycle, strategy assignments |
| **Intelligence** | `watchlist_agent_results`, `intelligence_entities`, `news_articles` | Agent outputs, NLP entities, news corpus |
| **Market Data** | `market_quotes`, `indicator_confluence_cache`, `fundamental_data` | Prices, technicals, fundamentals |
| **Enrichment** | `ticker_enrichment_cache`, `catalyst_cache` | 60+ Finviz fields, catalyst data |
| **Strategy** | `strategy_signals`, `strategy_configs` | Signal history, dynamic config |
| **Backtest & Entry Grading** | `strategy_backtest_runs`, `strategy_backtest_trades`, `strategy_backtest_results` (overwritten latest snapshot), `backtest_result_history` (APPEND-ONLY, one permanent row per run), `trade_backtest_results` (entry/exit A–D grades + RSI/SMA/ATR/**MACD/Bollinger/ADX/Fibonacci/candlestick/structure** context, left-on-table 5/10/20d) | Backtest replays + closed-trade entry/exit grading. `trade_backtest_results` populated by `trade_backtest_engine.py` (weekday 6:30 PM); `backtest_result_history` appended by `backtest_history_snapshot.py`. Surfaced in v3 Strategy → Backtest. |
| **AI Trade Eval** | `trade_llm_reviews` (`review_stage='structured_backtest_eval'`, `eval_overall_score`, `eval_verdict`, `output_payload`) | Structured LLM trade evaluation (gemma3:12b) — scores + verdict per closed trade. Populated by `trade_close_llm_analyzer.py --structured` (weekday 9 PM). Research/journaling only, not advice. |
| **Setup-Quality Prior (advisory)** | `setup_quality_prior` (per RSI band), `proposal_setup_advisory` (per proposal), `candidate_setup_advisory` (per incubator/watchlist symbol) | Feedback loop: distills entry grades + evals into a prior, attaches an **advisory-only** flag to proposals AND candidate symbols (never gates/blocks/changes scoring). Built by `setup_quality_prior.py` (nightly 10 PM); candidate RSI from `ticker_snapshot_daily`. Served at `/api/v2/atm/setup-advisory` + `/api/v2/setup-advisory/candidates`; surfaced as caution badges in v3 Trading hub, Strategy→Incubator, and the new v3 Watchlist page. |
| **Watch Directives (advisory)** | `watch_directives` (operator ticker/sector/trend), `watch_directive_hits`, `hermes_directive_hits_staging` (Hermes-firewall), + provenance columns on `watchlist_items`/`strategy_watchpool` | Operator standing directives honored by Trade AI + Hermes. Leads cross into Trade AI via the **governed promotion engine** (`directive_promotion.promote_directive_lead`: tier+divergence governor → enrich → classify **Bucket 2/3 only**, scalp hard-excluded → watchpool). Hermes proposes via staging only (app drains). Served at `/api/v2/watch/provenance/{symbol}`, `/api/v2/watch/directives` (create/promote), `/api/v2/watchpool`, `/api/v2/watch-directives`, `/api/v2/watch/sectors`; UI on **`/v3/watchlist`** (holdings-style enriched cards + Add Watch modal + filters + provenance pills), **`/v3/watchpool`**, and **`/v3/sectors`** (sector monitor: ETF + momentum vs SPY + setups + watch candidates, `/api/v2/sectors/monitor`); Telegram `watch`/`promote` + morning-brief section. Standing **watchlist enrichment sweep** (`scripts/watchlist_enrichment_sweep.py`, cron */30 mkt-hrs + post-close) fills rsi/trend/score/setup_advisory; backfill in `migrations/2026-06-08_provenance_backfill.sql`. **Hermes-rank priority tier (2026-06-17):** with 3,300+ researched items and a bounded Finviz cap, the sweep is two-tier — a PRIORITY pool (directive-linked OR active OR `hermes_rank <= 150`, ~162 items, refreshed stalest-first ~135/run → ~36-min cycle) keeps the visible front-page cards fresh, plus a reserved TAIL slice (cap//4) rotates the rest stalest-first so nothing is permanently starved (cap 150→180). The `/v3/watchlist` UI flags a card's AI enrichment **stale at 1h** (`last_enriched_at`; was 2h). **Full design: [`docs/WATCH_DIRECTIVES.md`](WATCH_DIRECTIVES.md).** |
| **Unified card layer (description / sector / vs-sector)** | `symbol_profiles` (description_1s, sector, industry) → `/api/v2/symbol-cards` | One map powering Watchlist / Portfolio / Open-Trades cards: a **two-line "what the company does"** blurb + sector + 1-week vs-sector performance + analyst consensus + news. Built by `build_symbol_profiles.py` (yfinance `longBusinessSummary` first two sentences; weekly cron Sun 19:00). ETFs (no yfinance sector → `_ETF_SECTOR`: SPDRs→GICS sector, broad/bond/income→asset-class label) and open-end mutual funds (`_FUND_SECTOR`: Morningstar-style category) get a sector label instead of a blank pill; opaque 401k fund codes / delisted CUSIPs stay blank (no name source). |
| **Schwab API capability map (design)** | — (doc) | Maps the FULL Schwab Trader API capability set to Trade AI v12: BUILT (account/positions/transactions/orders/quotes, OAuth, ledger, journal, ToS watchlists) · READY-not-wired (batch quotes, price history, option chains, fundamentals, market hours, rate-limit numbers) · FENCED (all order types — Stage 2) · N/A (watchlists, paper-via-API, streaming-deferred). No code. Full: [`docs/architecture/SCHWAB_API_CAPABILITY_MAP.md`](architecture/SCHWAB_API_CAPABILITY_MAP.md). |
| **Schwab real-account journal (read-only, live)** | `trade_transactions`(+trade_time) / `schwab_round_trips` / `schwab_account_links` | Stage-1 LIVE: API-authoritative ledger (replace-in-window, slippage-granular, dividends/transfers, sweep noise filtered; 2026-06-12 roth/rollover hash-link swap CORRECTED — active trading account is the ROLLOVER ..0258, see SCHWAB_API_PHASE1_READONLY_FOUNDATION.md) → 135 round-trips (5-min agg + FIFO, +$17.4K net) → LLM strategy/grade/lesson. Paper closed trades reviewed into `journal_trade_reviews` (`journal_review_builder.py`); backtest SIMS (18,966) excluded (synthetic). Surfaces: System→Brokers `SchwabMonitor`, Journal→Real Accounts `SchwabJournal`. Daily crons 18:15/18:30. Separate from paper_trades (gate paper-only); writes still fenced (validator 17/17 as of 2026-06-12). Full: [`docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md). |
| **Engineering hard rules (enforced)** | — (git hook + code guards) | **No secrets in git**, **no hardcoded values** (chat IDs via `tg_chat_ids.chat_ids()`, broker/account-agnostic, default account from `DEFAULT_PAPER_ACCOUNT`), **holdings.json never wiped** (`protected_holdings_write`). First two enforced by `scripts/check_no_secrets.py` (pre-commit + pre-push, `install_git_hooks.sh`); blocks API-key/secret-file/`.env`-value, hardcoded chat IDs, and `or "broker"` fallbacks (`# hardcode-ok` opt-out). **Full reference: [`docs/ENGINEERING_HARD_RULES.md`](ENGINEERING_HARD_RULES.md).** |
| **Time-exit proposals (advisory, approval-gated)** | `paper_time_exit_proposals` | Positions held past their strategy `max_hold_days` → advisory close proposal (`generate_max_hold_exit_proposals.py`, cron). Operator approves via Trading→Open-Trades, `POST /api/v2/time-exit-proposals/decide`, or Telegram one-tap (texitapprove/texitreject); approval is hard-guarded (broker-agnostic `live_trading_interlock` on the trade's account + `close_paper_trade`). No silent auto-close. |
| **Schwab API — Phase 1 read-only foundation (reads LIVE+proven, writes fenced)** | `broker_oauth_tokens`(encrypted)/`broker_oauth_token_audit`/`schwab_account_links`/`schwab_api_raw_snapshots`/`schwab_basis_divergence`/`schwab_sync_history` | **Reads LIVE + proven** (Developer Portal app approved, credential-in pass complete); **writes NOT_PROVEN/fenced**. Safety guards proven by failure-injection (deliberately fed empty/401/timeout/near-expiry to prove fail-closed). GATE A `schwab_token_manager.py` (7-day refresh expiry first-class, no infinite refresh, Fernet-encrypted tokens with key only in 0600 gitignored file, day-5/6 Telegram alerts, fail-closed health, shared rate limiter). GATE B `schwab_position_sync.py` `protected_holdings_write` (bad payload⇒NO-OP byte-unchanged, backup+atomic+post-assert+restore, tax-basis flag-not-overwrite). `schwab_adapter` writes (submit_entry/cancel_order/_api_post)⇒NOT_PROVEN. **Stage 1 read-only transport:** `schwab_transport.py` wraps schwab-py 1.5.1 (MIT) as request/response ONLY (manager stays system-of-record via token hooks); normalizers reconciled vs live payloads; place_order/cancel_order/replace_order FENCED (raise NotProvenWrite), schwab-py imported only at the boundary; `validate_schwab_no_writes.py` 17/17 (2026-06-12: +5 Stage-2a guards — harness/capture read-only, hardcoded-gate purity+front-position, dormant-UI no-execution-path, canary consumer filters) incl Level II isolation (Rule 9); Schwab stays MANUAL_REVIEW/api_write_enabled=false. Cost basis: `schwab_cost_basis_lots`+`ingest_schwab_gainloss.py` (Schwab export authoritative); V reconciled to Schwab authoritative basis (+$168K→+$117,356, 169 sh basis_unknown pending realized export); journal consolidated to schwab_round_trips single source. **Full design: [`docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md).** |
| **Stage 2a readiness — ToS-style dormant Broker Orders UI + hardcoded canary gate + two-channel approval (2026-06-12)** | `schwab_round_trips.canary` / `schwab_shadow_recon_runs`+`_items` / `schwab_activity_log` / `trade_approvals`(typed-ticker web codes) | READ-ONLY phase, execution BROKER_DISABLED throughout. `brokers/canary_gate.py` = commit-only envelope (allowlist EMPTY until session commit · ≤$4 · ≤10 sh · ≤$40 · US equities · long-only) evaluated IN FRONT of the guard's mode logic for all mutating actions (22/22 tests incl. hypothetical-lift). Shadow recon `schwab_shadow_recon.py` (~30s read-back diff vs translator prediction; mismatch=ABORT) + activity capture `schwab_activity_capture.py` (poll, streaming deferred). Canary trips excluded from ALL analytics (6 consumers; zero-aggregate-movement proof). v3 Trading→Broker Orders: ToS-desktop Active Trader DRAFT builder (presets 2/5/10, structure-aware tooltips, advisory-only AI help local-first/Claude-on-request); Trading→Schwab Accounts: 3-account live monitor (`/api/v2/schwab/accounts-live`, edit→DRAFT only). 2FA: Telegram ✅ (+Tailscale deep-link to the intent) AND web TYPE-the-ticker popup; single-use, TTL, one order at a time; fully approved ⇒ still BLOCKED (proven). Protocol: [`docs/brokers/stage2a-canary-protocol.md`](brokers/stage2a-canary-protocol.md); guards: [`docs/brokers/execution-safety-guards.md`](brokers/execution-safety-guards.md). |
| **Stage 2b canary — FIRST live Schwab order proven (place→cancel), 2026-06-15** | `broker_order_intents` / `trade_approvals` / `intent_state_events` / `schwab_round_trips.canary` | **First live Command Center → Schwab write, end-to-end.** BUY 10 GRAB LIMIT 1.70 submitted (real `broker_order_id 1006761718313`, `state:SUBMITTED`) → rested (50% below market, can't fill) → operator cancelled in ToS → Schwab `canceled`. Chain proven: **arm (typed phrase, 6h DB session) → preflight (`schwab_stage2b_canary_preflight`) → single-channel 2FA (`approval_service`, `REQUIRED_CHANNELS=1`) → `pilot/execute` → `schwab_transport.place_order` → live order**. Pilot Console is the ONLY submit surface; draft cards are draft-only (approval flow removed — it used to create slot-holders). Battery pared to one **$0 PLACE→CANCEL** preset + manual form. **Fixes:** `consume()` supersedes leftover pending channel (was holding the one-at-a-time slot); SUBMIT auto-clears a stale slot + retries; preflight-hang cleared by restart. **Cancel-from-CC proven** (Pilot Orders "cancel order" button → `confirm()` → `pilot/cancel` → live Schwab cancel; shows for any non-terminal status). **Order-status reconcile** (`_pilot_status` reads Schwab live status by `broker_order_id`, overlays `live_status` + persists — `submitted`→`working`/`canceled`/`filled`; fail-open, stops once terminal) — closed the stale-status gap. **Widen via:** `canary_gate.CANARY_SYMBOL_ALLOWLIST`/`CANARY_SESSION_DATE`, `STAGE2B_MAX_PRICE_USD` ($4), `pilot_caps` (≤10sh/≤$40/5-order/account-allowlist=taxable-only), then real-fill+close, then lift `BROKER_DISABLED`. See CHANGELOG 2026-06-15 + [`docs/brokers/stage2b-write-pilot-spec.md`](brokers/stage2b-write-pilot-spec.md). |
| **Stage 2c — Stop Management (LIVE production, 2026-06-15)** | `schwab_pilot_orders`(kind) / `trade_approvals` / `stop_lifecycle` / `stop_grok_reviews` / `paper_trades` / `system_controls`(`protective_stops_enabled`) / `fidelity_monitored_stops` | **Protective stops live across all taxable + both Schwab IRAs** (Fidelity 401k ticket-only; no API). **`fidelity_rollover_ira` (2026-06-22):** SnapTrade read-only → **monitor-only** stops (`fidelity_monitored_stop.py`, standing unlock `fidelity_stops_enabled` via `snaptrade_pilot_arm.py --approve`); **no 2FA** (no broker execution); breach = alert + Active Trader ticket. Committed envelope `protective_stop_policy.py` (SELL-to-close, stop<price, qty≤held, ±8% drift, ≤$250k; tamper-evidenced). Schwab protective stops are **standing** (`_protective_unlocked()`); canary BUY pilot still ARM-gates. **Schwab: manual + per-order 2FA** for every place/**Modify**/Cancel. **Monitoring**: `stop_lifecycle_monitor.py` + `unified_stop_supervisor` (incl. fidelity monitored ratchet). **Alpaca = AUTOMATIC** (`alpaca_stop_manager.py`, paper-only, no 2FA). **SnapTrade one-share test** (no sandbox): `snaptrade_trade_pilot` when trade-capable broker linked. **Full architecture: [`docs/brokers/stop-management-architecture.md`](brokers/stop-management-architecture.md); Fidelity: [`docs/brokers/snaptrade-fidelity-protective-stops-spec.md`](brokers/snaptrade-fidelity-protective-stops-spec.md).** |
| **Hermes Intelligence Engine (advisory)** | `hermes_score_history` (21d retention), `hermes_weight_calibration`, `hermes_outcome_ledger`, `scope_governor_audit`, `hermes_score_event_queue`, `hermes_promotion_thresholds`, `hermes_lane_usefulness`, `hermes_tag_efficacy`, `hermes_maturity_history`, + `scope_tier`/`hermes_composite_score`/`hermes_rank`/`hermes_score_components` on `watchlist_items` | Ranked watchlist over a **governed, event-driven universe** (Maturity-5 program, 2026-07-02): `hermes_scope_governor.py` owns S0-S3 scope tiers (S0+S1+S2 ≤ 800, TTLs, audited); `hermes_watchlist_scorer.py` (`*/15`, tier plans + event lane via `hermes_score_event_feeder.py`) → composite + rank; `/v3/watchlist` ★rank badges; `GET /api/v2/hermes/intel/{symbol}` structured card. **Outcome spine:** `hermes_outcome_grader.py` nightly grades every promotion / external rec / research row / trade vs money; `hermes_outcome_learning.py` feeds weights (additive-clamped, shadow-gated — the drift calibrator is retired), promotion confidence gates, source retirement, and lane routing from the ledger; `hermes_tag_engine.py` = registry-vocabulary tags + continuous quality + tag-efficacy lift. `hermes_maturity_gates.py` computes the honest 6-dimension board (5s require 30-day streaks) into the maturity dashboard; `hermes_config_governor.py` files out-of-rails wants as `config_change_proposals`. H-5 alerts (`hermes_score_alerts.py`→alert_events+Telegram). **Full design: [`docs/design/HERMES_MATURITY_5_DESIGN.md`](design/HERMES_MATURITY_5_DESIGN.md) · engine: [`docs/HERMES_INTELLIGENCE_ENGINE.md`](HERMES_INTELLIGENCE_ENGINE.md).** |
| **Execution Quality** | `paper_execution_quality`, `broker_reconciliation_items`, `trade_thesis_outcomes` | TCA metrics, recon, outcome tracking |
| **Agent** | `cio_decisions`, `decision_outcomes`, `agent_handoffs` | Decision audit trail (CIO deduped per 24h) |
| **Recovery** | `stopped_out_watch`, `stopped_out_relist_events`, `stopped_out_watch_history` | Exit classification (true stop-out vs relist vs market reconnection), patience scoring |
| **Portfolio** | `portfolio_holdings`, `portfolio_accounts`, `personal_situation` | Positions, accounts, personal data |
| **System** | `pipeline_runs`, `daily_system_metrics` | Pipeline health, trending |
| **Feedback Loops** | `proposal_outcome_chain`, `alert_effectiveness`, `strategy_performance_snapshots`, `agent_sample_tracking`, `recovery_outcome_log`, `cio_decision_responses`, `gemma3_calibration_events` | Closed-loop tracking: proposal → trade → P&L → agent calibration. gemma3 overnight accuracy tracked via `gemma3_accuracy_by_job_type` view |
| **LLM Cache** | `llm_intelligence_cache` | 5 daily-generated LLM narratives (portfolio risk, rebalance, recovery, morning, prospects) |
| **Research** | `sec_form4`, `youtube_transcripts` | Filings, transcript archive |
| **Topic Intelligence** | `topic_monitor`, `content_entity_links`, `blocked_content`, `iris_library_gap_fills`, `topic_curation_feedback` | Topic research, entity linking, quality gating, learning loop |

### Critical Data Volumes

| Table | Approximate Rows | Growth Rate |
|-------|------------------|-------------|
| `news_articles` | 3,022+ | +200/week |
| `social_posts` | 2,248+ | +150/week |
| `incubator_universe` | 1,139 active | +50/week (rolloff cleans stale) |
| `trade_ai_scans` | 640 (current window) | 40-120/day weekdays |
| `cio_decisions` | 446 (deduped per 24h) | +15/day unique |
| `notification_log` | 90 | +5-10/day |
| `proposal_outcome_chain` | 38 | Grows with proposals |
| `alert_effectiveness` | 31 | +5-10/week |
| `llm_intelligence_cache` | 5 | Refreshed daily |

---

## 5. Pipeline Architecture

The pipeline runs **31 stages organized into 7 groups**. Each group has a designated time window and dependency chain.

```
[1. DATA COLLECTION] >>> [2. ENRICHMENT] >>> [3. SCORING] >>> [4. INTELLIGENCE] >>> [5. PROPOSALS] >>> [6. EXECUTION] >>> [7. OVERNIGHT]
    6-7 AM                   7-8 AM            8-9 AM           continuous          throughout day      market hours         8 PM+
```

### Group 1 -- Data Collection (6-7 AM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Finviz Screener Runner | `finviz_screener_runner.py` | Finviz Elite API (cookie + token) | `trade_ai_scans` rows |
| Social Ingest | `social_ingest.py` | Social media feeds | Sentiment scores |
| News Ingestion | `news_ingestion.py` | NewsAPI, Finnhub, FMP, Polygon, RSS | `news_articles` rows |
| FRED Data Ingest | `fred_data_ingest.py` | Federal Reserve API | Economic indicators |
| SEC Data Ingest | `sec_data_ingest.py` | SEC EDGAR | `sec_form4` (insider filings) |

### Group 2 -- Enrichment (7-8 AM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Finviz Enrichment | `finviz_enrichment.py` | Finviz 5-view pages | 60+ fields per symbol in `ticker_enrichment_cache` |
| Catalyst Enrichment | `catalyst_enrichment.py` | 7 API sources | `catalyst_verified` flag, `catalyst_cache` |
| Symbol Enrichment | `symbol_enrichment.py` | Fundamental APIs | `fundamental_data` |
| RAG Indexer | `rag_indexer.py` | News + transcripts + filings | Vector embeddings for search |

### Group 3 -- Scoring (8-9 AM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Trade AI Orchestrator | `trade_ai_orchestrator.py` | Scans + enrichment | 55-point scores, GO/WAIT/NO-GO |
| Indicator Engine | `indicator_engine.py` | yfinance OHLCV | 17 technical indicators in `indicator_confluence_cache` |
| Premarket Watcher | `premarket_watcher.py` | Pre-market quotes | Gap and volume alerts |
| Agent Router | `agent_router.py` | Scored symbols | Routes to appropriate agent |

### Group 3b -- Sentiment & Signal Fusion (7 AM, 12 PM M-F)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Sentiment Processor | `sentiment_processor.py` | Unscored news_articles | sentiment + sentiment_score on each article; sentiment_observations |
| Signal Fusion | `signal_fusion.py` | catalyst + news + social + sentiment | `fused_signals` (strategy-weighted composite per symbol) |
| Topic Curator | `topic_curator.py --improve-queries` | Recent articles + LLM | Content ratings, entity links, improved search queries → auto-ingestion (loop-capped: re-ingest passes `--no-auto-curate`) |

### Group 4 -- Intelligence (Continuous)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Watchlist Agent Jobs | `process_watchlist_agent_jobs.py` | Job queue + RAG + sentiment + social + fused + peers | Agent analysis results |
| Agent Event Router | `agent_event_router.py` | agent_event_queue | Routes events → agent jobs; handles CONTENT_GAP and RESEARCH_MORE |
| Agent Watchlist Engine | `agent_watchlist_engine.py` | Agent outputs | Updated watchlists |
| CIO Decision Engine | `cio_decision_engine.py` | All intelligence | `cio_decisions` |
| Pipeline Watchdog | `pipeline_watchdog.py` | `pipeline_runs` | Failure alerts + auto-retry |

### Group 5 -- Proposal Pipeline

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Weekly Incubator Builder | `weekly_incubator_builder.py` | Qualified scans | `incubator_universe` rows |
| Daily Incubator Refresh | `daily_incubator_refresh.py` | Incubator symbols | Updated scores/catalysts |
| Incubator Rolloff | `incubator_rolloff_engine.py` | Decayed symbols | Removed entries |
| Proposal Promoter | `incubator_proposal_promoter.py` | ACTIVE incubator | `paper_trade_proposals` |
| Proposal Enrichment | `proposal_enrichment_loop.py` | Open proposals | Enriched data packets |
| Proposal Lifecycle | `proposal_lifecycle.py` | Proposal states | State transitions |

### Group 6 -- Execution (Automated, Market Hours)

| Stage | Script | Trigger | Outputs |
|-------|--------|---------|---------|
| Risk Gate | `risk_gate.py` | On proposal creation | Pass/fail + reason codes. Paper cap $15K (env: `PAPER_MAX_POSITION_SIZE`) |
| Instant Submission | `api_v2.py` → `proposal_paper_submitter.py` | On approval click | Immediate Alpaca order (market or limit based on price proximity) |
| Smart Order Type | `alpaca_paper_adapter.py` | During submission | Market if price ≤ entry or within 2%; limit+bracket if >2% above |
| Execution Sweep | `paper_execution_sweep.py` | Every 5 min (cron safety net) | Catches approved proposals not yet submitted |
| Position Monitor | `paper_trade_monitor.py` | Every 2 min (cron, market hours) | R-multiple trailing stops, target detection, automatic closes, phantom integrity-check (closes DB-open positions not held at broker with **voided** P&L — `pnl=0, verdict=PHANTOM`) |
| Broker Reconciliation | `alpaca_paper_reconciler.py` | On fill events + scheduled 09:35 & 16:05 with `--fix` | Broker is **source of truth**: `--fix` overwrites DB entry/shares/fill-confirmation FROM the broker, never the reverse. `broker_reconciliation_items` |
| Execution Quality | `execution_quality_analyzer.py` | On trade close | TCA metrics |

### Group 7 -- Overnight (8 PM - 6 AM)

| Stage | Script | Inputs | Outputs |
|-------|--------|--------|---------|
| Overnight Intelligence | `aegis_overnight.py` (systemd `aegis-overnight.timer` 20:00 + cron `0 20 * * *`) | Nightly deltas, sentiment, transcripts | Briefs, candidates, morning handoff |
| ~~Overnight Batch~~ | ~~`overnight_batch.py`~~ | — | **RETIRED** (PHASE102; cron tagged `PHASE102-RETIRED`, last run 2026-05-29). Its agent-performance scorer was rehomed to `update_agent_performance.py` (cron `0 20 * * 1-5`) |
| Agent Outcome Scorer | `agent_outcome_scorer.py` | Past recommendations | Performance grades |
| Strategy Weekly Review | `strategy_weekly_review.py` | Strategy signals | Performance reports |
| Overnight Embeddings | `overnight_batch_embeddings.py` | New content | Refreshed RAG index |

---

## 5b. Closed-Loop Intelligence Pipeline (Session 37)

The system operates as a **closed-loop intelligence engine**, not a data warehouse. Every data source feeds into correlation, every agent analysis feeds back into new searches, and every failure triggers a notification.

### Full-Circle Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CLOSED-LOOP INTELLIGENCE                         │
│                                                                     │
│   INGEST ──→ CORRELATE ──→ SENTIMENT ──→ CURATE ──→ AGENTS        │
│     ↑          by symbol     score all      LLM rate     analyze   │
│     │          + entity      + fuse          + link       + judge   │
│     │                                                      │        │
│     │          ┌──────────────────────────────────────────┘        │
│     │          ▼                                                    │
│     │     DEMAND SIGNAL                                             │
│     │     ├─ CONTENT_GAP (Iris detects missing coverage)           │
│     │     ├─ RESEARCH_MORE (agents need more data)                 │
│     │     └─ IMPROVED QUERIES (curator learns what's missing)      │
│     │          │                                                    │
│     └──────────┘  auto-trigger: search → ingest → score →          │
│                   RAG re-index → re-analyze → Telegram notify      │
└─────────────────────────────────────────────────────────────────────┘
```

### Layer Detail

| Layer | Script(s) | Input | Output | Cadence |
|-------|-----------|-------|--------|---------|
| **Ingest** | news_ingestion, social_ingest, youtube_transcript_ingest, sec_data_ingest | External APIs | Raw rows in news_articles, social_posts, youtube_transcripts | 2-3x daily + on-demand |
| **Correlate** | intelligence_entity_manager, topic_curator (extract_and_link_entities) | Raw content | content_entity_links (symbol ↔ content), intelligence_entities (per-symbol score) | After each ingest |
| **Sentiment** | sentiment_processor, signal_fusion | news_articles, social_posts | sentiment_observations (per-article), fused_signals (per-symbol composite) | 2x daily (7 AM, 12 PM) |
| **Curate** | topic_curator (rate_pending_content, improve_queries) | Pending content + LLM | rag_status=approved/blocked, llm_generated_queries, content_entity_links | Daily 7 AM |
| **Agent Analysis** | process_watchlist_agent_jobs | RAG + sentiment + social + fused + peers + playbook | watchlist_agent_results (recommendation, confidence, narrative) | Every 15 min |
| **Demand Signal** | agent_event_router (handle_content_gap, handle_research_more_demand) | CONTENT_GAP events, RESEARCH_MORE recommendations | Auto-triggered: topic_ingestion → sentiment → RAG → re-analysis | On event |
| **Feedback** | agent_outcome_scorer, learning_governance | Closed trades vs prior recommendations | agent_calibration (win rate, PnL), confidence adjustments | Daily 5:30 AM |
| **RAG Index** | rag_indexer | All approved content + agent results + synthesis | Vector embeddings for semantic search | 4x daily + on gap-fill |

### Agent Context Injection (per symbol analysis)

Every time an agent analyzes a symbol, it receives this full context stack:

```
1. Scan Intelligence    — screener position, score, decision (GO/WAIT/AVOID)
2. RAG Pre-Context      — top 5 prior intelligence items (news, transcripts, agent results)
3. News Sentiment (7d)  — article count, avg score, headlines with sentiment labels
4. Social Sentiment (7d)— post count, bullish/bearish/neutral breakdown, top posts
5. Fused Signal         — strategy-weighted composite (catalyst + news + social + sentiment)
6. Peer Agent Notes     — what other agents concluded on this symbol recently
7. Content Gap Warnings — Iris librarian flags on missing coverage
8. Technical Confluence — RSI, SMA, ATR, confluence tier
9. Prospects Context    — pipeline position (incubator, proposal, paper trade)
10. Calibration Data    — agent's own win rate, avg confidence, past PnL on similar
11. Strategy Playbook   — role instructions, entry/exit rules, risk parameters
12. Global Rules G1-G10 — income protection, SSDI awareness, confidence gating
```

### Demand-Driven Search Loop

When agents need more data, the system auto-responds:

| Trigger | Source | Action Chain |
|---------|--------|-------------|
| **CONTENT_GAP** | Iris librarian detects missing coverage | topic_ingestion → news search → sentiment_processor → RAG re-index → Maria re-queued |
| **RESEARCH_MORE** | Agent outputs low-confidence RESEARCH_MORE | Checks watchdog_actions for recent fills → fires synthetic CONTENT_GAP → full search loop |
| **Improved Queries** | topic_curator generates better search terms | Auto-runs topic_ingestion --use-llm-queries → new content flows back to curation |

### Per-Agent Full-Circle Integration

| Agent | Reads | Writes | Triggers | LLM Model |
|-------|-------|--------|----------|-----------|
| **Maria** | RAG, sentiment, social, fused, peers, playbook, scans | watchlist_agent_results (BUY/HOLD/AVOID + narrative) | Re-analysis on gap-fill; debate on SEC insider buy | gemma3:12b (2-pass: sentiment + fundamentals) |
| **Steph** | Portfolio state, allocation targets, income projections, sentiment | watchlist_agent_results (ADD/TRIM/HOLD + allocation review) | Escalation queue for concentration risk; INCOME_CRITICAL flag | gemma3:12b |
| **Alex** | Roth conversion models, IRMAA thresholds, tax brackets, retirement RAG | Research reports, Roth ladder plans, monthly reviews | Auto-queued on SEC insider buy consensus; weekly/monthly research | gemma3:12b + Claude (complex) |
| **Aegis** | All agent results, portfolio positions, overnight events | Morning briefs, synthesis reports, cross-agent coordination | Morning brief delivery; post-trade synthesis writeback | gemma3:12b |
| **Iris** | Content freshness, RAG coverage, duplicate detection, entity staleness | Hygiene proposals, CONTENT_GAP events, taxonomy proposals | CONTENT_GAP → auto-search; hygiene escalations to John | gemma3:12b (classification) |
| **Scalp Critic** | Incubator candidates, catalyst data, technicals, news/social | llm_screen_grade (A-F), verdict (PROMOTE/HOLD/DROP) | Gates incubator → proposal promotion | gemma3:12b |

### Agent LLM Flow

```
Symbol enters pipeline
    ↓
gemma3:12b Pass 1 (sentiment + catalyst analysis)
    ↓
gemma3:12b Pass 2 (fundamental + technical synthesis)
    ↓
Combined result → JSON (recommendation, confidence, narrative)
    ↓
Stored in watchlist_agent_results
    ↓
Indexed into RAG (8h cadence)
    ↓
Available to next agent analyzing same symbol
    ↓
Outcome scorer matches to closed trades → calibration update
    ↓
Next run: agent sees updated calibration → adjusts confidence
```

> **Local-model status (2026-06-14):** the per-agent passes above resolve to `DEFAULT_LOCAL_LLM_MODEL`,
> which is **`gemma3:4b`** — the reliable local model. `gemma3:12b` is the *aspirational* policy primary
> but is currently **broken at the ollama runtime** (HTTP 500 on every prompt, even a one-line one — a
> VRAM/model-load failure, not a context limit). Re-pull (`ollama rm gemma3:12b && ollama pull
> gemma3:12b`, check VRAM) before re-pointing the default at it. Where the table says "gemma3:12b", read
> "the local default" until 12b is fixed.

### CIO Final Synthesis (Grok-primary, 2026-06-14)

The four watchlist specialists (Maria / Steph / Risk → handoff) each emit a structured opinion; a **fifth
CIO synthesis pass** reconciles them into the single `latest_recommendation` shown on the cards
(`scripts/process_watchlist_agent_jobs.py`). That synthesis pass now runs on a **two-lane router**:

1. **Primary — free Grok OAuth** (`grok-3-mini` via the local xAI proxy, `llm_lane.generate(lane="grok")`,
   $0 cost). Chosen after a grok-vs-12b A/B in which **12b 500'd on all three names** while Grok produced
   sharper, more skeptical reads (e.g. NVDA BUY→AVOID 0.88, DLR BUY→ADD_ON_PULLBACK, BDSX BUY→IGNORE).
2. **Fallback — local default** (`gemma3:4b`) via `llm_router`, used only if the Grok lane is unavailable.

Each synthesis is **prompt-versioned**: the prompt is stamped `[prompt_version: cio_synth_v2_grok_2026-06-14]`
and the row records `synthesis_version = 2` (integer) plus the actual `model_used` (`grok-3-mini` or the
local model that produced it) for audit. This replaced a bug where `model_used` was hardcoded to the
Ollama model regardless of which model actually ran.

**Queue prioritization** — the job picker in `process_watchlist_agent_jobs.py` no longer drains the
~3,000-name backlog FIFO. It tiers by `EXISTS` subqueries so the names the operator cares about refresh
first, then `priority`, then `created_at`:

| Tier | Criterion |
|------|-----------|
| 0 | Symbol is an **operator directive-watch** name (`watchlist_items.in_directive_watch`) |
| 1 | Symbol is **active** on the watchlist (`status='active'`) |
| 2 | Symbol has a **BUY / STRONG_BUY** research card |
| 3 | Everything else (the long tail) |

**Re-run / staleness logic** — `aegis_overnight` flags any symbol not analyzed in **48h** and queues a
`stale_refresh`; the market-hours cron drains ~5–10 jobs/run; a synthesis decision **expires at 14 days**
(G4). With tiered prioritization, the ~50 directive/active/buy-rated names stay fresh while the tail no
longer starves them.

### Portfolio Look-through, Ask-the-Agents & IPO Lockups (2026-06-14)

**Look-through** (Portfolio → Look-through tab; `portfolio_lookthrough_themes.py`; `/api/v2/portfolio/lookthrough`,
refreshed daily 07:40) resolves every fund to its underlying stocks (yfinance fund top-holdings) and
aggregates portfolio-wide + per-account. Surfaces: theme exposure (Mag7 / Nasdaq100 / S&P500 / Semis / AI
mega-cap / AI-datacenter-power / Nuclear / Energy / Cyber / Defense / China), top-underlying-stock
concentration with **fund-source tooltips**, a concentration donut, rule-based advisories, a Grok narrative,
and **CIO / Risk / Steph agent cards**. Honest caveat: yfinance gives top-10 fund holdings → theme %s are
lower bounds.

**Ask-the-Agents** (`AskAgents` component on Look-through + Risk; `portfolio_ask.py`; `/api/v2/portfolio/ask`)
— natural-language Q&A that pulls REAL positions + analyst ratings (pro_analyst) + look-through and routes
to Grok as CIO/risk advisor. Frames R:R from analyst targets; handles private names. **Defer-to-live-data**
rule: a name with a live quote IS public (the model's training may be stale — e.g. SpaceX/SPCX IPO'd
2026-06-12). `private_symbols.py` lists only genuinely-private names (OpenAI/Stripe/Anthropic/Databricks).
"Set alert" → `ask_alerts.py` (IPO-news / price → Telegram). **Ticker resolution is case-INSENSITIVE
(2026-06-16):** the operator types lowercase ("trim xlb for spcx"), so `_tickers()` validates lowercase
tokens against the symbols actually held / with analyst data (filtering common words like "trim"/"look"),
while explicitly-uppercase tokens still pass for not-yet-held names. The position context carries **shares,
live price, basis, and a per-account breakdown** so the model can answer "how many shares to trim"; analyst
upside is recomputed against the live holdings price, not the stale analyst-snapshot price.

**Strategy Planner** (Strategy hub → **Planner** tab, `/v3/strategy`; `strategy_planner.py`;
`POST /api/v2/strategy/{plan,approve}`) — interactive "declare → impact → advise → approve→sync" loop
(2026-06-17). (1) **Declare** an intent (roll account→cash, trim, deploy cash, rebalance). (2) **Impact**
(what-if, read-only): exact **look-through theme delta** computed from `lookthrough_themes.json`
`accounts_detail` (per-account exposure), account refactor, cash freed + cash-% shift, and a **precise
per-holding income hit** (Σ market_value × dividend yield% from the authoritative `dividend_calendar`; the
raw `ticker_dividend_data` feed is rejected for systematically inflated yields, and tax-deferred 401k funds
correctly show no spendable distribution) vs the **$55k** target. (3) **Advise**: goal-aligned redeploy plan via the free LLM lane (income-gap / Roth
golden-window / defense-thesis aware) + Hermes-ranked watchlist candidates. (4) **Approve** → persists to
`strategy_plans` **and syncs both ways**: LEARNING (`llm_feedback_observations`, `workflow=strategy_plan`)
so the approved direction trains the models, and DISCOVERY (auto-creates operator **`watch_directives`**
that seed the discovery engine + watchlist sweep). Closes the loop **strategy → discovery → watchlist →
proposal**. Advisory + read-only — approval seeds discovery, never places a trade. **UI (`StrategyPlanner.tsx`,
redesigned 2026-06-17):** the declare form sits beside a **live "Current — <account>" panel** (value + top
holdings from `/api/v2/portfolio/holdings`), resolves the dollar amount in place ("sell all 10 positions in
fidelity_401k = $573,968"), gives trims a holding picker, and renders the result as a guided 4-step flow with
**before→after** metric cards (cash weight, income lost, account-after) + the per-holding income breakdown.

**IPO lockups** (`config/ipo_lockups.json` from the primary **S-1 on SEC EDGAR**; `ipo_lockups.py`) — when
insiders can sell, by tranche. `ipo_lockup_alert.py` fires Telegram 14d before each unlock;
`update_lockup_earnings_dates.py` auto-snaps earnings-tied tranches to the real report date when announced.

### Per-surface external "second-read" lanes + alert-noise fixes (2026-06-14)

**Enhancement engine** — `hermes_subject_enhance.py` runs a free-OAuth Grok "second read" over each site
surface and stores it in `hermes_external_research` (`trigger_reason=enh_<type>`); the `✦ Grok` badges
(Home brief, Open Trades, Proposals, Sectors, Closed trades) read it via
`/api/v2/hermes/subject-intel-map?type=<type>`. Gatherers per type: `report` (the daily morning brief),
`position`, `proposal`, `closed_trade`, `sector`, `scalp`. `FRESH_HOURS=12` (scalp 4) de-dupes re-runs.
Cron: scalp/proposal/position/sector/closed_trade scheduled in the enh block; **`report` added
`0 8,20 * * *`** (was unscheduled — the lane sat stale at a June-9 one-off).
- **Gatherer robustness** — `gather_report` globbed `reports/*` and picked the newest path by mtime, which
  became the `weekly/` **directory**; `read_text()` → `IsADirectoryError` swallowed by a bare except,
  silently zeroing the lane. Now files-only + prefers `aegis_morning_brief_*.md` + `errors="ignore"`. Audit:
  this was the ONLY gatherer with the trap (the rest are DB-query-only or read fixed paths).

**Home → Morning Brief rendering** — `HomeHub.tsx` formerly dumped `action_items` / `strategy_health` /
`overnight_activity` via `JSON.stringify`. Now formatted (severity-colored action rows + code chips,
strategy stat chips, overnight metric grid with a quiet-night empty state).

**Position-card & regime data-accuracy fixes (2026-06-16)** — `open_trades_intelligence.py` +
`aegis_nightly_ingestion.py` + `market_regime_classifier.py`:
- **ETF sector mislabeling** — Finviz tags EVERY ETF as sector "Financial" (industry "Exchange Traded
  Fund"), so XLI/XLB/BND/SCHD/SCHG/JEPI/ARKG all showed "Financial (XLF)" on the Open Trades cards. An
  authoritative `_ETF_SECTOR` map now takes PRECEDENCE (sector SPDRs → real GICS sector; broad/bond/income
  funds → honest asset-class label, no faked "in-line" when there's no sector ETF to compare). Fixed at
  ingest too (`_corrected_sector()` refuses a bare Finviz "Financial" on any ETF) + 664 rows backfilled, so
  Sectors/Watchlist don't re-inherit it.
- **Worthless/delisted equity** — a real ticker (not a fund) collapsed to ~$0 with <−90% P&L (e.g. SRNE
  @ $0.0007) was showing cached RSI/SMA technicals as live. Now flagged `worthless`, technicals nulled +
  marked stale, warning "delisted/worthless — verify & write off".
- **Analyst target upside** was frozen at analyst-fetch time (SPCX "−14.8% to target" off a stale pre-spike
  price). Now recomputed against the LIVE price in `_card_enrichment`.
- **Regime ↔ VIX coherence** — the classifier could declare `high_volatility` off a gap-volatility proxy
  alone while VIX was calm (operator saw "high volatility 43%" with VIX ~16). A VIX-coherence guard now
  dampens the gap-only high-vol score when the VIX signal is low/normal.

**SIEM stop-echo de-noise** — `_system_siem_dashboard` re-ingested `notification_log` (our own outbound
Telegram messages) at source severity, so every stop alert we SENT counted as a P1 `STOP_TRIGGERED` event
(38/1 group). Echoes are now demoted to **P3** + tagged `echo:true` + separate dedupe group (every P0–P2 is
detected upstream first). Reminder: stops on Schwab/Fidelity holdings are **advisory only** (no trading API),
not executed orders.

**Weekend-aware staleness** — the orchestrator's 26h staleness page fired on the expected Fri→Sun
market-closed gap. Threshold now extends **+24h per weekend calendar date** in the gap (61h weekend gap
suppressed; a real 97h outage still fires).

### Daily Intelligence Workflow (End-to-End)

This is the complete day-in-the-life showing how data flows from raw ingestion through agent analysis, LLM curation, and back into smarter searches:

```
5:00 AM ─ Alex daily retirement scan
5:30 AM ─ Agent outcome scorer (grade yesterday's recommendations)
6:00 AM ─ Credential monitor + previously traded watchlist
6:30 AM ─ NEWS INGESTION (Yahoo RSS, Finnhub, Seeking Alpha, Google News)
          └→ ~40-60 articles ingested → auto-approved for RAG
6:30 AM ─ SOCIAL INGESTION (StockTwits, Reddit)
          └→ ~100-200 posts with sentiment scored at ingest
6:45 AM ─ Topic ingestion (gap-fill mode: only topics with <3 articles)
6:50 AM ─ RAG indexer (embed new news, transcripts, social posts)
7:00 AM ─ SENTIMENT PROCESSOR (score all unscored articles)
          └→ Lexicon analysis: positive/negative/neutral + confidence
7:00 AM ─ TOPIC CURATOR (the learning engine):
          ├─ [1] Rate pending content (LLM decides: approved/low_quality/blocked)
          ├─ [2] Extract entities (LLM finds tickers/topics → content_entity_links)
          ├─ [3] Improve queries (LLM reviews what was found → generates better queries)
          ├─ [3b] AUTO-INGEST with improved queries (runs topic_ingestion --use-llm-queries)
          ├─ [4] RAG re-index (embed newly approved content)
          └─ [5] Fire agent events (TOPIC_INTELLIGENCE → notify relevant agents)
7:15 AM ─ SIGNAL FUSION (fuse catalyst + news + social + sentiment per symbol)
          └→ Strategy-weighted composite: e.g. defense_thesis weights catalyst 0.45
8:10 AM ─ Incubator LLM screener (grade top candidates A-F, PROMOTE/HOLD/DROP)
8:15 AM ─ Daily incubator refresh (update scores, RVOL, catalyst freshness)
8:20 AM ─ INCUBATOR PROPOSAL PROMOTER (promote grade A/B candidates to proposals)

─── MARKET HOURS (9 AM - 4 PM) ───

Every 15 min:
  ├─ Event detector → agent_event_queue (STOP_TRIGGERED, RSI_EXTREME, etc.)
  ├─ Agent event router:
  │   ├─ CONTENT_GAP → auto-search + ingest + sentiment + RAG + re-analyze
  │   ├─ RESEARCH_MORE → demand-driven search loop
  │   └─ Other events → route to appropriate agents
  └─ Process agent jobs (Maria, Steph, Risk analyze symbols with 12-layer context)

12:00 PM ─ Sentiment processor (midday refresh)
12:15 PM ─ Signal fusion (midday refresh)
12:30 PM ─ News ingestion (midday)
12:35 PM ─ Social ingestion (midday)

─── EVENING (6-10 PM) ───

6:00 PM ─ Incubator LLM screener (evening batch)
6:00 PM ─ Incubator rolloff (remove stale candidates)
6:10 PM ─ Proposal promoter (evening promotion)
7:00 PM ─ YouTube transcript ingest (all 48 tracked channels)
8:00 PM ─ Overnight batch + SEC data ingest

─── OVERNIGHT ───

Agent jobs continue processing (25 per 5 min)
RAG re-indexer (agent results + synthesis, 8h cadence)
Agent outcome scorer and learning governance update calibration
```

### LLM Curation Schedule (When Does It Get Smarter?)

| When | What Happens | LLM Used |
|------|-------------|----------|
| **7:00 AM daily** | topic_curator rates pending content (approved/low_quality/blocked) | gemma3:12b (~15s per article) |
| **7:00 AM daily** | topic_curator extracts tickers + topics → content_entity_links | gemma3:12b |
| **7:00 AM daily** | topic_curator improves queries: reviews last week's articles, generates 4 targeted news + 4 video queries per topic, tailored to John's situation | gemma3:12b |
| **7:00 AM daily** | Auto-ingests with improved queries (step 3b → topic_ingestion --use-llm-queries) | N/A (search APIs) |
| **8:10 AM + 6 PM** | Incubator LLM screener grades candidates — strategy-aware: 4 prompt groups (income, growth, reversion, momentum default). Income/reversion not penalized for low RVOL | gemma3:12b |
| **On CONTENT_GAP** | Agent event router auto-triggers: topic search → news search → sentiment score → RAG re-index → re-queue analysis | gemma3:12b (agent re-analysis) |
| **On RESEARCH_MORE** | Multiple agents say "need more data" → synthetic CONTENT_GAP → full search loop | gemma3:12b |
| **5:30 AM daily** | Outcome scorer grades past recommendations (CORRECT/PARTIAL/WRONG) → calibration update | N/A (rule-based) |
| **Sunday 6 AM** | Iris hygiene: demote stale content, detect superseded regulatory data | N/A (rule-based) |
| **Sunday 7 PM** | Weekly incubator rebuild with LLM multi-strategy classification | gemma3:12b |

### Query Improvement Example (How the System Learns)

The LLM reviews what was found last run and generates increasingly targeted queries:

**Static queries (original):**
```
"SSDI benefits update 2026"
"social security disability income limits"
```

**LLM-improved queries (after learning John's situation):**
```
"Roth conversion strategies for SSDI beneficiaries with $40K income and MFS filing in New York"
"2026 IRMAA income thresholds for SSDI recipients and Roth conversion planning"
"How MFS filing affects IRMAA lookback for Medicare beneficiaries starting in 2026"
"Safe Dividend Stocks for SSDI Recipients: 4-8% Yield Without IRMAA Risk"
```

The curator stores these in `topic_monitor.llm_generated_queries` and auto-runs ingestion with them. Each daily cycle produces more targeted results.

---

## 5.5 Self-Healing Data Gap Orchestration

The system identifies its own knowledge gaps and dispatches workers to close them autonomously before the next overnight intelligence run.

### Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `data_gap_registry` table | PostgreSQL | Structured tracking of every detected gap |
| `_extract_and_register_gaps()` | `run_deep_overnight_llm_queue.py` | Parses every gemma3 output for explicit `data_gaps` + 7 implicit patterns |
| `data_gap_resolver.py` | `scripts/` | Hourly worker that dispatches resolution actions |
| `gap_resolution_outcomes` table | PostgreSQL | Measures whether resolutions improved next-day output |

### Gap Types Detected

| Type | Trigger | Resolution Action |
|------|---------|-------------------|
| `missing_div_yield` | "dividend yield is none" in response | Force enrichment refresh |
| `missing_sector` | "sector unknown" or "sector: none" | Force enrichment refresh |
| `missing_market_data` | "rvol unavailable", "rsi unavailable" | Force enrichment refresh |
| `missing_catalyst` | "needs more data", "wait for catalyst" | Dispatch Maria research job |
| `missing_setup_details` | "setup information missing" | Reconstruct from paper_trades + proposals |
| `missing_thesis` | "original thesis unknown" | Recover from paper_trade_proposals |
| `stale_news` | "no recent news" | Trigger news ingestion priority refresh |

### Cron Schedule

| Time | Frequency | Purpose |
|------|-----------|---------|
| 10:00–16:00 ET | Hourly M–F | Close gaps during market hours |
| 18:00 ET | Daily M–F | Pre-overnight sweep before 23:00 queue |
| Sun 08:00 | Weekly | Audit persistent unresolvable gaps |

### Workflow

```
gemma3 output → _extract_and_register_gaps() → data_gap_registry (open)
    → hourly resolver dispatches: enrichment / Maria research / thesis recovery
    → gap marked 'resolved' → source job re-queued at P1:80
    → next overnight produces better answer with enriched data
```

### Dashboard Surface

`/v2/overnight` Data Gap Intelligence section: open/enriching/resolved/abandoned counts with per-type symbol breakdown. API: `gap_stats` and `gap_summary` in `/api/v2/overnight-dashboard`.

---

## 5.6 Three-Tier Alert Architecture

Replaces ~50 Telegram messages/day with ~12 actionable messages. Every Telegram notification must require action or contain delta intelligence.

### Tiers

| Tier | Behavior | Count |
|------|----------|-------|
| URGENT | Telegram immediate, 24h dedup per symbol+condition, escalate on worsen | 7 types |
| DIGEST | Aggregated into morning (8 AM) or evening (4 PM) brief | 6 types |
| DASHBOARD_ONLY | No Telegram, visible at /v2/alerts | 4 types |

### Key Components

| Component | Purpose |
|-----------|---------|
| `alert_dispatcher.py` | Central classifier with dedup, fatigue detection, rate limiting |
| `send_alert_digest.py` | Morning/evening consolidated Telegram briefs |
| `alert_dispatch_log` table | Every classification + action decision |
| `digest_queue` table | Aggregated alerts pending next digest |
| `/v2/alerts` page | Dashboard view of sent/suppressed/queued/dashboard-only |
| `/api/v2/alerts-dashboard` | API for alert volume and classification data |

### Cron Schedule

| Time | Script | Purpose |
|------|--------|---------|
| 8:00 AM ET M-F | send_alert_digest.py morning | Morning consolidated brief |
| 4:00 PM ET M-F | send_alert_digest.py evening | Evening consolidated brief |

---

## 6. External Research & Signal Ingestion

### Active Data Sources

| Source | API / Method | Data Type | Query Frequency | Fallback |
|--------|-------------|-----------|----------------|----------|
| **Finviz Elite** | HTTP scrape (cookie + API token) | Screener results, 60+ enrichment fields | 7x daily (07:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00 M-F, flock-protected) | None -- primary screener, manual cookie refresh required |
| **NewsAPI** | REST API (key) | News articles, headlines | 2x daily (06:30, 12:30) + on-demand | Finnhub news fallback |
| **Finnhub** | REST API (key) | News, company filings, insider activity | On enrichment trigger | NewsAPI fallback |
| **Polygon** | REST API (key) | Market data, quotes, corporate events | On catalyst enrichment | Yahoo Finance |
| **FMP (Financial Modeling Prep)** | REST API (key) | Fundamentals, earnings, financial statements | On catalyst enrichment | AlphaVantage |
| **AlphaVantage** | REST API (key) | Fundamentals, economic indicators | On enrichment | FMP fallback |
| **Yahoo Finance (yfinance)** | Python library | OHLCV, quotes, dividends | Indicator refresh (5:45 AM), on-demand | Polygon |
| **FRED** | REST API (key) | Federal Reserve economic data (rates, CPI, employment) | Daily (6 AM) | Cached last-known values |
| **SEC EDGAR** | REST API (public) | Form 4 insider filings | Daily (8 PM) | Skip -- non-critical |
| **YouTube Transcripts** | `youtube-transcript-api` | Video transcripts for financial analysis | Monthly discovery + daily channel scan | Skip -- supplementary |
| **Alpaca** | REST API (key) | Paper trade execution, fills, positions | On execution + reconciliation | Manual fallback |
| **Ollama (local LLM)** | HTTP (:11434) | Classification, review, health checks | Continuous (toll-gated) | Cloud LLM cascade |
| **Brave Search** | REST API (key) | News search for topic ingestion | On topic ingestion | DuckDuckGo fallback |
| **Google News RSS** | RSS feed | Topic-targeted news articles | On topic ingestion | Brave Search |
| **DuckDuckGo** | HTML scrape | News search fallback | On topic ingestion | None |
| **StockTwits** | REST API | Social sentiment, post volume | 2x daily (6:30 AM, 12:35 PM) | Reddit only |
| **Reddit** | REST API | Social discussion, sentiment | 2x daily (6:30 AM, 12:35 PM) | StockTwits only |
| **2Captcha** | REST API (key) | CAPTCHA solving for protected sites | On-demand when blocked | Skip site |

### 2Captcha Integration

**API Key:** `.env` → `TWOCAPTCHA_API_KEY`

2Captcha enables automated data collection from sites that block scrapers with CAPTCHAs. The system can solve:

| CAPTCHA Type | Supported Sites | Use Case |
|-------------|-----------------|----------|
| **reCAPTCHA v2/v3** | Seeking Alpha, TipRanks, Glassdoor, SEC EDGAR (rate-limited) | Article scraping, analyst ratings, insider filing deep-dive |
| **hCaptcha** | Finviz (when rate-limited), Discord (social scraping) | Screener data when cookies expire, social sentiment from Discord |
| **Cloudflare Turnstile** | Many financial news sites, MarketWatch, Barron's | Premium article access, paywall-adjacent content |
| **Image CAPTCHA** | Legacy financial sites, government portals | SSA.gov data, state regulatory filings |
| **FunCaptcha** | LinkedIn (company data) | Executive changes, hiring signals |
| **GeeTest** | Some Asian market data providers | International ETF/ADR data |

**Integration pattern** (for any ingestion script):
```python
import os, requests

def solve_captcha(site_url, site_key, captcha_type="recaptcha_v2"):
    api_key = os.getenv("TWOCAPTCHA_API_KEY")
    if not api_key:
        return None  # skip — no captcha solving available

    # Submit captcha task
    resp = requests.post("https://2captcha.com/in.php", data={
        "key": api_key, "method": "userrecaptcha",
        "googlekey": site_key, "pageurl": site_url,
        "json": 1
    }).json()

    task_id = resp.get("request")
    # Poll for solution (typically 10-30 seconds)
    for _ in range(30):
        time.sleep(5)
        result = requests.get(f"https://2captcha.com/res.php?key={api_key}&action=get&id={task_id}&json=1").json()
        if result.get("status") == 1:
            return result["request"]  # solved captcha token
    return None
```

**Target sites for enhanced ingestion:**

| Site | Data Value | CAPTCHA Type | Priority |
|------|-----------|-------------|----------|
| **Seeking Alpha** | Premium analyst reports, earnings call transcripts | reCAPTCHA v2 | High -- fills content gaps in Alex agent research |
| **TipRanks** | Analyst consensus, price targets, smart score | reCAPTCHA v2 | High -- enriches proposal quality scoring |
| **Finviz** (rate-limited) | Screener when cookie expires | hCaptcha | Medium -- backup for primary screener |
| **MarketWatch** | Premium articles, options flow | Cloudflare | Medium -- broadens news sentiment coverage |
| **Barron's** | Premium analysis, portfolio strategy | Cloudflare | Low -- supplementary for Alex agent |
| **SEC EDGAR** (heavy load) | Bulk insider filing analysis | reCAPTCHA | Low -- only when bulk-downloading |

**Cost:** ~$2-3 per 1,000 CAPTCHAs solved. At current ingestion volume, estimated $5-10/month.

### Why Each Source Is Used

| Source | Signal Provided | Impact if Unavailable |
|--------|----------------|----------------------|
| Finviz Elite | Volume/gap/float screener hits -- **the primary candidate discovery mechanism** | No new candidates surface. Pipeline stalls at Group 1. |
| News APIs (4 sources) | Market-moving events, catalyst verification, sentiment | Catalyst scoring degrades; proposals lack event context |
| Fundamentals (FMP/AV) | Earnings, revenue, debt ratios | Strategy filters using fundamental data produce false negatives |
| Yahoo Finance | OHLCV for 17 technical indicators | Indicator engine outputs stale; confluence scores unreliable |
| FRED | Macro context (rates, unemployment, CPI) | Macro overlay strategies (sector rotation, bond income) lose context |
| SEC EDGAR | Insider buying/selling signals | Insider signal absent; non-blocking for most strategies |
| YouTube Transcripts | Earnings call language, forward guidance | Alex agent income analysis loses qualitative depth |
| Social (StockTwits + Reddit) | Retail sentiment, volume spikes, emerging narratives | Social fusion signal degrades; momentum strategies lose edge |
| Alpaca | Order routing, fill confirmation | Execution halted; proposals queue without fills |
| Local LLM | Classification, critique, health checks | Falls back to cloud LLM (higher cost, higher latency) |
| 2Captcha | Access to CAPTCHA-protected financial sites | Skip protected sites; reduced coverage for premium content |

### Source Availability Handling

```
if source.available:
    ingest(source.data)
    update_freshness(source, now())
elif source.captcha_blocked and TWOCAPTCHA_API_KEY:
    token = solve_captcha(source.url, source.site_key)
    ingest(source.data, captcha_token=token)
elif source.has_fallback:
    ingest(source.fallback.data)
    log_degraded(source)
    alert_operator(source, "degraded")
else:
    use_cached_last_known(source)
    if staleness > source.max_stale_hours:
        alert_operator(source, "stale")
        mark_dependent_stages("degraded")
```

Every source has a `max_stale_hours` threshold. When exceeded, the `pipeline_watchdog` fires a Telegram alert and marks dependent pipeline stages as degraded.

### Research Architecture (Stub -- Not Yet Implemented)

The following integrations are **architecturally designed but not yet live**:

| Integration | Purpose | Status |
|-------------|---------|--------|
| Google Programmable Search API | Broad web research for novel signals | Stub -- endpoint defined, no API key provisioned |
| Earnings transcript provider (e.g., Seeking Alpha, Motley Fool) | Structured earnings call analysis | Stub -- YouTube transcripts used as partial substitute |
| Alternative data feeds (satellite, credit card, app usage) | Non-traditional alpha signals | Planned -- not architectured yet |
| Real-time news streaming (WebSocket) | Sub-second news reaction | Planned -- current batch polling at 2x/day |

When these stubs are activated, they will integrate at the **Group 1 (Data Collection)** and **Group 2 (Enrichment)** pipeline stages.

---

## 6b. Topic Intelligence System (Closed-Loop)

The topic intelligence system discovers, ingests, curates, and links non-symbol research content (SSDI, trusts, sector analysis, etc.) using a closed-loop architecture where each iteration improves the next.

### Architecture

```
[1] INGESTION (topic_ingestion.py)
    17 topics from DB → LLM generates targeted queries →
    YouTube API → Google News RSS → Brave → DuckDuckGo →
    Saved Google search URLs reused → ALL results downloaded
         |
         v
[2] CURATION (topic_curator.py) ← runs automatically after ingestion
    LLM rates: approved / low_quality / blocked →
    LLM extracts entities (tickers, topics, sectors) →
    content_entity_links table connects to existing DB records →
    LLM generates improved queries for next run →
    Triggers RAG re-index of approved content
         |
         v
[3] RAG INDEX (rag_indexer.py)
    Approved content → embeddings → agents consume via RAG
         |
         v
[4] AGENT CONSUMPTION (rag_retrieval.py)
    Agent asks about NVDA → gets topic_intel from entity links →
    Alex gets SSDI articles, Maria gets AI datacenter research
         |
         v
[5] FEEDBACK LOOP (topic_curation_feedback)
    Tickers extracted → Queries that worked → Better queries next run
```

### 2026-06-20 — Grounded + graded research, source lifecycle, continuous freshness

The closed loop now extends from topics through **web-grounded, garbage-filtered briefings** and a **rated
website registry**. Full detail: **`HERMES_RESEARCH_LIFECYCLE_AND_SOURCE_RATINGS.md`**.

- **Topic count: 140+** (operator Telegram adds auto-route to BOTH ticker-discovery *and* knowledge
  research; planning topics get operator context + Steph ownership).
- **DOES BOTH (web + LLM):** `topic_research_synthesizer.py` grounds each LLM briefing on the crawler's
  real articles (`symbol=topic_id` / keyword fallback) and **catalogs the sites used** into
  `hermes_research_intelligence.evidence_json.grounded_on`. `--reground` upgrades memory-only rows to
  source-cited once the crawler has ingested the topic.
- **Grade out garbage:** grounding only uses **graded-good** articles (excludes `low_quality`/`blocked`/
  demoted). `topic_curator.py` now runs on a **standalone cron (09:30/13:30/18:30)**, not just the
  post-ingestion trigger, so the grading backlog is drained independently.
- **Find/catalog new sites + ratings (autonomous, no human flip):** `hermes_source_curation.py` maintains
  `research_sources` (~97 active / 352 total). Track A auto-promotes domains by **yield** (≥2 outputs,
  ≥30%) and auto-retires dead ones; Track B has an **LLM validate** first-seen domains (free lane) and
  auto-activate credible ones immediately — spam auto-rejected, verdicts cached. Website lifecycle
  first-seen→LLM-validated/yield-proven→active→decay→auto-retire runs hands-off.
- **Throughput:** `topic_ingestion.py --max-topics N` + a 2nd 13:00 crawl so 120+ new topics are crawled
  (newest-first) within days, not weeks.
- **Surface:** RetirementHub → Planning Research tab (6 themes, vetted source chips, provenance count) via
  `GET /api/v2/retirement/planning-research`.

### 2026-06-21 — Layer-4 inference/synthesis engine activated

The research pipeline now feeds a cross-source **inference engine** (`scripts/inference_*.py`, full detail in
**`INFERENCE_LAYERS_LAYER4.md`**). A flock-guarded cycle (weekday 08:00/13:00/16:30) fuses news + market
regime + cross-market regional signals (Asia/Europe/EM → US) + portfolio + CEF/ETF NAV premium/discount into
auditable `inference_results` (with reasoning traces), advisory-only, free LLM lanes only. News is region-
tagged first (`region_tag_news.py`, cheap keyword pass — backfilled 3,964 articles, 255 Asia). Surfaced at
`GET /api/v2/inference/*`. Was built standalone but uncommitted/dormant; now committed, scheduled, and wired.

### DB Tables

| Table | Purpose |
|-------|---------|
| `topic_monitor` | 17 topics with queries, saved URLs, personal context, LLM-generated queries |
| `content_entity_links` | Links articles/transcripts to tickers, topics, sectors |
| `blocked_content` | Items never re-downloaded (LLM or operator blocked) |
| `iris_library_gap_fills` | Search attempt log (source, query, results, saves) |
| `topic_curation_feedback` | Learning loop: improved queries, quality notes, tickers found |

### Active Topics (17)

| Priority | Topic | Agent | Content Type |
|----------|-------|-------|-------------|
| P1 | Disability Retirement | Alex | SSDI, benefits, planning |
| P1 | SSDI Benefits | Alex | Benefits updates, limits, rules |
| P1 | SSDI Cash & Asset Shielding | Alex | Asset protection, trusts, ABLE accounts |
| P2 | AI Data Center Build-Out | Maria | Infrastructure, power, cooling, GPUs |
| P2 | IRMAA Medicare Surcharge | Alex | Medicare premiums, income thresholds |
| P2 | Roth Conversion Strategy | Alex | Tax brackets, conversion planning |
| P2 | Top Yield & Dividend Stocks | Steph | High yield, BDCs, CEFs, monthly income |
| P2 | Trust & Estate Planning | Alex | Special needs trusts, ABLE, Medicaid |
| P3 | AI Chip & Materials Layer | Maria | Semiconductors, HBM, packaging |
| P3 | AI Networking Layer | Maria | InfiniBand, optical, switches |
| P3 | Covered Call Income | Steph | CC strategies, ETFs, premium income |
| P3 | Defense Sector Thesis | Maria | Defense budget, AI military |
| P3 | Dividend Income Strategy | Steph | Dividend growth, aristocrats |
| P3 | Emerging Sectors by Sentiment | Aegis | Sector rotation, momentum |
| P3 | Top Swing Trade Setups | Steph | Breakout, momentum, gap setups |
| P4 | Bond & Interest Rate | Steph | Treasury yields, rate forecast |
| P5 | Tax Loss Harvesting | Alex | Wash sale, year-end strategies |

### Search Cascade (per topic)

1. **Saved Google search URLs** → extract query → YouTube API search (10 results each)
2. **YouTube Data API v3** → search + transcript fetch (4-method: cookies, API, timedtext, yt-dlp)
3. **Google News RSS** → free, 10 results per query
4. **Brave Search News** → if API key active
5. **DuckDuckGo HTML** → last resort, no key needed

### Entity Linking

When content has no ticker, it links by topic/sector/concept:
- SSDI article → `entity_type='topic', entity_value='ssdi'`
- NVDA datacenter article → `entity_type='ticker', entity_value='NVDA'` AND `entity_type='sector', entity_value='ai_infrastructure'`
- Retirement planning → `entity_type='topic', entity_value='retirement_planning'`

Entity links enable cross-system queries: "Show me everything about NVDA" returns trade proposals AND topic intelligence articles.

### Access Points

| Channel | Path |
|---------|------|
| Command Center | `/v2/topic-monitor` |
| Telegram | `topic status`, `topic add`, `topic url`, `topic run` |
| API | `/api/v2/topics`, `/api/v2/topics/by-ticker/{TICKER}`, `/api/v2/topics/entities` |
| Agents | Automatic via RAG + entity links + agent_event_queue |

### Daily API Cost

| Source | Calls/Day | Cost |
|--------|-----------|------|
| YouTube Data API v3 | ~34 searches (3,400 of 10,000 free quota) | Free |
| Google News RSS | ~51 fetches | Free |
| YouTube transcript API | ~50 transcripts | Free |
| Brave Search (if renewed) | ~34 queries | ~$0.17/day ($5/mo) |
| Local LLM (curation) | ~67 calls, ~17 min GPU | ~$0.02 electricity |
| Cloud LLM fallback | Rare | ~$0.01/day |
| **Total** | | **Free-$0.20/day** |

### Cron Schedule

| Time | Script | Purpose |
|------|--------|---------|
| 6:45 AM M-F | `topic_ingestion.py --gaps-only --no-llm` | Fill gaps, fast |
| 7:00 AM M-F | `topic_curator.py --improve-queries` | Rate, extract, link, improve |
| 8:00 PM Sunday | `topic_ingestion.py` | Full run, all topics, with LLM |

---

## 7. Screener System

- **Source:** Finviz Elite (requires active subscription + cookie)
- **Config:** `assets/screeners.yaml`
- **Authentication:** Dual method (cookie for scraping + API token for API calls)

### Active Screeners

| Screener | RVOL | Gap | Price | Float |
|----------|------|-----|-------|-------|
| `prime_setups` | >5x | >10% | $2-$20 | <50M |
| `watchlist_setups` | >3x | >5% | $1-$30 | <100M |

### Run Windows

| Window | Time | Purpose |
|--------|------|---------|
| 1 | 04:00 AM | Pre-market scan (European hours) |
| 2 | 07:00 AM | Pre-market US hours |
| 3 | 09:00 AM | Market open |
| 4 | 10:00 AM | Post-open consolidation |

---

## 8. Strategy Engine

All 22 strategies are loaded dynamically from `config/strategies/*.yaml` at runtime. There are no hardcoded strategy lists anywhere in the codebase. Each YAML includes `vix_rules`, `technical_indicators_required`, and `performance_context` blocks.

### Strategy Classification Flow

```
Symbol from screener/incubator
    |
    v
Phase 1: Deterministic Filters
(screen_filters from YAML + enrichment data)
    |
    +-- match --> Assign matched strategies
    |
    +-- no match --> Phase 2: LLM Classification
                     (gemma3:12b thesis-driven)
                         |
                         v
                     Assign thesis-driven strategies
    |
    v
Multi-Strategy Assignment
(single symbol can match multiple strategies)
    |
    v
Write to incubator_universe
```

### Strategies by Timeframe

| Timeframe | Strategies |
|-----------|------------|
| **INTRADAY** | `gap_and_go`, `momentum_scalp` |
| **SHORT_SWING** | `earnings_catalyst`, `swing_breakout`, `swing_trade`, `speculative_growth`, `tax_loss_harvest` |
| **MEDIUM_SWING** | `recovery_watch`, `sector_rotation` |
| **POSITION** | `income_add`, `core_growth_compounder`, `core_index`, `covered_call_income`, `defense_thesis`, `dividend_growth_compounder`, `high_yield_income_bdc`, `international_dividend`, `reit_income`, `bond_income` |
| **CASH** | `cash_or_stable` |

Each YAML strategy defines: entry criteria, risk parameters (position size, stop placement), scoring weights, exit rules, account eligibility, and co-enablement rules.

**14 of 24 strategies require LLM classification** (IV rank, dividend growth years, unrealized losses not available in the deterministic enrichment cache).

---

## 9. Incubator Pipeline

The incubator is the holding area between raw screener hits and actionable proposals.

### Stage Flow

1. **`weekly_incubator_builder`** (Sunday 7 PM) -- Pulls qualified tickers from `trade_ai_scans` (score >= 30, RVOL >= 3, catalyst verified). Classifies each against all 24 strategies.

2. **`daily_incubator_refresh`** (daily) -- Updates scores, RVOL, and catalyst freshness.

3. **`incubator_rolloff_engine`** -- Removes symbols that no longer meet criteria.

4. **`incubator_llm_screener`** (NEW) -- Pre-promotion LLM screening for quality control.

5. **`incubator_proposal_promoter`** (every 2h: 9,11,13,15,17 M-F) -- Promotes qualifying symbols. Auto-expires stale proposals first.

### Promotion Criteria

| Condition | Requirements |
|-----------|--------------|
| High-conviction | `status=ACTIVE`, `score >= 38`, `catalyst_verified = true`, `days_active >= 1` |
| Score override | `status=ACTIVE`, `score >= 45`, `days_active >= 1` |

### Auto-Expiry Rules (runs before each promotion cycle)

| Rule | Condition | Result |
|------|-----------|--------|
| No action | PENDING >3 days, no approval/rejection | EXPIRED |
| Past expiry | `expires_at` < NOW | EXPIRED |
| Price drift | PENDING >2 days AND price moved >8% from entry | EXPIRED |

### Promotion Gate
- Global ceiling: 20 PENDING proposals max
- Per-strategy: max 5 per strategy_id (concentration check)
- Per-symbol: max 1 per strategy group (MOMENTUM/INCOME/GROWTH/REVERSION), max 2 total
- Penny stock filter: skip symbols with price <$1.00
- Stop breach: auto-expire if current_price <= proposed_stop
- RSI gate: blocks RSI>=80 momentum, RSI>=75 swing at promotion. Income/recovery exempt.
- RSI auto-expiry: Rule 5 expires PENDING proposals where RSI>=80 on every cycle
- If 3+ strategies all at cap, blocks further promotion

---

## 10. Proposal Lifecycle & Automated Execution

### Lifecycle Flow

```
[PROPOSED] ──→ [ENRICHING] ──→ [RISK_CHECK] ──→ [PENDING]
                                                     │
                    ┌────────────────────────────────┤
                    │                                │
               [APPROVED]                       [REJECTED / RISK_BLOCKED / EXPIRED]
                    │
                    │ ← INSTANT (same HTTP request, no cron delay)
                    ▼
            [ALPACA SUBMISSION]
                    │
        ┌───────────┼───────────┐
        │           │           │
   [MARKET]    [LIMIT]    [BRACKET]
   (immediate)  (wait)    (limit+stop+target)
        │           │           │
        ▼           ▼           ▼
     [FILLED]  [PENDING_FILL] [PENDING_FILL]
        │                       │
        ▼                       ▼
     [OPEN] ←──────────────────┘
        │
        │  ← paper_trade_monitor.py (every 5 min)
        │     adjusts stops, checks targets
        ▼
     [CLOSED]
     (target hit / stop hit / manual close)
```

**Key principle:** Approval triggers immediate execution. There is no human step between approval and Alpaca order submission. The system determines order type, parameters, and routing automatically.

### Order Type Selection Logic

The system selects order type at submission time based on current market conditions:

```
alpaca_paper_adapter.py → submit_entry()
    │
    ├─ HARD BLOCK: price ≤ stop             → BLOCKED (stop_breached)
    │   (Would immediately stop out)           Order never submitted
    │
    ├─ HARD BLOCK: drift > 5%               → BLOCKED (excessive_drift)
    │   (Stale proposal, too far from plan)    Order never submitted
    │
    ├─ Current price ≤ proposed entry       → MARKET ORDER
    │   (Better price available — fill now)
    │
    ├─ Current price within 2% of entry     → MARKET ORDER
    │   (Close enough — avoid missing setup)
    │
    └─ Current price >2% above entry        → LIMIT ORDER (bracket)
        (Price drifted — wait for value)       limit buy + stop loss + take profit
```

**Hard blocks** prevent the BLBD incident (May 12, 2026): a 4-day-old proposal at $80.24 entry/$76.23 stop was submitted when price was $68. The buy filled at $68.48 (below stop) and the stop triggered immediately. Both the revalidator and adapter now independently block this scenario.

**Approved ≠ Executed.** Approval triggers validation, but execution is conditional on passing all gates. A stale or drifted proposal will be blocked even after approval.

### Approval-Time Revalidation

When John approves a trade, `approval_revalidator.py` → `validate_at_approval()` runs **immediately** before the proposal enters the execution pipeline. This is separate from the execution-time revalidator — it runs at decision time, not submission time.

**Implemented in:** `approval_revalidator.py` → `validate_at_approval()`, called from `api_v2.py` POST `/api/v2/approvals/decision`

| Check | Source | Fail Action |
|-------|--------|-------------|
| Stop breach (live price ≤ stop) | Alpaca live quote | **REJECTED** — approval reverted |
| Price drift > 10% | Alpaca vs proposed_entry | **REJECTED** |
| R:R ratio < 1.5 (with live price) | Computed from live price/stop/target | **REJECTED** |
| Strategy YAML criteria | `config/strategies/{id}.yaml` | **REJECTED** per specific disqualifier |
| Proposal staleness | `created_at` vs timeframe_class threshold | **REJECTED** (intraday: 2h, swing: 72h) |
| Past trade losses | RAG query for `trade_outcome` embeddings | Warning surfaced to user |
| Price drift > 5% | Alpaca vs proposed_entry | Warning + shares recalculated |
| Price drift > 2% | Alpaca vs proposed_entry | Shares recalculated to maintain dollar risk |
| **RSI overbought** | ticker_snapshot_daily RSI >80 (momentum strategies) | **REJECTED** |
| RSI elevated | RSI >72 (momentum strategies) | Warning |
| **RVOL collapsed** | Current RVOL <1.5x (momentum strategies) | **REJECTED** |
| RVOL fading | Current RVOL <40% of original scan | Warning |
| Catalyst stale | Time-sensitive catalyst >48h old | Warning |
| VWAP extended | Price >5% above VWAP (intraday strategies) | Warning |
| Negative news | >2 negative articles since proposal creation | Warning |

**Strategy YAML criteria enforced** (from `config/strategies/*.yaml`):
- Price range (min/max per strategy)
- RVOL minimum
- Float maximum
- Signal score minimum
- Catalyst requirement (present/verified)
- Account eligibility and forbidden accounts
- Auto-disqualifiers (e.g., AFTER_130PM, WIDE_SPREAD, DILUTION_RISK)

If validation returns REJECTED, the approval is reverted to pending and the user sees the blockers in the UI response.

**Agents query past trade outcomes during proposal review.** Both `proposal_agent_review.py` and `proposal_intelligence_analyzer.py` inject RAG-retrieved trade history into their LLM prompts. If FLYW lost money as a swing_trade, the next FLYW swing proposal prompt explicitly tells agents about that loss.

**Market orders:** Simple buy → immediate fill → **stop recalculated if fill < proposed entry** → stop placed as separate GTC order after fill.
If fill price is below the proposed stop (stop would be above entry), the adapter recalculates stop to 5% below actual fill price. This prevents the stop-above-entry scenario that left GCTS unprotected on 2026-05-13.
Post-fill, the monitor takes over position management (trailing stops, auto-close on stop/target hit).

**Sync position promotion:** `sync_positions` detects Alpaca-filled trades stuck at `status='pending'` and promotes them to `'open'` with correct fill price. Also recalculates stop if above fill.

**Broker as source of truth:** No `paper_trades` row is created until the broker confirms the fill. Unfilled limit orders return `{status:'pending'}` without creating a DB record. The `sync_positions` method detects fills on subsequent cycles and creates broker-confirmed records. The `broker_confirmed` column (`GENERATED ALWAYS AS (filled_at IS NOT NULL)`) gates all journal queries — phantom records never appear in profitability reporting.

The broker is authoritative across the whole reconciliation surface — a position exists **iff** the broker holds it, and is flat **iff** the broker is flat:
- **DB-open but broker-flat (phantom):** `paper_trade_monitor.py` integrity-check closes it with `close_reason='phantom_no_alpaca_position'` and **voids the P&L** (`pnl=0, pnl_pct=0, r_multiple=0, outcome_verdict='PHANTOM'`). A phantom was never a real round-trip, so it must never book a computed win/loss — doing so previously polluted the paper Closed-Trade Review (e.g. MRVL +$126, SNOW +$131 as bogus wins). Voided phantoms drop out of journal stats via the existing `pnl != 0` filter.
- **Broker-held but DB drift:** `alpaca_paper_reconciler.py --fix` overwrites DB `entry_price`, `shares`, and fill confirmation FROM the broker (never the reverse). Runs 09:35 & 16:05 on a schedule (not detect-only).
- **Broker-held but no open DB record (orphan):** the adapter sync materializes a broker-confirmed record (`unknown_sync`). The reconciler's `CLOSED_BUT_HELD` check only fires when the broker holds a symbol with **no** matching open DB trade — a closed record on a symbol that *also* has a current open record is just history, not a mismatch.
- **Protective-stop drift:** the broker's live sell-stop is the source of truth for the stop price/order-id too. The DB `stop_loss_price` column goes stale when the monitor hasn't trailed, so `alpaca_paper_reconciler --fix` syncs it from the broker (`STOP_DRIFT`) and raises `NO_BROKER_STOP` (HIGH) when a held position genuinely has no broker stop. (Display columns being stale once made a fully-protected position — TMHC with a live $68.02 stop — look naked.)

### Trade Integrity Audit — dual sign-off

`scripts/trade_integrity_audit.py` audits **every** trade with two independent signers and writes per-trade rows to `trade_integrity_audit`:
- **Trade AI (deterministic):** broker-confirmed, not-phantom (vs broker holdings), has-protection (checks the **broker's** live stop, not the stale DB column), P&L integrity, lineage, data-freshness. Read-only — never mutates trades.
- **Hermes (agent):** `paper_trade_multi_reviews` coverage; `--enqueue-hermes` requests reviews for unreviewed trades.

`dual_status` is **GREEN** only when Trade AI PASSes **and** Hermes has reviewed. Already-remediated phantoms (closed + voided) are marked `remediated` and excluded from active REDs so live problems stand out. Hard failures push to SIEM (P1). Cron: every 15 min market hours. Endpoint: `/api/v2/trade-integrity-audit`.

**Hermes review pipeline.** The agent reviews are produced by `scripts/multi_tier_trade_reviewer.py` (local LLM — gemma3:4b realtime / gemma3:27b overnight) and stored in `paper_trade_multi_reviews`. Only **closed** trades are reviewable. Coverage was stuck at ~36% because the per-trade tiers were never scheduled (only weekly/monthly were) and the audit's `--enqueue-hermes` wrote to a non-existent `agent_jobs` table. Fixed: `--enqueue-hermes` now invokes the real reviewer per unreviewed closed trade, and an **overnight reviewer cron (22:30 weekdays)** keeps coverage current. Coverage is measured over real closed trades (status=`closed`) — `cancelled` orders are not real round-trips and are excluded.

### Broker connectors & credential management

The `accounts` table carries an explicit `api_enabled` flag (Alpaca + Schwab = API accounts; Fidelity 401k = manual/no-API). Connectors implement one broker-agnostic interface (`get_account/get_positions/get_open_orders/submit_entry/sync_positions/get_status`); `scripts/validate_broker_connectors.py` is a side-effect-free harness validating each. **Only Alpaca is live API trading today**; Schwab/Tastytrade are programmed but awaiting live credentials, and were fixed to be account-aware (they previously hardcoded `accounts[0]`, broken for the 3 Schwab accounts).

Credential configuration has two surfaces:
- **v3 Admin → Brokers tab (read-only):** connectivity, validation, cred-presence booleans (no secrets), last sync. Endpoint `/api/v2/system/broker-connectors`.
- **`apps/broker-admin/` (Tier-2, secure):** the only place secrets are entered — localhost-bound, password-gated, CSRF-protected; writes `config/broker_credentials.env` (chmod 600, gitignored); adapters pick it up via `broker_secrets.load_into_env()` without overriding the main `.env`. The unauthenticated read-only dashboard never handles secrets.

### Broker-confirmation gate — phantom elimination (vendor-neutral)

Phantoms = journal rows that never confirmed at the broker. Root cause (diagnosed): (1) the `proposal_approved` path promoted `pending → open` matched by **symbol**, dropping the `broker_order_id`; (2) the `alpaca_sync` path wrote `open` rows with no order id. The clean `submit_entry` path (awaits fill, stamps order id) produced zero phantoms.

The fix is a single broker-neutral confirmation door — no path, for any broker, creates a COUNTED row without walking through it:
- **Contract:** `scripts/broker_adapter.py` defines the vendor-neutral `BrokerAdapter` (`submit_order/get_order_status/confirm_fill/get_positions/...`) and `adapter_for(account)` (resolves the broker from config, imports `broker_confirm_<broker>.py` by name). **Zero vendor literals** in the gate/verifier (grep-asserted); `alpaca` appears only in `broker_confirm_alpaca.py`.
- **Two-source verification:** `scripts/trade_fill_verifier.py` — TradeAI re-queries the order; **Hermes independently re-checks read-only**, writing verdicts only to `hermes_fill_verifications` (never mutates `paper_trades`). A row is COUNTED only if broker-proven AND both agree. `confirm_fill` catches order-linked-but-unfilled rows a naive "has order id" check misses (e.g. #29 NVDA).
- **STEP 3a (live):** `alpaca_paper_adapter.sync_positions` promotion is now **order-anchored** — a pending row becomes `open` only when matched to a specific filled broker order (capturing `broker_order_id`/`client_order_id`); otherwise it is left pending (no unanchored promotion, no `unknown_sync` duplicate). Forward-only; rewrites no history.
- **STEP 3b (live):** the live-trading-gate excludes integrity-flagged phantoms from its counting (see Live Trading Gate). Rule = **exclude-provably-fake** (keep real legacy/breakeven trades), reconciled against rigorous `confirm_fill` via `scripts/step3_reconcile_filter.py`.

**Limit orders:** Bracket order (buy + stop + target as legs). All legs submitted atomically.
If the limit buy doesn't fill by end of day (TIF=day), the order expires. The proposal
remains in PENDING state and will be re-evaluated by the execution sweep on the next
market day. If the proposal itself expires (per strategy timeframe), it transitions to EXPIRED.

**Quote source cascade for price check:**
1. Alpaca latest trade (`/v2/stocks/{symbol}/trades/latest`)
2. Alpaca latest quote bid/ask (`/v2/stocks/{symbol}/quotes/latest`)
3. yfinance fallback
4. If all fail → default to limit order at proposed entry (conservative)

**Order lifecycle states:**
```
SUBMITTED → NEW → PARTIALLY_FILLED → FILLED → (monitor takes over)
                                    → EXPIRED (limit not filled by EOD)
                                    → CANCELLED (user or system cancellation)
```

### Risk Gate (Pre-Submission)

Every proposal passes through `risk_gate.py` before execution:

| Check | Threshold | Fail Action |
|-------|-----------|-------------|
| Position size | Paper: $15K max (env configurable), Live: per strategy YAML | DOLLAR_SIZE_TOO_LARGE |
| Duplicate position | No open trade for same symbol | BLOCKED_DUPLICATE |
| Duplicate order | Idempotency check via client_order_id | BLOCKED_DUPLICATE_ORDER |
| Quality review | Not in BLOCKED_BY_RISK_GATE or REJECT_RECOMMENDED | BLOCKED_QUALITY |
| Live trading lock | ALPACA_MODE must be 'paper' | BLOCKED_LIVE_MODE |
| Data quality | Intel readiness > 50 (warning only) | LOW_INTEL (warning) |

### Execution-Time Revalidation

Before submitting to Alpaca, `paper_execution_revalidator.py` runs a final eligibility check using **live Alpaca quotes** (not stale DB data). The revalidator returns an `eligibility_status`: `ELIGIBLE`, `INELIGIBLE`, or `NEEDS_REVALIDATION`.

**Implemented in:** `paper_execution_revalidator.py` → `revalidate()`
**Quote source:** `get_current_quote()` → tries `market_quote_provider.fetch_alpaca_quote()` first, falls back to `trade_ai_scans` DB table.

| Check | Action |
|-------|--------|
| **Stop already breached** (price <= stop) | **Hard block** — instant INELIGIBLE, order never submitted |
| Market session (closed/premarket/afterhours) | Delay until regular hours |
| Recommendation staleness (vs strategy-specific threshold) | Delay or downgrade |
| Approval staleness | Delay if approved too long ago |
| Price drift >= 3% from proposed entry | Block, require re-approval (NEEDS_REVALIDATION) |
| Price drift >= 1.5% | Warning, score deduction |
| Risk/reward degraded > 50% | Block, require re-approval |
| Material changes since approval | Require re-approval |

The submitter persists the eligibility result to the proposals table:
- `execution_eligibility_status` (ELIGIBLE/INELIGIBLE/NEEDS_REVALIDATION)
- `execution_eligibility_reason` (human-readable)
- `live_price_at_execution` (Alpaca quote at validation time)
- `live_price_timestamp`

**Telegram alerts (Gap 6):** When revalidation returns `NEEDS_REVALIDATION` (material change or excessive drift), the submitter sends a Telegram alert with the original vs current price, drift %, recalibrated shares, and inline re-approval commands (`/approve updated paper entry {id}` or `/reject updated paper entry {id}`). Blocked submissions also trigger a Telegram alert with the block reason. This prevents silent stale submissions.

**Revalidation audit trail (Gap 7):** When a trade is submitted, the adapter persists the full revalidation snapshot to `paper_trades`: `revalidation_verdict`, `revalidation_score`, `revalidation_flags`, `price_at_approval`, `staleness_at_submit_min`. This enables the Automated Journal to show revalidation context without cross-table joins.

Freshness thresholds match strategy timeframe:

| Strategy Type | Staleness Threshold |
|--------------|-------------------|
| Scalp / gap_and_go | 30 minutes |
| Momentum / day trade | 60 minutes |
| Swing / swing_breakout | 3 days (4,320 min) |
| Earnings / sector rotation | 5 days (7,200 min) |
| Income / position / defense | 10 days (14,400 min) |

Staleness is checked against `approved_at` (when user acted), not `created_at` (when system generated).

### Adapter-Level Hard Safety Gates

Even if the revalidator passes, `alpaca_paper_adapter.py` → `submit_entry()` enforces two additional hard blocks as defense-in-depth:

**Implemented in:** `alpaca_paper_adapter.py` → `submit_entry()` (after current price fetch, before order submission)

| Gate | Condition | Result |
|------|-----------|--------|
| Stop breach | `current_price <= stop_price` | Order blocked, returns `stop_breached` |
| Excessive drift | `abs(current_price - entry_price) / entry_price > 5%` | Order blocked, returns `excessive_drift` |

The adapter accepts a `validated_price` parameter from the revalidator to eliminate the TOCTOU (time-of-check-to-time-of-use) gap. If the adapter's own price fetch fails, it uses the revalidator's validated price. The adapter also accepts a `revalidation_snapshot` parameter containing the full recheck result, which is persisted to `paper_trades` for journal audit trail (Gap 7).

### Stop Protection Verification & Tracking (Phase 190)

Protective stops are now **provable** from the DB, not just placed at the broker. Root cause of
the prior gap: `alpaca_sync` onboarded positions with no stop metadata, and the adapter's post-fill
stop path discarded the broker order id — so positions could be hedged at the broker yet appear
unprotected in the DB (and no monitor alerted).

**Protection metadata columns on `paper_trades`** (migration `migrations/2026_06_02_phase190_protection.sql`):
`stop_order_id`, `stop_verified_at`, `stop_verified_source`, `broker_stop_status`, `current_stop`,
`protection_status` (`PROTECTED_TRACKED` / `PROTECTED_UNRECORDED` / `NAKED`),
`protection_defect_reason`, `take_profit_order_id`, `profit_protection_status`, `trailing_active`,
`trailing_policy_version`, `last_broker_protection_check_at`.

| Component | File | Role |
|-----------|------|------|
| Broker stop verifier | `verify_paper_trade_broker_stops.py` | Reads Alpaca **paper** order book (GET-only), matches stop orders to open trades, persists `stop_order_id` + verification metadata. Never places/modifies/cancels orders. |
| Stop-confirmation fix | `alpaca_paper_adapter.py` → `submit_entry()` | Captures the `_api_post` stop response; records `stop_order_id` + note from **broker confirmation**, never from the `use_market` boolean. Unconfirmed → `STOP_SUBMITTED_UNCONFIRMED`; failed → existing close-unhedged path. |
| Protection defect detector | `protection_alerts.py` | Reads `paper_trades` (not brokerage JSON); detects naked / untracked / large-gain-no-TP / unverified-note; emits SIEM (`alert_events`, deduped 6h) + Telegram gate (`PROTECTION_ALERTS_TELEGRAM`). Invoked best-effort by `unified_stop_supervisor.py`. |
| Hermes protection surface | view `hermes_v_open_position_protection_context` + `hermes_open_position_protection_check.py` | Advisory findings (`open_position_no_broker_stop`, `broker_stop_exists_db_untracked`, `large_gain_no_take_profit`, `stop_note_unverified`, `protection_metadata_mismatch`, `stale_quote_blocking_protection_review`). |
| Dashboard endpoint | `api_v2.py` → `GET /api/v2/atm/protection-coverage` | Read-only protection coverage counts + defects-by-symbol for the ATM panel. |

**Lifecycle note:** premarket/pre-open proposals currently loop through delayed-revalidation
instead of being parked. A `PENDING_TRADING_WINDOW` lifecycle is **designed** (advisory analyzer
`pending_trading_window.py`); wiring into the approver is deferred to a later phase to avoid GO/WAIT
changes.

**Readiness/executor freshness alignment (2026-06-04):** `proposal_execution_readiness.py`
previously relaxed the quote-age ceiling to 24h for *all* strategy classes outside regular hours.
For **intraday** strategies (`momentum_scalp`, `gap_and_go`) this let a stale premarket quote
surface as `ACTIONABLE_READY`, only for the approver to reject it on click ("Need fresh market
data") — because the executor (`paper_trade_logger.py`, flat 15-min ceiling, no caller override)
never relaxes. The after-hours relaxation is now gated to **swing/position only** (`is_intraday`
guard derived from `get_timeframe_class`); intraday keeps its 300s ceiling year-round so readiness
can no longer show a green card the executor will reject. Swing/position after-hours pre-staging on
a day-old quote is unchanged.

**RTH-gate on intraday proposal GENERATION (2026-06-04):** the freshness fix above stops the false
green light but proposals were still *generated* premarket (04:00–09:00) on stale quotes, so they
expired or auto-rejected (price-drift / blocked-too-long) before the 9:30 open — a real GO signal
(e.g. XOS, FOFO on 2026-06-04) never became an approvable proposal. Fix: `auto_proposal_generator.py`
→ `run_auto_proposals()` now skips intraday signals (`momentum_scalp`, `gap_and_go` via
`get_timeframe_class`) when `current_market_session() != "regular"`, recording
`SKIPPED_OUTSIDE_RTH` in `auto_proposal_decisions`. They regenerate on the next `*/30 9-16` run on
live quotes. This single gate also covers the `catalyst_momentum_engine.py` premarket-scalp band,
which shells out to `auto_proposal_generator.py`. The incubator promoter is unaffected — its
`_CLASSIFICATION_STRATEGIES` excludes intraday. Swing/position generation is unchanged; `force=True`
(manual operator runs) bypasses the gate.

**Liquidity pre-screen on proposal GENERATION (2026-06-04):** the RTH-gate fixed *timing*, but the
screener still fed structurally untradeable microcaps (FOFO live spread 19.8% / 8.5K shares; BNKK
15% / 1.6K shares on 2026-06-04) that reached Telegram and were only rejected downstream by the
execution-readiness layer — pure operator noise. Root cause: `strategy_signals` carries no absolute
volume or spread (only `rvol`, a *ratio* — 22× a tiny base is still tiny), and no stored source is
reliable for thin names (`trade_ai_scans.volume` NULL, `market_quotes` has no row for FOFO/BWEN), so
a live quote is the only dependable liquidity source. Fix: `auto_proposal_generator.py` →
`run_auto_proposals()` step 2e calls `_liquidity_prescreen(symbol, rules)` after strategy-criteria
validation and before sizing (so it only quotes candidates that passed the cheap structural filters).
It blocks when the live `spread_pct` exceeds `max_spread_pct` (5.0), or when **both** the share floor
(`min_day_volume_shares` 25000) and the dollar floor (`min_dollar_day_volume` $100K) are breached,
recording `SKIPPED_LIQUIDITY` in `auto_proposal_decisions` (+ `liquidity_rejected` stat). Thresholds
live in `config/strategies/shared_risk_rules.yaml → liquidity_prescreen` (looser than the execution
layer's ~1% momentum spread on purpose — generation catches *structurally* untradeable, approval
stays the tighter backstop). **Fail-open by design:** outside regular hours, no quote, provider
error, or config-disabled → it never blocks (swing/position after-hours pre-staging unaffected;
`force=True` bypasses). Verified: blocks FOFO/BNKK/XOS on live quotes, passes AAPL; all fail-open
paths confirmed.

**Companion analysis — Hermes news → scalp catalyst (2026-06-04):** see
`docs/HERMES_NEWS_TO_SCALP_CATALYST_INTEGRATION_2026_06_04.md`. STEP 0 grounding found the
`news_articles → news_to_catalyst.py → catalyst_events` classifier is **dead since 2026-04-27**
(0 rows/7d), which silently starves `signal_fusion.py` (a live consumer of `catalyst_events`); the
live scalp-catalyst path is `catalyst_momentum_engine.py` (SearXNG + screener candidates, not
Hermes-discovered news); and Hermes already writes the shared Postgres
(`hermes_research_intelligence`, 421 rows/24h) so no Docker bridge is needed. **Prompt #1 repair
APPLIED 2026-06-04** (doc §12): root cause was a column-name mismatch in `news_ingestion.py`'s
inline catalyst write (silent `except:pass` inside a green job) plus an unscheduled classifier;
fixed both writers (deduped via a new unique index), re-wired `signal_fusion`, and added
`intel_table_staleness_monitor.py` so this silent-failure class is caught next time. See that doc
for the remaining integration options (Hermes bridge, tiered cadence).

**Profit-protection advisory (Phase 191, advisory-only):** beyond *does a stop exist*, the system
now evaluates *is the stop still appropriate given unrealized profit*. `profit_protection_advisory.py`
(TradeAI scoring) computes stop quality — profit locked, giveback if stopped, R vs the broker stop
when `planned_stop` is absent — and emits a per-trade action (`NO_ACTION` … `URGENT_PROTECTION_REVIEW`)
persisted to `atm_profit_protection_advisories`. `hermes_profit_protection_check.py` adds a Hermes
second opinion (loose-stop / giveback / no-take-profit / metadata-missing finding types). Surfaced via
`GET /api/v2/atm/profit-protection-advisory` for the inline ATM panel. **No stops moved / no orders
placed** — operator-approved execution is deferred to Phase 192.

**LLM stop/trailing advisory — family-aware, bounded, self-checked (2026-06-13):**
`holding_protection_advisor.py` produces a per-holding protective-stop + trailing recommendation on
the free **Grok OAuth** lane (local-gemma fallback; both free), surfaced on the Open Trades cards and
the Watchlist/Proposals exit ladders. Three reinforcing layers keep the advice honest:
1. **Tier WIDTH (dynamic since 2026-07-14)** — `holding_family.py` maps each holding to a stop tier
   from **`config/stop_policy.yaml`**: operator pin → `asset_classification_rules.json` bucket tags →
   **dynamic volatility tier** (`classify_volatility_tier`: beta / real ATR% / dividend yield /
   sector — vol_low 5–8%, vol_medium 8–11%, vol_high 9–13%; NO hardcoded symbols; daily
   `volatility_tier_refresh.py` cron 06:45 → `symbol_volatility_tiers` + state file) → ETF asset
   class → type/ATR fallback → default. Bounds are then adjusted (cap end only, never below
   `stop_min+0.5`) by **market regime** (`market_regime_snapshots`: risk-on widens the vol_high
   trail cap +1 pt; risk-off tightens all caps −1), **lifecycle stage** (watch −1 / trim −2) and
   **conviction size** (stock <$10k −1). Legacy families (momentum 2-6% … position 5-12%) remain
   valid tier keys. Full spec: [`docs/STOP_METHODOLOGY.md`](STOP_METHODOLOGY.md). A portfolio-level
   drawdown guard (90d peak, warn ≥10% / critical ≥12%) rides the stop-health cron.
2. **Bounded prompt** — stop must be below price, anchored at/below the 20d swing low, inside the
   family band, `stop_pct_below` = the computed value; **fixed-vs-trailing is a RULE**: trail only if
   unrealized ≥ +10% AND price > 50d SMA (income: ≥ +20%), else fixed; trail is **PERCENT-only** so
   units are never ambiguous. (The WHEN-to-tighten R-tiers stay in `strategy_trailing_policy.py`.)
3. **Sanity gate** — `_sanity_check()` validates every output against the real technicals + family
   bounds (stop-below-price=fail, claimed-vs-actual %, reachable-swing-low anchoring, distance/trail
   bands) → verdict ok/warn/fail stored in evidence, surfaced as "⚠ check advisory" / "⛔ unreliable
   advisory" on the card. Display renders from STRUCTURED fields ($ stop + trail shown as both $ and
   %), never a free-form string. **Advisory only — no stops moved / no orders placed.**

### Proposal Lifecycle State Machine

**Implemented in:** `proposal_paper_submitter.py` → `submit_paper()`
**DB column:** `paper_trade_proposals.paper_submit_state`

```
NOT_SUBMITTED → VALIDATING → VALIDATED → SUBMITTED
                    │                        │
                    └─ BLOCKED ←─────────────┘
```

| State | Trigger | Owner |
|-------|---------|-------|
| NOT_SUBMITTED | Proposal created/approved | api_v2.py |
| VALIDATING | submit_paper() called, before revalidation | proposal_paper_submitter.py |
| VALIDATED | Revalidation passes (eligibility=ELIGIBLE) | proposal_paper_submitter.py |
| BLOCKED | Revalidation fails or adapter rejects | proposal_paper_submitter.py |
| SUBMITTED | Adapter successfully submits to Alpaca | proposal_paper_submitter.py |

All transitions are logged to `proposal_event_log` with timestamps and payloads.

### Execution Audit Trail

Every trade persists a `risk_params_at_fill` JSONB snapshot in the `paper_trades` table:

```json
{
  "proposed_entry": 80.24,
  "live_price_at_submit": 68.48,
  "filled_avg_price": 68.48,
  "stop": 76.23,
  "target": 88.26,
  "drift_pct": 14.66,
  "order_type": "market",
  "order_type_reason": "market_better_price ($68.48 <= $80.24)"
}
```

**Implemented in:** `alpaca_paper_adapter.py` → `submit_entry()` (INSERT INTO paper_trades)

### Proposal Enrichment Packet

Each proposal accumulates before becoming submittable:
- Entry/stop/target price levels (from ATR, confluence cache, or strategy rules)
- Catalyst data and verification
- Indicator confluence (17 technical indicators)
- Agent analysis results (if reviewed)
- Risk gate assessment
- LLM review (when available)

### In-Trade Position Management

Once a position is open on Alpaca, `open_trade_monitor.py` → `monitor_trade()` runs on each open trade during market hours and manages positions automatically. All risk actions are logged to the `paper_trade_risk_actions` table.

**Implemented in:** `open_trade_monitor.py` → `monitor_trade()`, `_auto_close_position()`, `_update_stop_on_alpaca()`, `_log_risk_action()`

#### Trade Lifecycle States

**DB column:** `paper_trades.lifecycle_state`

```
pending → open → managing → closed / stopped_out
```

| State | Meaning |
|-------|---------|
| `pending` | Order submitted but not yet filled |
| `open` | Position filled on Alpaca |
| `managing` | Monitor is actively managing risk (first tick after fill) |
| `closed` | Position exited (target hit, stop hit, manual, or news close) |

#### Automated Risk Actions (Priority Order)

The monitor checks these conditions in order. Stop-hit and target-hit return immediately since the trade is closed.

| Priority | Condition | Action | Implemented In |
|----------|-----------|--------|----------------|
| 1 | **Stop hit**: `price <= stop` | Auto-close position on Alpaca, mark trade closed/LOSS | `_auto_close_position()` |
| 2 | **Target hit**: `price >= target` | Auto-close position on Alpaca, mark trade closed/CORRECT | `_auto_close_position()` |
| 3 | **Trailing stop**: `R >= 1.0` | Move stop to `entry + 50% × (price - entry)`, update Alpaca stop order | `_update_stop_on_alpaca()` |
| 4 | Near stop: price within 75% of stop distance | Alert only (Telegram) | `insert_alert()` |
| 5 | Near target: price within 80% of target distance | Alert only (Telegram) | `insert_alert()` |
| 6 | Stale trade: open > 3h with |R| < 0.5 | Flag as stale, alert | `stale_flag=true` |
| 7 | Extended profit: R >= 1.5 | Informational alert | `insert_alert()` |
| 8 | Critical news keywords detected | Auto-close position, alert | `_auto_close_position()` |

**Stops only move UP, never down.** The trailing stop ratchets upward as the trade progresses.

#### Risk Action Audit Trail

Every stop adjustment, auto-close, and trailing stop update is logged to `paper_trade_risk_actions`:

| Column | Purpose |
|--------|---------|
| `action_type` | `stop_hit_close`, `target_hit_close`, `trailing_stop_update`, `critical_news_close` |
| `old_value` | Previous stop/target level |
| `new_value` | New stop level or exit price |
| `trigger_price` | Market price that triggered the action |
| `trigger_reason` | Human-readable explanation |
| `broker_order_updated` | Whether Alpaca order was modified |

#### Dynamic Stop Adjustment Flow

```
open_trade_monitor.py → monitor_trade() (cron-driven, market hours)
    │
    ├─ Get current price via get_current_price()
    ├─ Compute: unrealized P&L, R-multiple
    ├─ Update paper_trades: current_price, unrealized_pnl, r_multiple
    │
    ├─ STOP HIT? (price <= stop)
    │   ├─ Delete position on Alpaca
    │   ├─ Update paper_trades: closed, exit_price, pnl, lifecycle_state='closed'
    │   ├─ Log to paper_trade_risk_actions
    │   └─ Telegram: "STOP HIT" → return (done)
    │
    ├─ TARGET HIT? (price >= target)
    │   ├─ Delete position on Alpaca
    │   ├─ Update paper_trades: closed, exit_price, pnl, lifecycle_state='closed'
    │   ├─ Log to paper_trade_risk_actions
    │   └─ Telegram: "TARGET HIT" → return (done)
    │
    ├─ TRAILING STOP? (R >= 1.0)
    │   ├─ new_stop = entry + 50% × (price - entry)
    │   ├─ If new_stop > current stop:
    │   │   ├─ Cancel old stop order on Alpaca
    │   │   ├─ Place new GTC stop at new_stop
    │   │   ├─ Update paper_trades.stop_loss
    │   │   ├─ Log to paper_trade_risk_actions
    │   │   └─ Telegram: "TRAILING STOP: stop moved"
    │   └─ Else: hold (stops never move down)
    │
    ├─ NEAR STOP? NEAR TARGET? STALE? EXTENDED PROFIT?
    │   └─ Alert only (Telegram + open_trade_alerts table)
    │
    └─ CRITICAL NEWS?
        ├─ Auto-close position on Alpaca
        └─ Telegram: "CRITICAL NEWS AUTO-CLOSE"
```

#### Alpaca Order Limitations

Alpaca paper trading does not support simultaneous stop + limit sell on the same shares (OCA). The workaround:
- Stop-loss is placed as a standing GTC order on Alpaca
- Profit target is monitored by `paper_trade_monitor.py` every 5 minutes
- When price reaches 80%+ of target move, the stop tightens aggressively to capture the gain
- When target is hit, the stop is cancelled and position is closed at market

#### Safety Net

`paper_execution_sweep.py` runs every 5 minutes during market hours as a safety net:
- Finds approved proposals with `paper_submit_state = NOT_SUBMITTED`
- Calls `submit_paper()` for each
- Catches edge cases: server restart during approval, network blip, etc.

This is NOT the primary execution path — instant execution on approval is. The sweep is the fallback.

#### Stop Adjustment Rules & Safeguards

**When stops ARE adjusted:**
- R-multiple crosses a threshold (1.0, 1.5, 2.0, 3.0)
- Price reaches 80%+ of target move (aggressive tightening)
- Stop is missing from Alpaca (re-placed at DB level)

**When stops are NOT adjusted:**
- New stop would be LOWER than current stop (stops only ratchet UP)
- Market is closed (adjustments only during regular session)
- Position has no DB record (orphaned Alpaca position — alert sent)

**Drift and slippage handling (multi-layer):**

| Layer | Check | Threshold | Action |
|-------|-------|-----------|--------|
| Revalidator | Stop breach | `price <= stop` | **Hard block** — INELIGIBLE |
| Revalidator | Price drift | >= 3% | Block, require re-approval |
| Revalidator | Price drift | >= 1.5% | Warning, score deduction |
| Adapter | Stop breach | `price <= stop` | **Hard block** — defense-in-depth |
| Adapter | Excessive drift | > 5% | **Hard block** |
| Adapter | Moderate drift | > 2% | Limit order (wait for value) |
| Adapter | Small drift | <= 2% or below entry | Market order (capture setup) |
| Post-fill | R-multiple | >= 1.0 | Trailing stop locks 50% of gains |
| Post-fill | Stop breached | `price <= stop` | Auto-close position |
| Post-fill | Target reached | `price >= target` | Auto-close position |
| Post-fill | Time stop | `hold_days >= max_hold_days` | Auto-close (per-strategy: scalp 0d, swing 21d, sector 56d, income none) |

- In-trade: stop is computed from actual fill price, not proposed entry
- In-trade: R-multiple uses actual fill price as baseline, adjusting for real slippage
- Unfilled limit orders expire at EOD (TIF=day), proposal re-evaluated next session
- All risk actions logged to `paper_trade_risk_actions` table with trigger prices

#### What the System Does NOT Do (Current Limitations)

- **Volatility-based stop widening:** Stops do not expand based on ATR or VIX changes. The initial stop is set at proposal time using ATR and remains the floor.
- **Granular R-multiple tiers:** Both `paper_trade_monitor.py` (every 5 min) and `open_trade_monitor.py` (every 15 min) implement full 4-tier trailing: 1.0R→breakeven, 1.5R→lock 0.5R, 2.0R→lock 1.0R, 3.0R→lock 2.0R. Uses `planned_stop` to recover initial 1R even after stop has been moved.
- **Regime-aware adjustment:** Market regime changes (bull → bear) do not automatically modify open positions.
- **Partial profit taking:** The system closes the full position at target, not partial lots.
- **Spread/liquidity checks:** The system does not check bid-ask spread or volume before adjusting stops. Acceptable for paper trading.

### Post-Trade Analysis Pipeline

When any paper trade closes, `on_paper_trade_closed()` in `agent_curation_hooks.py` triggers the full post-trade analysis chain. All close paths call this hook: `open_trade_monitor.py` (auto-close on stop/target/news), `paper_trade_closer.py` (manual close), `alpaca_paper_adapter.py` (sync close).

**Implemented in:** `agent_curation_hooks.py` → `on_paper_trade_closed()`

| Step | Component | Output |
|------|-----------|--------|
| **Outcome provenance** | `_write_outcome_to_proposal()` | Writes verdict/pnl/r_multiple back to `paper_trade_proposals` |
| Iris writeback | `iris_record_trade_outcome()` | Outcome intelligence rules |
| Aegis synthesis | `aegis_write_post_trade_synthesis()` | Narrative paragraph in `agent_curation_events` |
| Outcome lessons | `trigger_outcome_lessons()` | Pattern library updates |
| Pattern confirmation | `check_pattern_confirmation()` | Pattern strength adjustments |
| RAG indexing | `_index_trade_outcome_to_rag()` | Outcome embedded in `content_embeddings` |
| LLM analysis | `paper_trade_analyzer.py` | What worked/failed/lessons in `paper_trade_analysis` |
| **Realtime review** | `multi_tier_trade_reviewer.py` (gemma3:12b) | 4-agent structured review in `paper_trade_multi_reviews` |

### Learning Loop (Closed — Self-Improving)

The system forms a closed feedback loop where trade outcomes improve future proposals:

```
Trade closes → LLM analysis + agent critiques → RAG embedding
    ↓
Next proposal for same symbol/strategy
    ↓
proposal_agent_review.py queries RAG → sees "PAST TRADE HISTORY" in prompt
proposal_intelligence_analyzer.py queries RAG → "factor past losses into assessment"
approval_revalidator.py queries RAG → surfaces past losses as warnings
    ↓
Agents vote with historical context → better decisions
```

**Key tables in the learning loop:**

| Table | Purpose | Written By | Read By |
|-------|---------|------------|---------|
| `content_embeddings` (source_type='trade_outcome') | Vectorized trade outcomes | `agent_curation_hooks.py` | RAG queries in proposal review |
| `content_embeddings` (source_type='trade_review') | Vectorized tier reviews | `multi_tier_trade_reviewer.py` | RAG queries in proposal review |
| `agent_intelligence_rules` (rule_type='trade_learning') | Learning agent findings | `multi_tier_trade_reviewer.py` | Agent prompt context |
| `paper_trade_multi_reviews` | Structured reviews per tier | `multi_tier_trade_reviewer.py` | Journal UI, monthly aggregation |
| `paper_trade_analysis` | LLM what-worked/failed/lessons | `paper_trade_analyzer.py` | Journal UI |
| `paper_trade_risk_actions` | Stop adjustments, auto-closes | `open_trade_monitor.py` | Journal UI, risk audit |
| `journal_trade_reviews` | Human-readable review + tags | `agent_curation_hooks.py` | Journal UI |
| `trade_thesis_outcomes` | Thesis confirmed/invalidated | `post_trade_thesis_reviewer.py` | Journal UI |

### Journal Edge-Analytics + AI Q&A (2026-06-15)

`journal_analytics_engine.py` (read-only) computes TradeZella-style edge analytics from data already
captured — `schwab_round_trips` (trade facts + entry/exit timestamps) left-joined to
`journal_trade_reviews` (setup/emotion/R enrichment). No new tables/migration. Sections:
- **time_analysis** — win-rate / net-P&L / count by day-of-week, hour, and trading session
  (premarket / open 9:30-11 / midday 11-14 / close 14-16 / after-hours, ET).
- **equity_curve** — cumulative net-P&L series + max drawdown + per-trade Sharpe + recovery factor.
- **r_distribution** — realized-R histogram + planned-vs-realized (sparse until trades are reviewed).
- **setup_breakdown** — edge by `strategy_tag` (always populated: scalp/swing/momentum/…), plus
  setup_family / emotion / mistake-tag overlays from reviews.

`journal_ask.py` answers natural-language questions over that analytics via the free Grok lane
(local-gemma fallback) — "why do I lose on Thursdays?", "best session for my scalps?". Endpoints:
`GET /api/v2/journal/edge-analytics?account=&days=` and `POST /api/v2/journal/ask {question,account,days}`.
Surfaced in v3 **Journal → Analytics** (risk KPIs, day/session bar charts, edge-by-strategy, R-dist, Ask
box). Complements the existing review-based `/api/v2/journal/analytics`. MFE/MAE deferred (needs new
intratrade excursion capture). Schwab→journal ingest itself: `schwab_transaction_ingest` →
`schwab_journal_builder` → `schwab_journal_classifier`, now `.env`-loaded (was silently NOT_PROVEN under
cron) + auth-monitored, run nightly 18:15 and every 15 min in trading hours.

### API: Professional Trade Journal Entry

**Endpoint:** `GET /api/v2/journal/trade-detail/{id}`
**Implemented in:** `api_v2.py`

Aggregates ALL data for a single closed trade into a structured response:

| Section | Data Source |
|---------|------------|
| `classification` | paper_trades: strategy, setup, regime, day/time |
| `timing` | paper_trades: entry/exit timestamps, hold duration |
| `technicals_at_entry` | paper_trades: VIX, RVOL, score, grade, catalyst |
| `risk_execution` | paper_trades: planned vs actual, slippage, MAE/MFE, R-multiple |
| `narrative.journal_review` | journal_trade_reviews: lessons, coach notes, mistake/strength tags |
| `narrative.thesis_outcome` | trade_thesis_outcomes: thesis confirmed/invalidated |
| `narrative.llm_analysis` | paper_trade_analysis: what worked/failed/lessons |
| `agent_critiques` | agent_curation_events: Iris, Aegis, system, LLM events |
| `multi_tier_reviews` | paper_trade_multi_reviews: realtime/overnight/weekly/monthly reviews with agent commentaries |
| `risk_actions` | paper_trade_risk_actions: stop adjustments, auto-closes |
| `proposal` | paper_trade_proposals: original proposal parameters, eligibility |

---

## 11. Agent Layer

### Conversational Agents (OpenClaw Gateway :18789)

| Agent | Role | Key Capabilities |
|-------|------|-------------------|
| **Maria** | Risk assessment | Position sizing, portfolio impact, exposure analysis, correlation checks |
| **Steph** | Technical analysis | Entry/exit timing, chart patterns, wealth advisory, indicator confluence |
| **Aegis** | Synthesis & surveillance | Nightly synthesis, morning briefs, cross-agent coordination, overnight monitoring |
| **Alex** | Income strategy | Roth conversion planning, SSDI/IRMAA impact, dividend analysis, covered call evaluation |

Agents are accessible via Telegram and WhatsApp. Configuration is in `config/agents.yaml` and personality/behavior rules in the agents bible (`docs/project/agents_bible.md`).

**Full agent workflows** (fleet roster, schedules, allocation chain Maria→Steph→Risk→Tax→Alex, v3 AgentsHub surfaces): see `docs/AGENT_AND_HERMES_WORKFLOWS.md` Part 1.

### Backend Automation Agents

| Agent | Role | Script |
|-------|------|--------|
| **Iris** | Library hygiene -- content quality, stale data detection, dependency audits | `scripts/iris_*.py` |
| **Pipeline Watchdog** | Health monitoring -- 31 stage failure/delay detection | `scripts/pipeline_watchdog.py` |
| **Scalp Critic** | LLM critique of screener candidates before promotion | `scripts/incubator_llm_screener.py` |

### Agent Processing Schedule

| Window | Interval | Jobs/Run | Context |
|--------|----------|----------|---------|
| Market hours (6 AM - 7 PM) | Every 15 min | 10 jobs | Active trading context |
| Overnight (8 PM - 11 PM) | Every 5 min | 25 jobs | Batch processing |
| Weekend | Every 10 min | 15 jobs | Catch-up processing |

---

## 12. LLM Subsystem

### Configuration

All LLM config is sourced from `.env` -- zero hardcoded values. Configuration hub: `scripts/local_llm_config.py`.

### Primary Model

| Parameter | Value |
|-----------|-------|
| Model | `gemma3:12b` |
| Runtime | Ollama (localhost:11434) |
| GPU | Intel Arc B50 (Vulkan backend) |
| Layer offload | 41/41 layers on GPU |
| Keep-alive | Persistent (`OLLAMA_KEEP_ALIVE=-1`) |
| Performance | ~15s per chunk (GPU) vs ~300s (CPU) |

### Routing & Fallback Chain

```
local (gemma3:12b via Ollama) ──→ OpenAI (gpt-4o-mini) ──→ Anthropic (claude-sonnet-4-6)
         PRIMARY                      FALLBACK 1                  FALLBACK 2
    Intel Arc B50 GPU               On Ollama failure            On OpenAI failure
    ~15s/chunk, free                ~$0.01/call                  ~$0.03/call
```

**Escalation logic** (in `local_llm.py`):
- Try local Ollama first (toll-gated, max 300s timeout)
- On timeout/failure → try OpenAI `gpt-4o-mini`
- On OpenAI failure → try Anthropic `claude-sonnet-4-6`
- On all failure → return empty (caller handles gracefully)

### Process-Type Routing (Phase 0 Migration)

All LLM calls declare a process type. The config hub (`local_llm_config.py`) resolves the model from `.env`. Scripts call `local_llm.generate(prompt, caller="script_name", process_type="STANDARD")` — no hardcoded model names.

**Migrated scripts (Phase 0):** `morning_digest.py`, `portfolio_news.py`, `scalp_critic_agent.py`, `stop_decision_brief.py`, `post_trade_thesis_reviewer.py`, `catalyst_intelligence.py`, `scoring.py` — all route through `local_llm.generate()` with STANDARD process type, toll gate serialization, audit logging, and cloud fallback.

**When external LLM is used instead of local:**
- `rebalance_deep_analyzer.py` — gemma3:27b monthly deep analysis (zero cost, runs in deep overnight queue). Tier 2 verification via `rebalance_verifier.py` using Anthropic Sonnet (~$0.008/week).
- `portfolio_yaml_advisor.py` — legacy, requires Claude Opus (blocked by API credit depletion). Superseded by `rebalance_deep_analyzer.py` for monthly analysis.
- Agent conversational responses (via OpenClaw) — may use cloud LLM for complex queries
- All other use cases (classification, screening, enrichment, narratives) → local primary

### Toll Gate (GPU Contention Prevention)

File lock at `/tmp/ollama_llm_gate.lock` using `fcntl.flock(LOCK_EX)`:
1. Caller acquires exclusive lock (blocks up to 600s)
2. Writes PID + timestamp to lock file for debugging
3. Sends request to Ollama
4. Releases lock on completion or timeout
5. If lock acquisition fails → falls back to cloud LLM

### Multi-Tier Trade Review System

Closed trades receive escalating LLM review across 4 tiers. Each higher tier sees lower-tier reviews as context, building layered analysis. All reviews persist to `paper_trade_multi_reviews` table and index findings into RAG.

**Implemented in:** `multi_tier_trade_reviewer.py`

| Tier | Model | Trigger | Purpose |
|------|-------|---------|---------|
| Realtime | gemma3:12b (Ollama) | Every trade close via `on_paper_trade_closed()` | Fast initial analysis (~30s) |
| Overnight | gemma3:27b (Ollama) | Nightly 8 PM via `overnight_batch.py` | Deeper analysis with larger model |
| Weekly | OpenAI gpt-4o | Sunday 10 AM via cron | Cross-trade pattern detection, strategy grades |
| Monthly | Anthropic Claude | 1st of month via cron | Strategic review of weekly summaries + flagged trades |

Each tier generates structured reviews with 4 agent perspectives:

| Agent | Evaluates |
|-------|-----------|
| risk_agent | Stop placement, position sizing, R:R honored |
| strategy_agent | Criteria alignment, setup validity, repeat-worthiness |
| execution_agent | Entry timing, slippage, exit handling |
| learning_agent | Patterns, rules to change, memory for future trades |

All agent commentaries are written to `agent_curation_events` (visible in journal) and learning findings to `agent_intelligence_rules` (consumed by future proposals via RAG).

### LLM Use Cases

| Use Case | Script | Frequency | Model |
|----------|--------|-----------|-------|
| Intelligence enrichment (5 surfaces) | `llm_intelligence_enrichment.py` | 7:20 AM daily | gemma3:12b |
| Strategy classification (23 strategies) | `multi_strategy_classifier.py` | Sunday night batch | gemma3:12b |
| Proposal review (4-chunk pipeline) | `proposal_llm_reviewer.py` | Per proposal | gemma3:12b |
| Incubator pre-screening (A-F grades) | `incubator_llm_screener.py` | 8:10 AM + 6 PM | gemma3:12b |
| Holdings health refresh | `holdings_llm_refresh.py` | 3x daily market hours | gemma3:12b |
| Topic curation (rate, extract, improve) | `topic_curator.py` | 7:00 AM daily | gemma3:12b |
| Agent responses | Via OpenClaw gateway | On user interaction | gemma3:12b + cloud fallback |
| Rebalance advisor | `portfolio_yaml_advisor.py` | Monthly or on-demand | Claude Opus (cloud) |
| **Trade review — realtime** | `multi_tier_trade_reviewer.py` | Every trade close | gemma3:12b |
| **Trade review — overnight** | `multi_tier_trade_reviewer.py` | Nightly 8 PM | gemma3:27b |
| **Trade review — weekly** | `multi_tier_trade_reviewer.py` | Sunday 10 AM | OpenAI gpt-4o |
| **Trade review — monthly** | `multi_tier_trade_reviewer.py` | 1st of month | Anthropic Claude |
| **Post-trade analysis** | `paper_trade_analyzer.py` | Every trade close | gemma3:12b |
| **Proposal intelligence** | `proposal_intelligence_analyzer.py` | Per proposal (with RAG context) | gemma3:12b |
| **Proposal agent review** | `proposal_agent_review.py` | Per proposal (with RAG context) | gemma3:12b |

### LLM Context Engine

All prompt builders use `scripts/llm_context_engine.py` to inject actual DB data into
prompts. No LLM call receives only IDs or trigger names — every call gets the underlying
data it needs to reason correctly.

**Usage:** `from llm_context_engine import build_context`
`ctx = build_context(symbol='GCTS', context_type='trade_review', trade_id=158, conn=conn)`

**Context types and data sources:**

| Context Type | Data Injected | Source Tables |
|-------------|---------------|---------------|
| `strategy_classification` | RSI, RVOL, price, sector, beta, P/E, SMA50/200, trade history, news | `ticker_snapshot_daily`, `paper_trades`, `trade_closed`, `news_articles` |
| `trade_review` | Entry/exit/P&L/stop/hold/R-multiple + past symbol W/L/stop usage | `trade_closed`, `paper_trades` |
| `risk_synthesis` | All positions with market values, portfolio %, day change | `holdings.json` |
| `recovery_watch` | Exit price, days out, recovery %, thesis at exit, current RSI | `stopped_out_watch`, `ticker_snapshot_daily` |
| `covered_call` | Price, RSI, beta, div yield, RVOL, Aegis verdict | `ticker_snapshot_daily`, `aegis_covered_call_candidates` |
| `proposal` | Entry/stop/target, R:R, catalyst, score, current snapshot | `paper_trade_proposals`, `ticker_snapshot_daily` |

**Anti-hallucination block** appended to every context: *"Use ONLY the data above.
Do NOT invent, estimate, or assume numbers not explicitly provided."*

**Data flow:** DB tables → `llm_context_engine.py` → formatted text block → prompt builder → LLM call → structured output → DB results table

### LLM Intelligence Enrichment (Phase 5)

`llm_intelligence_enrichment.py` generates 5 intelligence sections daily, stored in `llm_intelligence_cache`:

| Section | Content | Surfaced On |
|---------|---------|-------------|
| `portfolio_risk` | Risk assessment narrative (concentration, stops, actions) | `/v2/command` |
| `rebalance_suggestions` | 5 numbered tax-aware suggestions | `/v2/rebalance` |
| `recovery_analysis` | Re-entry readiness and abandonment calls | `/v2/recovery` |
| `morning_synthesis` | Portfolio + news + social synthesis paragraph | `/v2/command`, Overview |
| `prospect_narratives` | Per-symbol 1-sentence thesis (top scored) | `/v2/prospects` |
| **Topic query generation** | `topic_ingestion.py --curate` | Per ingestion run |
| **Content quality rating** | `topic_curator.py` | Post-ingestion |
| **Entity extraction (tickers/topics/sectors)** | `topic_curator.py` | Post-ingestion |
| **Query improvement (learning loop)** | `topic_curator.py --improve-queries` | Daily |

---

## 13. API Layer

- **Endpoint count:** 100+
- **Base path:** `/api/v2/*`
- **Server:** `scripts/portfolio_server.py` on port 7777
- **Handler:** `scripts/api_v2.py` (12,600+ lines)
- **Protocol:** HTTP/JSON (no auth layer -- internal network only)

### Endpoint Groups

| Group | Key Endpoints | Methods |
|-------|--------------|---------|
| **Portfolio** | `portfolio/holdings`, `portfolio/performance`, `portfolio-monitor` | GET |
| **Watchlist** | `watchlist`, `watchlist/items`, `watchlist/symbols`, `watchlist/research-card/{sym}` | GET, POST |
| **Prospects** | `prospects`, `trade-ai` | GET |
| **Proposals** | `proposals`, `proposals/feedback`, `proposals/history`, `proposal-detail/{id}` | GET, POST, PUT |
| **Intelligence** | `intelligence-entities`, `intelligence-whiteboard`, `qualified-intelligence` | GET |
| **CIO** | `cio` (unified), `cio-dashboard`, `cio-decisions`, `cio-decisions/{sym}` | GET |
| **Recovery** | `recovery` (exit classification, relist tracking, patience scoring) | GET |
| **Rebalance** | `rebalance`, `rebalance-plans`, `rebalance-plans/latest` | GET |
| **Reports** | `reports` (hub), `weekly-report`, `monthly-report` | GET |
| **Retirement** | `retirement`, `tax-situation`, `trust-transfers` | GET |
| **Strategy** | `strategy-rules`, `strategy-rotations`, `classifications` | GET, PUT |
| **Agents** | `agent-pipeline`, `agent-health`, `agent-detail`, `agent-calibration` | GET |
| **Risk** | `risk-gate-status`, `portfolio-signal-qa` | GET |
| **Research** | `rag/status`, `research/ticker/{sym}`, `research-topics` | GET, POST |
| **Social** | `social/posts`, `social/status`, `aegis/social-sentiment` | GET |
| **Pipeline** | `pipeline-health`, `pipeline-run-health`, `auto-proposal-diagnostics` | GET |
| **System** | `system-health`, `cost-dashboard`, `llm/health`, `llm-spend` | GET |

### New Endpoints (Session 29 — 2026-05-11)

| Endpoint | Purpose |
|----------|---------|
| `/api/v2/recovery` | Full recovery dashboard with exit classification (true stop-out vs relist vs market reconnection), patience scoring, relist event history |
| `/api/v2/cio` | Unified CIO intelligence with deduplicated decisions (DISTINCT ON symbol), rotations, plans, learning recommendations |
| `/api/v2/portfolio-monitor` | Real-time portfolio health: holdings with technicals, risk alerts, news digest, LLM health, dividend calendar, recovery watch |
| `/api/v2/reports` | Reports hub: agent activity, pipeline runs, learning stats, incubator, social ingestion, weekly DOCX catalog |

### Enrichment Changes (Session 29)

- **`/api/v2/prospects`**: Now includes incubator LLM screen grades, proposal LLM reviews, social sentiment from `social_sentiment_history`
- **`/api/v2/watchlist`**: Now includes LLM health, news counts (7d), social sentiment, latest scan scores/decisions, catalyst text

---

## 14. Frontend

- **Framework:** React SPA (Next.js)
- **Route:** served at `/v2/` via Portfolio Server (port 7777)
- **Source:** `apps/command-center-v2/` (91 TypeScript/React files)
- **Pages:** 61 (all fully implemented, no stubs)
- **API hooks:** `useApi()`, `useFetch()` custom hooks for data fetching
- **Charts:** BarChartJS, LineChart, DoughnutChart components

### Page Groups

| Group | Pages | Key Views |
|-------|-------|-----------|
| **Portfolio Core** | Overview, Portfolio, Returns, Dividends, Rebalance, Retirement, Tax, Correlation, Attribution, Forecast | Holdings, P&L, income, allocation, tax lots |
| **Trading** | Trade AI, Strategy Desk, Prospects, Execution Quality, Broker Recon | Screener results, strategy signals, TCA |
| **Paper Trading** | Paper Status, Paper Proposals, Paper Journal, Paper Outcomes, Paper Governance, Paper Trade Intelligence | Full paper trading lifecycle |
| **Intelligence** | AI Analyst, Intelligence Sources, Intelligence Entities, Intelligence Whiteboard, Content Health, Topic Monitor, Portfolio Intelligence | Research, NLP, RAG, topic ingestion |
| **Agents** | Agent Pipeline, Agent Calibration, CIO Dashboard, Morning Brief | Agent performance, decisions, briefings |
| **Monitoring** | Watchlist, Recovery, Portfolio Monitor, Alerts, Notifications, System Health, Risk, Risk Regime | Position tracking, stops, alerts |
| **Pipeline** | Pipeline Health Master, Pipeline Controller, Incubator, Self Improvement, Weekly Learning, Learning Governance | Pipeline ops, incubator lifecycle |
| **Reporting** | Reports, Journal Analytics, Journal Reports, Backtesting | Analytics, reports, DOCX catalog |
| **Admin** | Strategy Admin, Live Governance, Approvals, Orchestration, Ops, System Hub, Action Center | Config, governance, operations |

---

## 15. Notification & Alerting

| Channel | Integration | Config | Priority |
|---------|-------------|--------|----------|
| **Telegram** (primary) | Bot API | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | P1 -- all alerts |
| **WhatsApp** | Twilio API | Twilio credentials | P2 -- agent conversations |
| **Email** | SMTP | SMTP config | P3 -- reports |
| **Slack** | Webhook | Webhook URL | P4 -- optional |

All channels toggled via `ENABLE_*` flags in `.env`.

### Alert Types

| Alert | Source | Trigger |
|-------|--------|---------|
| Smart Proactive Alerts | `telegram_smart_alerts.py` | 6 AM daily |
| Pipeline Failure (watchdog) | `pipeline_watchdog.py` | Stage failure/staleness |
| Pipeline Failure (wrapper) | `pipeline_alert.py` | Non-zero exit on any wrapped cron job |
| System Health | `system_health_alerts.py` | Threshold breach |
| Iris Library Alert | Iris agent | Content hygiene issues |
| Aegis Morning Brief | `aegis_morning_brief_delivery.py` | 8 AM daily |
| Recovery Watch | `recovery_watch_daily.py` | Stop-out detection, relist classification, escalation to Maria/Steph |
| Pre-Market StockTwits | `premarket_watcher.py` | StockTwits surge data (persisted to social_posts + trade_ai_scans) |
| Stop Placement Reminder | `recovery_watch_daily.py` | Positions without confirmed stops |
| Weekly DOCX Report | `generate_weekly_docx.py` | Weekly Word report generated + Telegram notification |
| Intelligence Gap Fill | `agent_event_router.py` | CONTENT_GAP auto-search completion |
| Incubator Promoter | `incubator_proposal_promoter.py` | Promotions or failures |
| YouTube Ingestion | `youtube_transcript_ingest.py` | Crash during channel scan |

### Pipeline Failure Alerting (Session 37)

Every critical cron job is wrapped with `pipeline_alert.py` which:
1. Runs the command and captures stdout/stderr
2. On non-zero exit: sends Telegram with error excerpt + reply-to-retry command
3. Logs to `logs/<pipeline_name>.log` with timestamp and exit code

Wrapped pipelines: news_ingestion, youtube_ingest, overnight_batch, sec_data_ingest, event_detector, previously_traded, pipeline_watchdog.

**Scale:** 56 scripts send Telegram alerts across 100+ unique call sites. Structured alerts/briefs log to `notification_log` (dedupe keys); SIEM advisories to `alert_events`; LLM monthly/weekly reports to `ai_reports`. Recurring operator **reports** are additionally captured at the send chokepoint to `telegram_outbox` (see Reports Portal below) so every report the operator receives is also browsable in the dashboard.

### Reports Portal (v3) — every Telegram report persisted & surfaced (2026-06-16)

Recurring operator reports (Incubator LLM Screen, Auto-Research, EOD Open Trades, Trade AI Critique, Strategy/Alex weekly reviews, Portfolio/Monthly reports, CIO & Daily Intelligence, overnight/pre-market briefs, Learning Digest, Stop briefs) were being sent to Telegram but **never persisted**, so the Reports hub could not show them. Fixed by capturing at the source:

- **`report_capture.py`** — `classify_report()` recognizes 20 report headers and `capture()` writes each recognized report to a new **`telegram_outbox`** store. Best-effort: it never raises and never blocks a send; unrecognized/transient messages (already self-logged to `notification_log`/`alert_events`) are skipped to avoid duplication.
- **Chokepoint** — `telegram_alert._raw_send_telegram()` calls `capture()` for every send. **9 direct-posting senders** (`eod_open_trade_alert`, `scalp_critic_agent`, `portfolio_monthly_report`/`_synthesis`, `portfolio_weekly_report`, `morning_digest`, `send_morning_brief`, `weekly_summary_local`, `stop_decision_brief`) were routed through `send_telegram()` so they are captured **and** FQDN/`/v3`-normalized (their DOCX `sendDocument` paths stay direct — `send_telegram` is text-only).
- **`reports_portal.py`** — the portal unions four stores (`notification_log`, `alert_events`, `telegram_outbox`, `ai_reports`) into one categorized, searchable, paginated feed with full-article rendering and a purge tool. Categories (17 tabs): Morning Briefs, Digests, **Portfolio Briefs, Monthly Reports, Weekly Reviews, Incubator Screen, Research & Intel, Trade Reports, Trade Critique, Learning Digest**, Alerts, Advisories, Recovery Watch, Dividends, Regime/Rebalance, Paper Trading, System Health. Monthly/Weekly pull real history from `ai_reports`. Served at `GET /api/v2/reports/{categories,list,item}` + `POST /api/v2/reports/purge`; UI on **`/v3/reports`** (news-reader layout).
- **Link integrity** — report bodies link to dashboard pages; a normalizer (`notification_url_builder._to_v3`) + the portal's `_PAGE` map resolve every legacy `/v2/<slug>` to the **semantically correct** `/v3` page (e.g. `recovery → /v3/risk` where the Recovery Watch section lives, `actions → /v3/` Home Action Inbox, `approvals → /v3/trading`), dropping any slug that would resolve to a dead route.

### Central Intelligence — live LM review & feedback loop (2026-06-16)

The "Agent / Local LM Review & Feedback" widget on the Central Intelligence board previously POSTed to a non-existent endpoint (404 → localStorage fallback). Now `POST /api/v2/agents/intelligence-feedback`:

- Runs the **local gemma LLM** (`llm_lane.generate(lane='local')`) on the operator's question + critique + the visible signals and **returns the review synchronously**.
- Operator may opt into the **Grok lane** too (`use_grok` → `llm_lane.generate(lane='grok')`, only if the free OAuth proxy is authenticated); the UI shows local + Grok reviews side by side.
- Persists to `intelligence_feedback` and records one **learning observation per lane** to `llm_feedback_observations` (`workflow='central_intelligence_review'`), so operator critique feeds the self-learning loop.

**Proposal-alert dedup fix (2026-06-04):** `send_telegram_proposal_alert.py` enforces a 30-min
per-proposal dedup via `paper_trade_proposals.last_alert_at`. The write-back was silently failing —
its `_db_query` helper never committed (singleton conn, `autocommit=False`) and ran the `UPDATE`
through the `fetchall()` path, which raises on a no-result statement and was swallowed by a bare
`except`, leaving the shared transaction aborted (and poisoning later queries on the conn).
`last_alert_at` was therefore never persisted, so every `*/2` cron tick re-sent the identical card
(e.g. ARTL ~10× on 2026-06-03). `_db_query` now has a `fetch="none"` write mode that commits and
returns rowcount, with rollback-on-error; the dedup UPDATE uses it. Note: dedup is purely
time-based — a genuine state change (ACTIONABLE → BLOCKED) within the 30-min window is also
suppressed until the window elapses or the proposal auto-rejects after 30-min blocked.

**Silent-failure watchdog stack (2026-06-04).** Built after a freshness scan found the
`catalyst_events` pipeline had been silently dead ~5 weeks (no monitor watched for "table that
should have rows has none"). Three independent layers:
1. **`system_freshness_monitor.py`** (`*/20`) — registry-driven freshness/empty-vs-input/cron-logfile
   checks; emits SIEM (`alert_events` `data_integrity`) + Telegram for P0/P1; **narrow safe
   auto-fix** (allowlist of idempotent DB-only re-runs — `news_to_catalyst`, `hermes_news_bridge`,
   `research_insight_extractor` — capped 2/day, always logged + escalated; never schema/column/
   trading writes). Weekday-aware. Fail-tested end-to-end (Telegram delivery to operator device
   confirmed).
2. **`freshness_watchdog_heartbeat.py`** (`*/30`, independent — does not import the monitor) — pages
   P0 if the monitor's heartbeat goes >70 min stale (watches the watchman; host-alive case).
3. **Off-host ping** — `system_freshness_monitor` pings `FRESHNESS_HEARTBEAT_PING_URL` each run if
   set (external uptime service; covers total-host death). **Env-gated — set the URL to activate.**

Consolidated post-repair state: **`docs/SYSTEM_HEALTH_BASELINE_2026_06_04.md`** (signal lanes 4/5,
freshness registry, 4-gate readout, open risks, watchdog coverage). Full narrative + decisions:
`docs/HERMES_NEWS_TO_SCALP_CATALYST_INTEGRATION_2026_06_04.md`.

### Central Alert Dispatcher (Phase 2)

`alert_dispatcher.py` provides unified routing for all alerts:

| Feature | Detail |
|---------|--------|
| **Cross-script dedup** | Same symbol + alert type + date = one alert per day |
| **Escalation tiers** | `INFO` (dashboard only), `ALERT` (Telegram), `URGENT` (bypasses rate limit) |
| **Fatigue detection** | Auto-downgrade to INFO after 3 consecutive days + fire META alert |
| **Rate limiting** | Max 15 Telegram alerts per hour (configurable via `ALERT_MAX_PER_HOUR`) |
| **Convenience functions** | `alert_stop_triggered()`, `alert_dividend_payers()`, `alert_pipeline_failure()`, `alert_proposal_aging()`, `alert_api_credits_depleted()` |

### Missing Condition Alerts (Phase 2)

`alert_missing_conditions.py` checks daily at 7:30 AM:
- Proposals stuck in PENDING > 7 days
- Anthropic API credit depletion (minimal POST test)
- Email digest not firing > 3 days
- Rebalance data > 14 days stale

**Telegram reply commands for retry:**
- `run promoter` / `run promoter dry` — retry incubator promoter
- `run screener <name>` — retry a screener
- `status` — full system health check

### Failure Notification Flow

```
Cron fires script via pipeline_alert.py
    ↓
Script exits non-zero
    ↓
pipeline_alert.py captures error
    ↓
Telegram alert sent:
    "PIPELINE FAILURE: <name>
     Error: <last 5 lines>
     Reply: run <name>"
    ↓
John replies in Telegram → telegram_command_handler executes retry
```

---

## 16. Scheduling & Orchestration

67+ cron entries manage the full pipeline (flock-protected to prevent stacking). Key schedule (all times Eastern):

### Morning Cascade (5-8 AM)

| Time | Job | Script |
|------|-----|--------|
| 5:00 AM | Alex daily scan | `alex_retirement_advisor.py` |
| 5:45 AM | Indicator cache refresh | `indicator_cache_refresh.py` |
| 6:00 AM | Smart proactive alerts | `telegram_smart_alerts.py` |
| 6:15 AM | Agent context refresh | `agent_context_refresh.py` |
| 6:25 AM | Agent intelligence discovery | `agent_intelligence.py` |
| 6:30 AM | News ingestion | `news_ingestion.py` |
| 6:45 AM | Topic ingestion (gaps only) | `topic_ingestion.py --gaps-only` |
| 6:35 AM | Classify candidates | `multi_strategy_classifier.py` |
| 6:45 AM | Sync watchlist to DB | `watchlist_sync.py` |
| 6:50 AM | Materialize strategy cards | `strategy_card_materializer.py` |
| 6:55 AM | Income engine | `income_engine.py` |
| 7:00 AM | CIO decisions + enrichment | `cio_decision_engine.py` |
| 7:00 AM | Topic curator (rate, extract, improve) | `topic_curator.py --improve-queries` |
| 7:15 AM | State freshness + price sync | `state_freshness_writer.py` |
| 7:15 AM | Portfolio orchestrator (digest, alerts) | `portfolio_orchestrator.py` |
| 7:20 AM | LLM intelligence enrichment (5 sections) | `llm_intelligence_enrichment.py` |
| 7:25 AM | System health alerts | `system_health_alerts.py` |
| 7:30 AM | Missing condition alerts | `alert_missing_conditions.py` |
| 7:40 AM | Portfolio QA | `portfolio_level_qa.py` |
| 8:00 AM | Aegis morning brief (upgraded: dividends, proposals, risk) | `aegis_morning_brief_delivery.py` |

### Market Hours (9 AM - 4 PM)

| Time | Job |
|------|-----|
| 09:00, 10:00 AM | Orchestrator runs (screener windows 3, 4) |
| 11, 12:30, 1, 2, 3 PM | Hourly light reprice + intraday intelligence |
| 12:00, 2:00, 4:00 PM | Afternoon pipeline refresh (--no-llm, scoring only) |
| 12:30 PM | News ingestion (midday) |
| 4:00 PM | End-of-day screener + news |
| 5:30 PM | Evening pipeline refresh (with LLM enrichment) |

### Evening & Overnight

| Time | Job |
|------|-----|
| 6:10 PM | Proposal promoter (evening) |
| 6:30 PM (Mon–Fri) | Entry/exit grade engine — `trade_backtest_engine.py` (grades newly closed trades into `trade_backtest_results`) |
| 8:00 PM | Overnight batch + SEC Form 4 |
| 8:30 PM | Feedback loop processor (outcome chains, alert scoring) |
| 9:00 PM (Mon–Fri) | AI Trade Eval — `trade_close_llm_analyzer.py --structured` (gemma3:12b, --limit 12, structured scores+verdict). Research/journaling only. |
| 10:00 PM (daily) | Setup-quality prior + proposal advisory — `setup_quality_prior.py` (advisory-only, never gates). |
| 10:10 PM (Sun) | Backtest result-history archiver (append-only) — `backtest_history_snapshot.py`, after the Sun 10 PM enterprise replay |

> Backtest cadence summary: daily active backtest weekdays 6 AM (`strategy_backtester.py`); full enterprise replay Sunday 10 PM (`enterprise_backtester.py --replay-trades`); entry/exit grading weekdays 6:30 PM; result-history archiver weekdays 6:10 AM + Sunday 10:10 PM (`backtest_history_snapshot.py`, append-only, never overwrites). Services run under systemd (`tradeai-portfolio-server.service`); all scheduled batch jobs run under cron + `safe_flock.sh`.
| 9:00 PM | Auto-research |
| **11:00 PM–3:00 AM** | **Deep overnight LLM window** (gemma3-overnight, 100-job cap, 15 job types: strategy classification, risk synthesis, RAG curation, journal/trade reviews, recovery watch, covered call scoring, strategy opportunity scan, rebalance analysis, + rotating strategy scans: income (Mon), growth (Wed), reversion (Sat). Event-driven requeue + calibration loop. Strategy-aware incubator grading (4 prompt groups)) |
| **Fri 4:00 PM** | **Friday extended window** (400-job weekly backlog clear, 11h window) |
| Sun 7:00 PM | Weekly incubator builder |
| Sun 8:00 PM | Full topic ingestion (all topics, with LLM) |
| Sun 9:00 PM | Weekly DOCX report (`generate_weekly_docx.py`) |
| Sun 10:00 PM | LLM incubator classification |
| 1st of month, 6 AM | Backup verification (`backup_verify.py`) |

---

## 17. Security & Access Control

### Current State (Self-Hosted)

| Layer | Control |
|-------|---------|
| **Network** | Server on private network; no public-facing ports |
| **API** | No authentication layer (internal-only access) |
| **Database** | Password authentication, localhost-only binding |
| **Secrets** | `.env` file (not in git, `.gitignore` enforced) |
| **LLM** | Local inference primary; cloud API keys in `.env` |
| **Broker** | Paper mode only; API keys scoped to paper trading |

### Cloud Migration Security Requirements

| Requirement | Implementation |
|-------------|---------------|
| API authentication | API Gateway + JWT / API key |
| Network isolation | VPC + private subnets for DB and LLM |
| Secrets management | AWS Secrets Manager / Azure Key Vault |
| TLS everywhere | ALB/App Gateway termination + internal TLS |
| Audit logging | CloudTrail / Azure Monitor |
| RBAC | IAM roles per service |

---

## 18. Failure Modes & Recovery

### Critical Failure Scenarios

| Failure | Impact | Detection | Recovery |
|---------|--------|-----------|----------|
| **PostgreSQL down** | All services halt | `pg_isready` + watchdog | Restart service; restore from 7-day rolling backup |
| **Ollama crash** | LLM classification stops | Health check on `:11434` | Systemd auto-restart; cloud fallback activates |
| **Portfolio Server crash** | API + frontend unavailable | Health check on `:7777` | `pkill + restart`; systemd auto-restart (`Restart=always`) |
| **Portfolio Server HANG** (alive but unresponsive) | API + frontend hang; `/v2/` and `/v3/` unreachable | `scripts/portfolio_server_watchdog.sh` (cron */2) probes `/api/health`; systemd `Restart=always` does NOT catch a hang | Watchdog kills the (johnclaw-owned) pid → systemd respawns. Root cause fixed: api_v2 was `importlib.reload`-ed on *every* `/api/v2/` request, which deadlocked the threaded server under concurrent dashboard polling. Now mtime-gated + lock-guarded in `portfolio_server.py:_get_api_v2()` — reloads only when the source file changes. (Incident 2026-06-03.) |
| **Finviz cookie expired** | No new screener candidates | Screener stage reports 0 results | Manual browser re-authentication |
| **Cloud LLM budget exhausted** | Falls back to next provider | Budget counter in `.env` | Resets daily; or increase budget |
| **Network outage** | External data sources unavailable | Source staleness exceeds threshold | Pipeline operates on cached data; alerts operator |
| **Disk full** | Logs/backups fill disk | Disk monitoring | Log rotation; backup pruning |
| **GPU driver issue** | LLM falls back to CPU (~20x slower) | Vulkan layer count check | Restart Ollama with override; verify `OLLAMA_VULKAN=1` |

### Backup Strategy

| Asset | Method | Retention | Location |
|-------|--------|-----------|----------|
| Database | `pg_dump` (gzipped) | 7-day rolling | `backups/db/` |
| Configuration | `.env` + strategy YAML snapshot | Per-session | `backups/session*/` |
| Source code | Git | Full history | `.git/` |
| Portfolio state | JSON snapshot | 10 daily snapshots | `data/portfolios/snapshots/` |
| Systemd services | Config backup | Per-change | `backups/systemd/` |

### Restarting the Portfolio Server (`:7777`)

The service runs as systemd unit `tradeai-portfolio-server` (`User=johnclaw`, `Restart=always`). Two ways to restart, depending on privileges:

1. **With sudo (preferred — clean restart):**
   ```
   sudo systemctl restart tradeai-portfolio-server
   ```
   In a Claude Code session, run it via the `!` prefix so it executes in the operator's shell:
   `! sudo systemctl restart tradeai-portfolio-server`
   To allow this without an interactive password prompt, grant passwordless sudo for just this unit — create `/etc/sudoers.d/portfolio-server` (via `sudo visudo -f /etc/sudoers.d/portfolio-server`) containing:
   ```
   johnclaw ALL=(root) NOPASSWD: /usr/bin/systemctl restart tradeai-portfolio-server, /usr/bin/systemctl stop tradeai-portfolio-server, /usr/bin/systemctl start tradeai-portfolio-server
   ```

2. **Without sudo (kill + auto-respawn):** the process is owned by `johnclaw`, so SIGTERM/SIGKILL it and `Restart=always` brings it back in seconds — no sudo needed. This is how automation (and the hang watchdog) recovers it:
   ```
   kill -TERM "$(pgrep -f scripts/portfolio_server.py | head -1)"   # SIGKILL if it survives
   ```
   Note: `systemctl restart` itself requires interactive auth and will fail for `johnclaw` without the sudoers rule above.

After restart, verify: `curl -s -o /dev/null -w '%{http_code}' http://localhost:7777/api/health` → `200`. The hang watchdog (`scripts/portfolio_server_watchdog.sh`, cron */2) performs this kill+respawn automatically if `/api/health` stops responding. `api_v2.py` edits hot-reload on the next request (mtime-gated); edits to `portfolio_server.py` itself require a restart.

### Recovery Procedures

Full disaster recovery documented in `docs/RESTORE_GUIDE.md`:
- 6 core services to restore
- 23-point preflight check
- DB restore sequence
- Cron re-installation
- OpenClaw reconfiguration

---


---

## 18b. Hermes Sidecar — Advisory Challenger and Memory Layer

Hermes is Trade AI's near-24/7 research desk, second brain, memory layer, and independent challenger. It is NOT a separate trading worker.

**Key facts:**

- Hermes is installed as a project-scoped sidecar at `hermes_sidecar/`
- Trade AI remains the system of record and only execution authority
- Hermes writes only to `hermes_*` staging tables — never to production execution tables
- Hermes has no broker access, no proposal/trade/journal mutation authority
- Research auto-promotion (staged → promoted → optional RAG embedding) is **bounded and reversible** — it concerns research intelligence only and does **not** relax any trade/proposal gate (Safety Rules §19 hold)

**Current state (2026-06-03):**

- **Chief Coordinator runs the fleet live** (`--apply`) on a `*/15` flock-guarded cron (`scripts/hermes_coordinator.py`), per Operator Directive B (2026-06-02). Verified live 2026-06-03 (tick 08:09: "3 promoted, 4 agents run").
- Per-tick caps: librarian 10, autonomous loop 3/sub-loop, promote 10, embed 2.
- Autonomous loop: `ticker_challenger` + `pipeline_quality` sub-loops via Coordinator.
- Weekly source curation: Sun 11:30 PM (`scripts/hermes_source_curation.py` → `research_sources`).
- Model: gemma3:12b primary / gemma3:4b for fast continuous loops, via local Ollama (no external APIs).
- Kill switch: `touch hermes_sidecar/.hermes/DISABLED` (master); also `COORDINATOR_DISABLED`, `LIBRARIAN_DISABLED`.
- Gateway: active on port 18790 (systemd, auto-restart). Dashboard: v3 HermesHub (`/v3/`, Hermes hub).

**Full Hermes workflows** (fleet roster + run-state, per-tick caps, workflow chain, safety controls, v3 surfaces): see `docs/AGENT_AND_HERMES_WORKFLOWS.md` Part 2.

**Staging tables (6):** hermes_research_intelligence, hermes_validation_findings, hermes_alerts, hermes_embedding_queue, hermes_memory_events, hermes_promotion_audit

**Promoted advisory cache:** 7 rows in `llm_intelligence_cache` (hermes_* namespaced sections). Advisory only — not execution signals.

**Open-position protection surface (Phase 190):** safe view `hermes_v_open_position_protection_context` exposes broker-stop/take-profit/protection state for open paper trades; `hermes_open_position_protection_check.py` writes advisory `hermes_validation_findings` (6 protection finding types) → `hermes_alerts`. Advisory only — no trade mutation. See §10 *Stop Protection Verification & Tracking*.

**Full documentation:** `docs/hermes/` (design, architecture, phase reports, rollback files, operator runbook)

## 19. Safety Rules (Non-Negotiable)

These rules are non-negotiable. No automation, agent, or operator override may violate them.

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | `LIVE_TRADING_ENABLED=false` -- never change | `.env` + code assertion |
| 2 | `ALPACA_MODE=paper` -- never change | `.env` + adapter check |
| 3 | No risk gate threshold changes without explicit owner approval | UI gate + audit log |
| 4 | No auto-approval of proposals -- human-in-the-loop required | Proposal state machine |
| 5 | No holdings modification by automation | Read-only portfolio access |
| 6 | Holdings value must remain > $1M | Assertion check in code |

**Validation gate:** Live trading will not be enabled until:
- 6-month paper validation window closes (~Nov 2026)
- Win rate >= 55%
- Profit factor >= 1.3
- Full governance review completed

---

## 20. Key File Locations

| Path | Purpose |
|------|---------|
| `.env` | All secrets, API keys, feature flags |
| `.env.example` | Template with all variables documented |
| `config/strategies/*.yaml` | 24 strategy definitions (loaded dynamically) |
| `assets/screeners.yaml` | Finviz screener URLs + run windows |
| `assets/portfolio_accounts.yaml` | Account definitions |
| `assets/weights.yaml` | Asset allocation weights |
| `data/portfolios/state/holdings.json` | Portfolio state (current holdings) |
| `data/portfolios/state/personal_situation.json` | Personal data (18 keys) |
| `data/state/ticker_enrichment_cache.json` | Enrichment cache (1,139 symbols) |
| `scripts/api_v2.py` | All 275+ API endpoints (13,000+ lines) |
| `scripts/portfolio_server.py` | HTTP server with token auth (1,800+ lines) |
| `scripts/portfolio_orchestrator.py` | Orchestration hub with dividend alerts (1,750+ lines) |
| `scripts/recovery_watch_daily.py` | Recovery watch with exit classification (true stop-out vs relist) |
| `scripts/generate_weekly_docx.py` | Weekly consolidated Word report from all subsystems |
| `scripts/cio_decision_engine.py` | CIO decisions with 24h dedup gate |
| `scripts/alert_dispatcher.py` | Central alert routing (dedup, tiers, fatigue, rate limit) |
| `scripts/alert_missing_conditions.py` | Daily missing condition checks (proposals, API, email, rebalance) |
| `scripts/llm_intelligence_enrichment.py` | Daily LLM narrative generation (5 sections via gemma3:12b) |
| `scripts/feedback_loop_processor.py` | Outcome chains, alert scoring, strategy snapshots, agent tracking |
| `scripts/backup_verify.py` | Monthly backup integrity verification |
| `scripts/trade_ai_orchestrator.py` | Screener + scoring (873 lines) |
| `scripts/local_llm_config.py` | LLM configuration hub |
| `scripts/local_llm.py` | Ollama inference with toll gate |
| `scripts/topic_ingestion.py` | Topic-based content ingestion (4-source cascade) |
| `scripts/topic_curator.py` | Post-ingestion curation (rate, extract, link, improve) |
| `scripts/youtube_transcript_ingest.py` | YouTube video/channel ingestion (4-method transcript fetch) |
| `scripts/telegram_command_handler.py` | Telegram command handler (add video, add article, research, etc.) |
| `sql/migrations/` | 22 SQL migration files |
| `crontab_backup.txt` | Full cron schedule backup |
| `requirements.txt` | 376 Python packages |
| `docs/RESTORE_GUIDE.md` | Disaster recovery guide |
| `docs/project/agents_bible.md` | Agent behavior rules |
| `docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md` | Strategy playbooks |

---

## 21. Known Constraints

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| LLM classification speed | ~4.5 min/symbol on Intel Arc B50 (GPU) | Scheduled overnight; toll gate queuing |
| Finviz cookie expiry | Periodic manual browser authentication | Dual auth (cookie + API token); alert on 0-result scans |
| yfinance rate limits | ~2-3s throttle per symbol | Batch processing with delays |
| LLM-only strategies | 14/24 strategies need LLM (data not in enrichment cache) | Scheduled overnight batch |
| Proposal enrichment latency | ~30s-1min per proposal | Chunked async state machine |
| Single-server deployment | No HA, single point of failure | 7-day rolling pg_dump; documented restore guide |
| API authentication | Token-based auth via `API_AUTH_TOKEN` in .env | Set token to enable; frontend exempt; all /api/ paths checked |
| Anthropic API credits depleted | Rebalance advisor (`portfolio_yaml_advisor.py`) cannot refresh | Requires credit top-up or local LLM fallback |
| CIO daily duplicate decisions | Same symbol+action generated daily | 24h dedup gate added to `cio_decision_engine.py` |
| StockTwits pre-market persistence | Was Telegram-only, invisible to dashboard | Fixed: now writes to `social_posts`, `trade_ai_scans`, `scalp_scan_results` |
| Alpaca OCA limitation | Cannot hold stop + target orders simultaneously on same shares | Target monitored by `paper_trade_monitor.py` every 5 min; at 80% of move, stop tightens aggressively |
| Paper trading validation period | 6-month window required before live trading | Live trading gate tracks 4 metrics; all currently FAIL |

---

## 22. Glossary

| Term | Definition |
|------|------------|
| GO | Screener decision: symbol qualifies for trading |
| WAIT | Screener decision: monitor but do not trade |
| NO-GO | Screener decision: disqualified |
| RVOL | Relative volume vs. 20-day average |
| ATR | Average true range (14-period) |
| R:R | Risk-to-reward ratio |
| TCA | Transaction cost analysis |
| ENTRY_MISSED | Price moved beyond the defined entry zone |
| ENTRY_ZONE_VALID | Price is still within tradeable entry range |
| Pipeline chevron | Visual 8-stage progress indicator for proposals |
| Toll gate | `fcntl.flock()` serialization for GPU access |
| Incubator | Holding area between screener hits and proposals |
| Enrichment cache | Pre-computed Finviz + fundamental data per symbol |
| Strategy YAML | Dynamic strategy definition file loaded at runtime |
| Paper mode | All trades executed on Alpaca paper (simulated) |
| Profit factor | Gross profit / gross loss ratio |
| Relist | Vehicle/symbol reappears in portfolio without a confirmed exit -- market behavior, not strategy failure |
| Patience score | Accumulated score for relisted positions (0.0-1.0) -- higher = more sustained engagement without exit |
| Exit classification | Categorization of stop events: true_stop_out, relist_no_exit, market_reconnection, unclassified |

---

## 23. Automation Intent & Production Readiness

### System Design Intent

Trade AI v12 is designed as a **fully automated profit-seeking trading system** with professional risk controls. The system is intended to:

1. **Discover** candidates automatically (screeners, incubator, social, news)
2. **Evaluate** them through multi-strategy scoring, agent analysis, and LLM review
3. **Propose** trades with computed entry/stop/target levels
4. **Execute** instantly on approval — system determines order type and parameters
5. **Manage** open positions automatically — trailing stops, profit targets, dynamic adjustment
6. **Close** positions on target hit or stop trigger — no manual intervention required
7. **Learn** from outcomes — feed P&L back to agent calibration and strategy scoring

Human intervention points: proposal approval (go/no-go decision) and system configuration. Everything else is automated.

Currently in **paper-only validation mode** (6-month validation window before live consideration).

### Live Trading Gate

Live trading is locked behind 4 gates (all must pass simultaneously):

| Gate | Requirement | Current (2026-06-03) | Status |
|------|------------|---------|--------|
| Win Rate | >= 55% | 59.1% (broker-proven) | metric met, blocked on sample |
| Profit Factor | >= 1.3 | 3.66 | metric met, blocked on sample |
| Sample Size | >= 30 closed trades | 22 | NOT MET |
| Time in Paper | >= 6 months | ~0.9 months | NOT MET |

**Counting rule (STEP 3b):** the win-rate/profit-factor counts **exclude integrity-flagged phantoms** (`outcome_verdict='PHANTOM'` or `close_reason='phantom_no_alpaca_position'`) — a phantom was never a real broker round-trip, so counting it (it previously scored as a `pnl<=0` loss) deflated the metric. Rule = **exclude-provably-fake**: real legacy/unconfirmable trades and genuine breakevens are kept. This lifted the honest win rate from 44.8% → **59.1%** (sample 29 → 22). The gate **stays closed** — sample (22<30) and duration (0.9<6mo) still fail. Verified vs rigorous `confirm_fill` (`step3_reconcile_filter.py`): no provably-fake row is counted; #29 NVDA is caught. The number is conservative (breakevens count as losses).

Gate status is available at `/api/v2/live-trading-gate`.

### API Authentication

- **Method:** Bearer token via `API_AUTH_TOKEN` environment variable
- **When enabled:** All `/api/*` requests require `Authorization: Bearer <token>` header
- **Exempt paths:** `/v2/` (frontend), `/data/` (state files), `/reports/`, `/api/health`
- **When not set:** Auth is disabled (open access, internal-only assumption)
- **Query param fallback:** `?token=<token>` for browser testing

### Backup Verification

- **Script:** `scripts/backup_verify.py`
- **Schedule:** Monthly (1st of month)
- **Checks:** pg_dump exists + recent, backup size non-trivial, state files fresh, DB connectivity
- **Reports:** Via Telegram alert dispatcher (severity based on findings)

### Performance Budget

| Component | Target | Notes |
|-----------|--------|-------|
| API response (p95) | < 500ms | All GET endpoints |
| Morning pipeline | 07:00 - 08:00 ET | Full cascade: data refresh → enrichment → alerts → brief |
| LLM enrichment | < 120s total | 5 sections via gemma3:12b |
| Screener full run | 10:00 AM + 4:00 PM | Weekdays only |
| Overnight batch | 8:00 - 10:00 PM | Metrics, stale refresh, agent perf |
| Weekly DOCX | Sunday 9:00 PM | After all weekly jobs |

### High Availability Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Server failure | Total outage | 7-day rolling pg_dump, restore guide, state file backups |
| GPU failure | LLM enrichment stops | Cloud fallback chain (xAI → Anthropic → OpenAI) |
| API credits depleted | Rebalance advisor unavailable | Local LLM covers most use cases, alert on depletion |
| Finviz auth failure | Screener returns 0 results | Dual auth (cookie + API token), health check alerts |
| Ollama crash | All local LLM calls fail | Auto-restart via systemd, warmup function on cold start |

---

## 23c. Inference Layers — Higher-Order Reasoning (2026-06-21)

A modular, reusable layered reasoning pipeline that sits **on top of** the existing
intelligence stack (Hermes, RAG, LLM enrichment, journal analytics, topic curation,
risk gate, proposal lifecycle) and synthesizes everything into higher-order,
actionable inferences. Advisory-only — no execution path. Full design:
`docs/project/INFERENCE_LAYERS.md`.

- **Engine:** `scripts/inference_layer_engine.py` (`--run` / `--latest` / `--dry-run`);
  config `config/inference_layers.yaml`; cron `linux_launchers/run_inference_cycle.sh`.
- **Layers** (`scripts/inference_layers.py`): L1 Ingestion & region-tagging · L2
  Feature/regime extraction · L3 Cross-regional synthesis (Asia→US ETF/CEF, e.g. PTY)
  · L4 Higher-order (journal patterns, NAV premium/discount, opportunity/risk,
  **risk-appropriate sizing**, proactive Hermes queries).
- **Substrate:** `inference_hermes_query.py` (local gemma3 first, grok/chatgpt
  escalation, RAG injection, `proactive_query` autonomy), `inference_financial_modeling.py`
  (CEF/ETF NAV premium/discount, honest measured-vs-estimate flag),
  `inference_sizing.py` (tilt over `account_policy.compute_sizing`, re-validated by
  `risk_gate`), `inference_telegram.py`, `inference_api.py`.
- **Data:** `inference_runs`, `inference_results`, `inference_regional_signals`,
  `inference_sizing_recommendations`, `inference_memory`, `inference_proactive_queries`;
  `news_articles.region/geo_keywords` added. Schema: `create_inference_schema.py`.
- **Surfaces:** `/api/v2/inference/*` (delegated from `api_v2.handle`), Telegram digest,
  Intelligence-hub `InferenceLayersPanel`.

## 24. Session Changelog

### Session — 2026-06-21 (Inference Layers v1)

Built the modular Inference Layers system (12 new files, ~1,900 lines) — a layered
reasoning pipeline extending Hermes/RAG/journal/risk/proposal subsystems into
higher-order advisory inferences, region-aware (Asia→US/CEF), with risk-appropriate
sizing and a proactive "mind of its own" query loop. Verified end-to-end live
(run #1: 9 inferences, regime=risk_off, Asia signal, journal edge, NAV reads).
See §23c and `docs/project/INFERENCE_LAYERS.md`.

Same-day enhancements: (1) cron installed (weekday 08:00/13:00/16:30 ET, flock-guarded);
(2) autonomous gap-detection→prioritize→act pass (`inference_autonomy.py`) with string-
coercion, retry, and deterministic state-grounded fallback; (3) whole cycle routed to
the free **grok** OAuth lane (`llm.use_external_lane`+`salience_threshold:0.0`, plus
`autonomy.detection_lane`/`action_lane`) — full cycle ~69-117s on grok vs local stalls;
(4) `income_funds` trimmed 10→5 (PTY + held) to cut NAV call volume; (5) root-cause fix
to `notification_url_builder` so ALL Telegram/email links carry the FQDN **with :7777**;
(6) `telegram.min_severity` raised to **high** (high/critical only).

### Session 29 — 2026-05-11 (Phases 1-8)

12 commits, ~9,000 lines added across 65+ files. All changes are integrated into the sections above.

| Phase | Summary | Key Artifacts |
|-------|---------|---------------|
| **1. Fix What's Broken** | Re-entry vs stop-out classification, StockTwits pipeline fix, 4 new API endpoints, weekly DOCX, prospects entry/stop/target | `20260511_reentry_vs_stopout_classification.sql`, `generate_weekly_docx.py` |
| **2. Alert Quality** | Central alert dispatcher with dedup + fatigue + tiers, missing condition alerts, morning brief upgrade | `alert_dispatcher.py`, `alert_missing_conditions.py` |
| **3. Page Consolidation** | 61 → 42 primary routes via TabPage component. 8 merges, 3 eliminations. Legacy routes redirect. | `TabPage.tsx`, 8 hub pages, updated `App.tsx` + `Shell.tsx` |
| **4. Intelligence Delivery** | Morning Command page, market intelligence API, per-page news/social/sector context, CIO news context | `Command.tsx`, `/api/v2/command`, `/api/v2/market-intelligence` |
| **5. LLM Integration** | 5 daily intelligence sections via gemma3:12b. Portfolio risk, rebalance, recovery, morning synthesis, prospect narratives. | `llm_intelligence_enrichment.py`, `llm_intelligence_cache` table |
| **6. UI/UX** | Global alert banner (4 active alerts), freshness badges (green/yellow/red), Today's Actions panel on Overview | `GlobalAlertBanner.tsx`, `FreshnessBadge.tsx` |
| **7. Feedback Loops** | Proposal outcome chains (38 linked), alert effectiveness scoring (31 scored), strategy snapshots (4), agent sample tracking | `feedback_loop_processor.py`, `20260511_feedback_loop_closure.sql` |
| **8. Production Readiness** | API auth (token-based), backup verification (10/10 passing), live trading gate (4 gates, all FAIL = paper only) | `backup_verify.py`, `/api/v2/live-trading-gate` |

### Session — 2026-06-03 (Rating surfacing + workflow docs)

| Area | Summary | Key Artifacts |
|------|---------|---------------|
| **Entry/exit ratings** | Surfaced existing grade data where the operator looks: inline entry/exit **Grade column** in v3 Journal trade log; **"entry setup ~N"** badge per open position in v3 Trading. Diagnosed coverage (~74/76 Schwab closed trades graded). | `api_v2.py:_attach_backtest_grades()`, `JournalHub.tsx`, `TradingHub.tsx` |
| **Agent & Hermes workflows** | New canonical workflow reference; corrected stale MASTER §18b (Hermes now live coordinator-driven `*/15`, bounded reversible auto-promote — research only, no trade-gate relaxation). | `docs/AGENT_AND_HERMES_WORKFLOWS.md`, MASTER §11/§18b, `COMMAND_CENTER_PAGE_MATRIX.md` |
| **DOCX** | Append-only session addendum to canonical Reference Architecture. | `scripts/update_docx_session_2026_06_03.py` |

### Session — 2026-06-03b (Server hang fix + dashboard accuracy + v3 additions)

| Area | Summary | Key Artifacts |
|------|---------|---------------|
| **Server hang (critical)** | Portfolio server deadlocked (alive, serving nothing; `/v2/` & `/v3/` down) from `importlib.reload(api_v2)` on every request under concurrent dashboard polling. Fixed: mtime-gated + lock-guarded reload (`_get_api_v2()`) — reloads only on file change; also a big latency win (~25ms vs full-module reload). Added hang **watchdog** (cron */2) since `Restart=always` only catches crashes, not hangs. | `portfolio_server.py:_get_api_v2()`, `scripts/portfolio_server_watchdog.sh`, MASTER §18 |
| **Agent "last run" accuracy** | Dashboard showed aegis/iris as stale though both ran. Root cause: `agents/summary` derived `last_run` only from `watchlist_agent_results`; iris writes to `iris_run_log.ran_at`. Fixed iris via `_AGENT_HOME_TABLES`. aegis was correct (nightly brief cadence). Added staleness coloring (prevention) + honest "no handoffs" copy (worker agents don't write `agent_handoffs`; synthesis/Alex/auto_research/system do). | `api_v2.py:_agents_summary()`, `AgentsHub.tsx` |
| **v3 Trade AI tab** | Ported v2 `/v2/trade-ai` market-opportunities scanner into v3 Trading hub (GO/WAIT/NO-GO, score/RVOL/catalyst/critic, run KPIs). | `TradingHub.tsx`, `/api/v2/trade-ai` |
| **v3 Portfolio account filters** | Account filter chips on Holdings (per-account counts/value). | `PortfolioHub.tsx` |
| **Human Review actions** | Escalation-queue drawer now has navigation links (Inbox, Agent Collaboration) + clear action explanation. DetailDrawer gained read-only `links`. | `AgentsHub.tsx`, `DetailDrawer.tsx` |
| **Drive sync** | Large-file (>1 MB) markdown no longer `--convert-to=doc` (Google conversion timed out on a 3.4 MB report); uploads raw so it mirrors. | `scripts/sync-docs-to-drive.sh` |
