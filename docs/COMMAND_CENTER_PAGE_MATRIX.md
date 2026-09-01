# Command Center — Complete Page Matrix

Status:      ACTIVE
as_of:       2026-08-11T08:38:52-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-27 | Total pages: 67 | Nav groups: 11

## Navigation Structure

### Command
| Route | Label | What it does |
|---|---|---|
| `/v2/command` | Command Center | Daily intelligence dashboard. Priority action banners, portfolio KPIs, triggered stops, paper trades, proposals/CIO/recovery queue, news, AI briefing, agent health panel |
| `/v2/agent-collaboration` | Agent Collaboration | RACI matrix, cross-agent missions (7 types), handoffs, escalations, operator action items. Two-pane: mission list + inspector |
| `/v2/inbox` | Inbox | Notification center. Aggregates alerts, proposals, agent escalations needing operator review |
| `/v2/morning-brief` | Daily Brief | Morning decision queue. Risk exposure, opportunity panel, trust strip, command strip |

### Trading
| Route | Label | What it does |
|---|---|---|
| `/v2/trade-ai` | Trade AI | Market opportunities scanner. GO/WAIT/NO-GO decisions from orchestrator pipeline |
| `/v2/prospects` | Prospects | Prospect pipeline. Total prospects with strategy matching and scoring |
| `/v2/strategy-desk` | Strategy Desk | Strategy signals dashboard. Create paper trade proposals from signals |
| `/v2/incubator` | Incubator | Incubator universe. Recent events, classification, promotion pipeline to proposals |
| `/v2/atm-control-room` | ATM Control Room | Automated Trade Mode control. ATM state, position limits, kill switches, audit trail |
| `/v2/automated-trade-mode` | ATM Mode | ATM settings. Mode toggle (active/paused/disabled), account config, B-1 tracking |

### Portfolio
| Route | Label | What it does |
|---|---|---|
| `/v2/portfolio` | Holdings | Portfolio command center. All holdings across accounts with P&L, allocation, market value |
| `/v2/dividends` | Dividends | Dividend calendar, income by month, ex-dates, yield analysis |
| `/v2/returns` | Returns | Performance & returns. Period returns, benchmarks, attribution |
| `/v2/attribution` | Attribution | Top contributors/detractors. Position-level P&L attribution |

### Risk & Alerts
| Route | Label | What it does |
|---|---|---|
| `/v2/risk` | Risk Dashboard | Portfolio risk. Heat map, positions without stops, triggered stops, concentration |
| `/v2/alerts` | Alert Dashboard | Active alerts. Stop triggers, price alerts, system warnings |
| `/v2/risk-regime` | Risk Regime | VIX regime tracking. High/medium/low volatility classification with rules |
| `/v2/recovery` | Recovery Watch | Stopped-out positions. Analyst verdict (reentry candidate/avoid), confidence scores |

### AI Analyst
| Route | Label | What it does |
|---|---|---|
| `/v2/ai-analyst` | AI Advisory | AI-powered position analysis. Per-holding recommendations from agents |
| `/v2/technical` | Technical / PI | Technical health across all holdings. RSI, VWAP, support/resistance |
| `/v2/watchlist` | Watchlist | Watchlist workbench. Multi-agent research on tracked symbols |
| `/v2/watchlist/:symbol` | (symbol detail) | Deep dive on single symbol. Agent analyses, news, technicals, strategy cards |
| `/v2/cio` | CIO Dashboard | CIO intelligence. Alex-generated decisions, priority actions, rationale |

### Research
| Route | Label | What it does |
|---|---|---|
| `/v3/research-intelligence` (**CC v3 canonical**) | Research Intel | **Taxonomy-tagged intelligence cockpit** — Hermes + auto-research + topic_monitor; priority lanes (Retirement, Dividends, Macro/Sector); search/filter; holdings-aware. API: `/api/v2/research-intelligence` |
| `/v2/research-topics` | Research Topics (legacy list) | Research topic tracking. Iris-managed knowledge base, gap detection — linked from RI as “Legacy Research Topics” |
| `/v2/topic-monitor` | Topic Monitor | Topic freshness monitoring. Stale topics, coverage gaps |
| `/v2/research` | Ticker Research | Per-ticker research. Analyst data, financials, news, earnings |
| `/v2/intelligence` | Intelligence Hub | Intelligence aggregation. Sources, entities, sentiment |
| `/v2/overnight` | Overnight Brief | Overnight intelligence. Aegis-generated synthesis, market context |

### System & Pipeline
| Route | Label | What it does |
|---|---|---|
| `/v2/ops` | Ops Center | Automation trust center. Cron health, pipeline runs, system status |
| `/v2/pipeline` | Pipeline Stages | Pipeline health. Stage-by-stage execution status, timing, errors |
| `/v2/system-health` | System Health | System services health. API status, DB connections, LLM availability |
| `/v2/agent-pipeline` | Agent Pipeline | Agent operational dashboard. Queue metrics, LLM budget, per-symbol intelligence consensus, handoffs, events |

### Automated Trading
| Route | Label | What it does |
|---|---|---|
| `/v2/paper-proposals` | Proposals | Paper trade proposals. Pending/approved/rejected with enrichment status, execution readiness |
| `/v2/paper-review` | Trade Review | Paper trade review & learning. Closed trades analysis, lessons |
| `/v2/paper-status` | Trade Status | Open paper trades. Position monitor, stop levels, P&L, broker sync |
| `/v2/execution-quality` | Execution Quality | TCA (Transaction Cost Analysis). Slippage, timing, fill quality |
| `/v2/proposal-alerts` | Proposal Alerts | Proposal alert board. Telegram alert history, delivery status |

### Tax & Rebalance
| Route | Label | What it does |
|---|---|---|
| `/v2/tax` | Tax & Lots | Tax lot management. Wash sale tracking, gain/loss by lot |
| `/v2/rebalance` | Rebalance | Portfolio rebalancing. Target vs actual allocation, drift |
| `/v2/retirement` | Retirement | Retirement planning. Account type allocation, Roth/IRA/401k strategy |

### Learning & Improvement
| Route | Label | What it does |
|---|---|---|
| `/v2/agent-lifecycle` | Agent Lifecycle | 7-stage operational model (Define→Design→Build→Evaluate→Deploy→Monitor→Improve). Per-agent lifecycle state, functional stage panels with forms/data, live quality scores, requirement intake |
| `/v2/self-improvement` | Self-Improvement | Self-improvement center. Agent lessons, calibration feedback, iteration tracking |
| `/v2/agent-calibration` | Agent Calibration | Agent accuracy scoring. Per-agent calibration windows, accuracy %, correct/wrong counts, calibration error, scored events |
| `/v2/weekly-learning` | Weekly Learning | Weekly learning digest. Trade outcomes, agent performance trends |

### Governance & Admin
| Route | Label | What it does |
|---|---|---|
| `/v2/governance` | Governance Hub | Governance center. Safety checks, ALPACA_MODE, compliance, system facts |
| `/v2/strategy-admin` | Strategy Admin | Strategy configuration. YAML editor, screener config, strategy parameters |
| `/v2/strategy-analytics` | Strategy Analytics | Strategy scoreboard. Per-strategy win rate, R-multiple, sample size |
| `/v2/correlation` | Correlation | Position correlation analysis. Sector/factor exposure |
| `/v2/forecast` | Forecast | Portfolio forecast. Projected returns, income, growth scenarios |
| `/v2/broker-reconciliation` | Broker Recon | Broker reconciliation. DB vs Alpaca position matching, orphan detection |
| `/v2/plan-vs-performance` | Plan vs Perf | Plan vs performance. Proposal entry vs actual, stop adherence |

### Reports
| Route | Label | What it does |
|---|---|---|
| `/v2/reports` | Reports Hub | Report generation. Export portfolio, performance, tax reports |
| `/v2/journal` | Trade Journal | Trade journal hub. Manual + automated entries, P&L tracking, equity curve |
| `/v2/backtesting` | Backtesting | Strategy backtesting. Historical signal testing, parameter optimization |

## Hidden/Legacy Routes (no nav entry)
| Route | Component | Purpose |
|---|---|---|
| `/v2/agent-dashboard/:agentId` | AgentDashboard | Per-agent deep dive (linked from agent chips) |
| `/v2/bot-morning-brief` | MorningBriefBot | Bot-generated morning brief variant |
| `/v2/hub` | OpsHub | Legacy ops hub route |
| `/v2/orchestration` | OpsHub | Legacy orchestration route |
| `/v2/actions` | Inbox | Legacy actions route |
| `/v2/notifications` | Inbox | Legacy notifications route |
| `/v2/live-governance` | GovernanceHub | Legacy governance route |
| `/v2/intelligence-entities` | IntelligenceHub | Legacy intelligence route |
| `/v2/intelligence-sources` | IntelligenceHub | Legacy intelligence route |
| `/v2/intelligence-whiteboard` | IntelligenceHub | Legacy intelligence route |
| `/v2/pipeline-controller` | PipelineHub | Legacy pipeline route |
| `/v2/pipeline-health-master` | PipelineHub | Legacy pipeline route |
| `/v2/portfolio-intelligence` | PortfolioCommand | Legacy portfolio route |
| `/v2/portfolio-monitor` | PortfolioCommand | Legacy portfolio route |
| `/v2/paper-trade-intelligence` | PaperReview | Legacy paper trade route |

## v3 Strategy → Backtest (canonical, 2026-06-02)

Route `/v3/strategy` → **Backtest** tab. Full read-only port of v2 `/v2/backtesting` (`BacktestPanel.tsx`) plus a Backtest Intelligence layer. Defaults to `run_type=replay_trades` (real data; champion rows are seeded sims). All write/POST controls removed (read-only).

| Element | What it shows | Data source |
|---|---|---|
| Cadence strip | Last run + runs/day sparkline; backtest schedule | `/api/v2/backtesting/runs` |
| KPI tiles | Datasets, runs, backtest rows, results, strategy coverage, flagged, missed | `/api/v2/backtesting/status` |
| Overview | Win-rate-by-strategy (click→filter), R-multiple distribution, missed impact | `/api/v2/backtesting/trades`, `/missed-opportunities` |
| **Edge Decay** | Backtest win-rate vs live paper win-rate per strategy (overfit detection) | `/api/v2/backtesting/trades` + `/api/v2/paper-trade-readiness` |
| **Entry Quality** | Entry/exit A–D grades, RSI-vs-outcome, coaching, best entries ("how was our entry") | `/api/v2/journal/backtest-summary`, `/api/v2/journal/backtest-analytics` |
| **AI Trade Eval** | Structured LLM trade evaluation (gemma3:12b): 6 scores + verdict per trade, verdict distribution, drill into full reasoning. Research/journaling only — not advice. Judges on RSI/MACD/ADX/Bollinger/Fibonacci/structure/candlestick (VWAP/intraday excluded). Also shows the **setup-quality prior** (what entries have worked, by RSI band) that feeds the ATM advisory. | `/api/v2/backtesting/trade-evaluations`, `/api/v2/atm/setup-advisory` |

**Feedback loop (advisory-only, never gates):** the setup-quality prior attaches a caution/favorable badge ("⚠ setup ~N") wherever an entry/candidate's RSI falls in a historically weak/strong band:
- **Trading → Proposals** — per-proposal advisory. Source: `/api/v2/atm/setup-advisory`.
- **Trading → Open Trades** (2026-06-03) — per open position, an "entry setup ~N" badge matched by symbol, since open trades have no exit grade yet. Source: `/api/v2/open-trades` + `/api/v2/atm/setup-advisory`.
- **Strategy → Incubator** — per-candidate advisory badge. Source: `/api/v2/setup-advisory/candidates?entity=incubator`.
- **Watchlist** (new v3 page, nav `/v3/watchlist`) — active items + advisory strip + per-item badge. Source: `/api/v2/watchlist/items` + `/api/v2/setup-advisory/candidates?entity=watchlist`.

Never blocks execution, promotion, or scoring.
| **Capture** | Cumulative money-left-on-table over time, by-trade-type, worst exits | `/api/v2/backtesting/mfe-analysis`, `/api/v2/journal/backtest-analytics` |
| **Potential Over Time** | Run-over-run hypothetical performance (append-only history) | `/api/v2/backtesting/result-history` |
| Strategy / Trades / Missed / Results / Runs | Ported v2 tables + charts | `/api/v2/backtesting/{results,trades,runs,missed-opportunities}` |
| Trail Analysis / MFE-MAE / Optimization / LLM Review Coverage | Ported v2 analysis tabs | `/api/v2/backtesting/{trailing-stop-analysis,mfe-analysis,trailing-optimization}`, `/api/v2/lifecycle/llm-review-status` |
| Drill drawer | Sparkline + entry/exit grade badges + per-trade backtest lookup (Journal↔Backtest link) | `/api/v2/journal/backtest/{key}` |

## v3 Journal — entry/exit grade column (2026-06-03)

The Journal trade log now shows an inline **Grade** column (entry/exit letter grades A–D, colored) for every closed trade, in addition to the existing drill-drawer badges. Grades come from backtest-replay grading (`trade_backtest_results`) joined server-side on `trade_key` (`{symbol}:{account}:{close_date}`).

- Coverage: ~74/76 Schwab closed trades graded; paper trades are not backtest-graded (show "—").
- Backend: `/api/v2/journal` and `/api/v2/automated-trade-journal` rows enriched via `_attach_backtest_grades()` (adds `entry_grade`, `exit_grade`, `entry_rsi`, `left_on_table_20d`).
- Advisory/retrospective only; never gates anything.

## v3 Agents hub (rebound + Workflow, 2026-06-02)

Route `/v3/agents`. Previously mis-wired (showed "Agent 0…9", raw JSON, bare numbers). Fixed to bind the real fields; added a React Flow workflow view. Read-only.

| Tab | What it shows | Data source (correct fields) |
|---|---|---|
| **Roster** | Named agents + actions, buy/sell/hold, avg-conf, last-run, proposal-allowed/shadow-only badge | `/api/v2/agents/summary` (field **`agent`**, not `name`) |
| **Calibration** | Per-agent cards: accuracy ring, correct/wrong/neutral bar, Confidence/Cal-err/Overconf/Underconf, **PROPOSAL ALLOWED / SHADOW ONLY** badge, recs/symbols/resolved | `/api/v2/agent-calibration/{status,windows,agents}` (windows carry `accuracy`, `sample_size_status`, `*confidence_score`) |
| **Workflow** *(new)* | React Flow graph — **★ Alex/CIO as orchestrator hub**; nodes = roster agents (colored by calibration health) + non-roster pipeline nodes (grey, e.g. synthesis/human_review/auto_research); **live edges** from `/agent-pipeline` (animated; escalations amber) + documented **configured chain** maria→steph→risk→tax (dashed, labeled, not live); click node → drawer with calibration + RACI + recent handoffs | `/api/v2/agent-pipeline` (live `from_agent→to_agent`+`escalated`) + `/agent-calibration/windows`. Live edges real; configured chain clearly labeled; none fabricated |
| ~~**Performance**~~ | **Removed 2026-07-09** — duplicate of Calibration; legacy `agent_performance_history` feed was stale. API `/api/v2/agent-performance` still maps calibration windows for v2/integrations. | — |

Roster shows real runtime model **gemma3:12b** (roster doc's qwen3:14b label is superseded/disabled). New dependency: `reactflow` ^11.11.4 (MIT) in `apps/command-center-v3`. **Wall:** this is the core OpenClaw fleet only — Hermes challenger agents are a separate population in the Hermes hub; no control edge crosses between them.

## v3 Hermes hub — Workflow tab (2026-06-02, separate fleet)

Route `/v3/hermes` → **Workflow** tab. The Hermes challenger fleet as a React Flow graph, kept in the Hermes hub (NOT the Agents hub) to preserve the challenger wall.

| Element | Detail | Source |
|---|---|---|
| Nodes | 7 Hermes agents + 1 external "Trade AI safe views" node | `HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md` |
| **Run-state — TWO AXES, validated** | Approval (governance, from contracts) vs **execution footprint (validated DB rows)**. operational-approved (Source Discovery 13, Promotion Review 15) = green; **running-but-NOT-approved** (Librarian 13 autonomous-loop, Backlog Mgr 5, Embedding Curator 9 — code wrote real rows, not governance-approved) = amber; design-only (Coordinator — 1 smoke-test row) = grey dashed; disabled (Autonomous Research Mgr) = red. Node shows real row count + mode; drawer shows approval and execution separately. | `/api/v2/hermes/agent-footprint` (validated per-agent rows) + contracts doc |
| Edges | Configured handoffs (dashed, **not** animated — most agents not live); Coordinator "orchestrates" edges | contracts handoff targets |
| **The wall** | ONE-WAY "reads (read-only)" arrow from Trade AI → Hermes agents only. **No control edge to the core fleet.** Kill-switch + autonomous-loop indicator | architecture mandate |
| Drawer | Per-agent contract: mission, allowed reads/writes, forbidden, caps, activation phase, live activity | contracts doc |

Run-state (validated 2026-06-02 against `/api/v2/hermes/agent-footprint`, then **operator-approved**): originally 2 approved + 3 running-but-unapproved; per operator directive the 3 staging-only running agents (Librarian, Backlog Manager, Embedding Curator) were **APPROVED 2026-06-02** (governance reconciled to validated footprint). Now: **5 approved-operational, 1 design-pending (Coordinator — smoke-test only), 1 disabled (Autonomous Research Manager — unchanged).** Approval is staging-only (no new powers; Forbidden lists unchanged); Embedding Curator approval does not cover the still-gated RAG worker. The two fleets stay separate; the only cross-link is the read-only arrow.

**Core Agents Workflow — pipeline nodes:** non-roster handoff endpoints (synthesis, auto_research, **human_review**) render as grey "pipeline" nodes. Their drawers describe the node and surface routed items (e.g. human_review = operator escalation sink, showing escalated symbols + reasons) rather than empty agent fields.

## v3 DetailDrawer (all modals) — readability overhaul (2026-06-02)

The shared drill drawer (`DetailDrawer.tsx`) used by **every** v3 modal now renders human-readable content instead of raw DB fields:
- Keys humanized (snake_case → Title Case + acronym map: RSI, MACD, P&L, RACI, CIO, ATR…).
- JSON-string blobs **parsed into readable nested sub-fields** (e.g. dual-opinion `tradeai_original`/`hermes_audit` → Score/Decision/Summary, not raw `{"…"}`).
- ISO timestamps formatted; statuses/verdicts color-coded (green=agree/operational/approved, red=disagree/disabled/error, amber=staged/caution/not-approved); `— Section —` keys render as headers.

Hermes **Research** tab: findings shown as plain-English cards (title + meaning + suggested resolution + where-to-resolve) with severity dots, de-duped and severity-sorted.

**Workflow drawers (Agents + Hermes) — work + schedule, not just tables (2026-06-02):** node drawers now show **active job classifications + counts** (Hermes = `research_type` breakdown from `/api/v2/hermes/agent-footprint`, e.g. "research_backlog: 25"; core agents = buy/sell/hold rec counts from `/agents/summary`), the **run mode** (live `--apply`, no longer stale "dry-run"), and the **schedule / next run** (Hermes = Coordinator cron */15, "≤15 min" or "HALTED" if kill switch armed; core = "*/10–15 via agent job worker"). Node labels show the top classification + row count.

## v3 Hermes — SearXNG / infra visibility + provenance (2026-06-03)

New endpoint `/api/v2/hermes/infra` (service health + web-source domains + research funnel) powers four additions:
- **A — SearXNG node** on the Workflow graph (Docker `127.0.0.1:18888`), edge → Source Discovery ("web search"), colored by live health.
- **B — per-finding sources**: Research-tab cards show the web-source domains (`source_urls_json`) a finding was based on (shown only when present — internal/self-generated findings have none).
- **C — infra health strip** (always visible): SearXNG (Docker), Ollama (loaded models), Hermes Gateway (pid), Postgres — green/red dots; click for detail. Surfaces silent-dependency failures.
- **D — Provenance tab** (new): funnel SearXNG → staged → promoted (→ core intel) → embedded (→ RAG) + top web-source domains, **plus a full React Flow provenance lane** (`/api/v2/hermes/provenance`) tracing each recent research item as a connected node: SearXNG/Internal → source domain → **🤖 producing agent** → research item (color = staged/promoted) → Core RAG (purple edge if embedded). Click an item → its full provenance (id, status, producing agent, web source, embedded?).

Gateway health reads the JSON `gateway.pid`; SearXNG/Ollama via HTTP ping.

## v3 Hermes — source self-learning + connectors (2026-06-03)

`hermes_source_curation.py` (cron nightly 23:30) + `/api/v2/hermes/sources` + new **Sources tab**:
- **Track A (self-learning):** every web domain scored by **yield = (promoted+embedded) ÷ research it produced**; ≥30% = preferred (boosted in future SearXNG queries), low = candidate/noise. Surfaced as a yield bar list + colors the provenance-lane domain nodes (green/amber/red). Example: trading-course domains (tradezella, warriortrading) auto-flagged red 0%.
- **Track B (new-site discovery):** domains seen for the first time auto-registered as candidates for vetting.
- **Connectors registry (`research_sources`):** social (Reddit/Stocktwits/X), YouTube transcripts, SEC Form 4 = **active** (live pipelines); RSS = `hermes_rss_ingest.py` (dormant until `config/hermes_rss_feeds.txt`); **OpenAI/Anthropic/xAI = ACTIVE** (keys already in `.env`) but **not auto-scheduled into the */15 loop** (API-cost guard — operator enables when ready); Seeking Alpha = dormant (needs key, via official API not cookies).

**Ingestion timing → TradeAI:** curated research reaches the core in **~15–30 min** (auto-promote → `hermes_advisory_cache_worker` writes `llm_intelligence_cache` hermes_* + RAG embeddings → core agents read next run), carrying SearXNG/source provenance — near-real-time, not same-second. **SearXNG never uses logins/cookies** (public metasearch only); your AIs/premium sources integrate via official APIs.

## Agent Pages Cross-Reference

| Page | Route | What it shows | Data sources |
|---|---|---|---|
| Agent Lifecycle | `/v2/agent-lifecycle` | 7-stage operational model, per-agent state, quality scores, requirement intake | `/api/v2/command`, `/api/v2/agent-calibration/agents`, `/api/v2/agent-health`, `/api/v2/agent-lifecycle/requirements`, `/api/v2/agent-lifecycle/quality-scores` |
| Agent Pipeline | `/v2/agent-pipeline` | Job queue, LLM budget, intelligence consensus, handoffs, events | `/api/v2/agent-pipeline`, `/api/v2/system-health`, `/api/v2/agent-health` |
| Agent Calibration | `/v2/agent-calibration` | Accuracy scoring, calibration windows, scored events, weight proposals | `/api/v2/agent-calibration/status`, `/api/v2/agent-calibration/agents`, `/api/v2/agent-calibration/windows`, `/api/v2/agent-calibration/events` |
| Agent Collaboration | `/v2/agent-collaboration` | RACI matrix, missions, handoffs, escalations, operator actions | `/api/v2/agent-collaboration`, `/api/v2/agent-detail/raci` |
| Agent Dashboard | `/v2/agent-dashboard/:id` | Per-agent deep dive: RACI, confidence, analyses, debates, events | `/api/v2/agent-dashboard`, `/api/v2/agent-detail/raci`, `/api/v2/agent-detail/escalation-trace` |

**No overlap — each page serves a distinct purpose:**
- **Lifecycle** = How should we manage agents? (process)
- **Pipeline** = What are agents doing right now? (operational)
- **Calibration** = How accurate are they? (quality)
- **Collaboration** = How do they work together? (governance)
- **Dashboard** = Deep dive on one agent (detail)

## v3 additions (2026-06-03b)

| Surface | What changed | Source |
|---|---|---|
| **Trading → Trade AI** (new tab, default) | Market-opportunities scanner ported from v2 `/v2/trade-ai`: GO/WAIT/NO-GO decisions, run KPIs (GO/WAIT/NO-GO/scanned/VIX/regime), per-ticker score/grade/RVOL/price/chg/catalyst/critic verdict; click → full scan detail. Read-only. | `/api/v2/trade-ai` |
| **Portfolio → Holdings account filter** | Account filter chips (per-account count + value); filters holdings table. | `/api/v2/portfolio/holdings` (field: account) |
| **Agents → Human Review drawer** | Escalation queue now shows navigation links (Open Inbox `/v2/inbox`, Agent Collaboration `/v2/agent-collaboration`) + a plain-language explanation of the operator action. Drawer is review-only; links navigate, never mutate. | `/api/v2/agent-pipeline` (handoffs) |
| **Agents → Roster "Last run"** | Staleness coloring (≤1.5d green, ≤3d amber, older red) so a genuinely stopped agent is obvious. iris last-run corrected (`iris_run_log.ran_at`). Worker-agent "no handoffs" copy clarified (handoffs are written by the synthesis/escalation pipeline, not individual workers). | `/api/v2/agents/summary` |

## v3 Portfolio — holding technical analysis (2026-06-03c)

Holding drill-drawer (`/api/v2/portfolio/holdings`) now shows a **Technical Analysis** panel:
- **Data-as-of timestamp** — newest mtime of `ticker_enrichment_cache.json` / `technical_snapshot.json` (response field `enrichment_as_of`).
- **RSI zone** — oversold (≤30, potential buy) / overbought (≥70, caution) / neutral, with an RSI track. Field `rsi_status`.
- **Fibonacci retracement ladder** — 52w high/low reconstructed from `week52_high_pct`/`week52_low_pct` + price; levels 0/23.6/38.2/50/61.8/78.6/100%, current retracement %, nearest level highlighted. Field `fib`.
- **Ratings** — signal, analyst_rating, recom_score, pi_score.
- **Non-tradeable assets** (e.g. `FID-CONTRA-F` Fidelity 401k pool, cash) carry `data_available:false` + an `analysis_note` explaining there is no public ticker / market data — instead of a wall of "—". 31/45 holdings enrich; the rest are commingled funds/cash with no public ticker.

### Public-ETF proxies for non-tradeable holdings (2026-06-03d)

The 12 Fidelity 401(k) commingled pools / institutional mutual funds (no public ticker) now map to a labeled public-ETF **proxy** so the holding drawer can show RSI zone + fib retracement for the asset class. Proxies are picked from the enrichment universe and always shown with a "(proxy)" banner + disclaimer. Backend: `_HOLDING_PROXY_MAP` in `api_v2.py`; row carries `proxy:{ticker,label}`. Dollar fib levels are omitted for proxies (different price scale) — retracement % + nearest level shown instead. Cash stays unproxied.

| Holding | Proxy | Asset class |
|---|---|---|
| FID-CONTRA-F, FCNTX, JPM-LGCG | SCHG | US large-cap growth |
| SP500-D | SPY | S&P 500 |
| VANG-FTSE-SOC | SPY | US large-cap blend (ESG) |
| TRP-LVAL, AMANX | SCHD | US large-cap value / dividend |
| SS-SMMD | IJH | US mid-cap blend |
| WM-BLAIR | IWP | US mid-cap growth |
| AB-DISC-Z | IWN | US small-cap value |
| FID-DIVINTL, SS-GACEQ | VXUS | international / global ex-US |

### v3 Portfolio holdings rows — at-a-glance signals (2026-06-03e)

Holdings table rows now carry decision signals without opening the drawer: **Symbol · Value · P/L% · RSI zone chip · Signal pill · %Port** (replaced Shares & Day-Change, which moved to the drawer). P/L% = `gain_loss/cost_basis` where basis exists (33/45 — all Schwab); **fidelity_401k funds (0/10) and cash show "—"** (no per-lot basis; purchase *date* does not exist in any source). RSI chip color-zoned (oversold=green/buy, overbought=amber/caution, neutral=gray), `*` = via public-ETF proxy. Signal pill colored (ADD green / TRIM-SELL red / WATCH-MONITOR amber / HOLD gray). Header shows technicals as-of timestamp. Drawer still holds the full fib ladder + ratings.

## v3 System → Pipeline Health (2026-06-03f)

New **Pipeline** tab (default) in System hub — one at-a-glance view of every pipeline stage's live numbers, closing the visibility gap that let stale jobs hide for weeks. Source: `/api/v2/system/pipeline-health` (new aggregation endpoint). Cards:
- **Ingestion** — news today/7d + freshness, active topics, transcripts total + freshness (caught a 14d stoppage), SEC Form 4 7d.
- **Curation** — iris pending/applied/expired, hermes promoted/staged, catalyst hits today.
- **LLM** — agent results today/7d, holdings w/ LLM health + freshness, daily intel sections + freshness.
- **RAG** — embeddings total, +7d, model, latest-embed freshness.
- **Agent jobs** — queued/processing/pending (self-healing reaper), completed/failed today.
Freshness colored green/amber/red vs each stage's SLA. Read-only.

## v3 Ops → Schwab Reauth (2026-08-11)

| Route | Hub | Purpose |
|---|---|---|
| `/v3/system/schwab-reauth` | Ops → **Schwab Reauth** | Manual Schwab OAuth renewal: request authorize URL, paste `127.0.0.1?code=…`, submit |

- **APIs:** `GET /api/v2/brokers/schwab/reauth-url`, `POST /api/v2/brokers/schwab/exchange-code`, enhanced `GET /api/v2/brokers/schwab/token-health` (`show_banner`, `true_expiry`, `days_to_true_expiry`).
- **Site banner:** `SchwabReauthBanner` in CC shell when reauth/proactive window is due → links to this page.
- **Related:** System hub `SchwabMonitor` CTA; order cards deep-link here when token is dead.
- **Runbook:** `docs/SCHWAB_AUTO_REAUTH.md` (browser auto-login off by default).

## v3 System hub — Apps + Jobs tabs (2026-06-03g, v2 parity)

Two v2 pages that had no v3 home are now System-hub tabs:
- **Apps** (`/api/v2/system/applications`) — software inventory + version drift. KPI strip (total/current/behind/unknown/not-installed), table with installed→latest + status, click for update command. Was v2 System Applications.
- **Jobs** (`/api/v2/system/scheduled-jobs`) — systemd timers + cron, grouped Hermes / Trade AI / Other with status dots. Was v2 Scheduled Jobs. ("unknown" status = systemctl not resolvable for that unit — a backend gap.)

## v3 Home — rich Command Center + Hermes (2026-06-03h)

v3 Home Snapshot tab enriched to v2 Command Center parity from `/api/v2/command` (one endpoint, all sections): Stops Triggered (action), Paper Trades (P&L/R), Weekly Movers, CIO Decisions, Recovery Watch, Portfolio News, Agent Health, AI Intelligence Briefing (portfolio risk + morning synthesis) — plus a **Hermes** card (`/api/v2/hermes/health`: staged research, validation findings, autonomous loop, gateway). v3-themed cards, click-to-drill.

## Scheduled-jobs timer status fix (2026-06-03h)

`/api/v2/system/scheduled-jobs` returned "unknown" for all hermes/tradeai timers — the portfolio_server is a SYSTEM service and `systemctl --user` couldn't reach the user bus. Fixed by injecting `XDG_RUNTIME_DIR=/run/user/<uid>` + returning is-active output on non-zero exit. Now resolves active/inactive/failed.

## v3 parity batch — 6 v2 pages added (2026-06-03i)

| v2 page | v3 home | Endpoint |
|---|---|---|
| Broker Recon | Trading → Broker Recon | /api/v2/broker-reconciliation |
| Plan vs Perf | Strategy → Plan vs Perf | /api/v2/plan-vs-performance |
| Forecast | Portfolio → Forecast | /api/v2/forecast |
| System Access | System → Access | /api/v2/system/access-links |
| Inbox | Agents → Inbox | /api/v2/inbox (NEW: escalations + CIO review + proposals) |
| Weekly Learning | Agents → Weekly Learning | /api/v2/weekly-learning (NEW: multi-tier reviews + agent perf) |

## v3 win-rate unify + read-only Admin audit (2026-06-03j)

- **Win-rate unified:** MetricStrip + Home tile now both show the journal win rate (overview.journal: 55.3% / 121 trades) instead of the strip using paper-readiness (45.8% / 24). Paper-readiness win rate remains in the Trading/readiness context. They no longer disagree.
- **System → Admin (READ-ONLY audit):** displays live-trading gate (4 gates), risk settings (heat vs 5% threshold, max-per-trade/strategy/sector, daily-loss kills), ATM global config, and per-account ATM-enabled state. ZERO write controls — no toggles/inputs/save. Prominent banner: setting CHANGES go through a separate guarded flow (Telegram for ATM enable/risk), never the dashboard. Level 7 prohibited preserved.
