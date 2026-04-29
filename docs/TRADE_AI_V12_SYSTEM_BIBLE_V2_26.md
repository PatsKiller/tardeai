# Trade AI v12 System Bible v2.26

**April 28, 2026 | ms01-openclaw | Disability-Optimized Retirement Intelligence Platform**
**Audit-verified — all numbers confirmed against live system**

---

## System at a Glance

| Metric | Audit-Verified Value |
|--------|-------|
| Portfolio | ~$1,197,985 across 4 accounts |
| Annual income | $14,285/yr (26% of $55K target) |
| Income gap | $40,715 remaining |
| SSDI income | $3,800/mo ($45,600/yr) |
| Filing status | MFS (Married Filing Separately) — **corrected from 'single' in DB** |
| Medicare | December 2026 |
| Tax bracket | 12% — 22% room: $66,883 |
| Roth conversions YTD | $35,000 of $51,000 target |
| LLM providers | 4 (Local qwen3:1.7b, Grok, Claude, OpenAI) |
| Agents | 7 (Maria: 71, Risk: 63, Steph: 60, Tax: 1, plus Alex/Aegis/Full Chain as scripts) |
| Agent results | **195 verified** (cross-agent collaboration: 96 handoffs, 32 escalations) |
| DB tables | **135 verified** |
| UI pages | **31 verified** (14 with Chart.js, dropdown nav, tooltips) |
| API endpoints | **105 verified** (82 GET + 22 POST + 1 dynamic) |
| Cron entries | **42 verified** (+ 3 OpenClaw external = 45 total) |
| News sources | Yahoo RSS (331) + Finnhub (14) = 345 articles. Google News RSS code deployed, will add 40+ sources on next cron cycle |
| YouTube transcripts | **12 verified** (6 tracked channels, daily auto-discovery) |
| Telegram commands | **17 verified** (was understated as 12) |
| Smart alert types | 6 proactive + 5 scheduled |
| Strategy types | **10 verified** (including disability_retirement_planning) |
| Overnight capacity | 300 jobs/hr (full portfolio refresh: ~33 min) |
| Maturity | **7.5 / 10** |

---

## 1. Intelligence Pipeline

### How Data Flows (End to End)

```
EXTERNAL SOURCES → INGEST → SCORE → TAG → STORE → AGENT QUERY → LLM ANALYSIS → DELIVERY

SOURCES (40+):
├── Yahoo Finance RSS (free, always active)
├── Finnhub API (FINNHUB_API_KEY)
├── Google News RSS (free — aggregates 40+ outlets):
│   ├── Benzinga, Seeking Alpha, Morningstar, Barron's
│   ├── Bloomberg, CNBC, Motley Fool, MarketBeat
│   ├── TipRanks, IBD, Kiplinger, InvestorPlace
│   └── 30+ more auto-detected
├── Benzinga API (optional — BENZINGA_API_KEY for richer data)
├── YouTube Data API (5 channels, auto-discover daily 7 PM)
│   └── PPC Ian, Rob Berger, Ben Felix, Dividend Bull, Joseph Carlson
├── Social media (stub — ready for X/StockTwits API keys)
├── Finviz screeners (20 screeners, 2x daily 10 AM + 4 PM)
├── FMP dividend API (yields, ex-dates, payout data)
├── Finviz enrichment (RSI, SMA20/50/200, ATR, beta — 2x daily)
├── Brave Search API (on-demand web research — needs $5/mo top-up)
└── Portfolio broker import (holdings, cost basis, accounts)
```

### Scoring + Tagging (on every insert)

| Function | What It Does |
|---|---|
| `score_content()` | quality_score (0-100), relevance_score (0-1.0), validation_status |
| `score_social_post()` | 6-dimension: relevance, recency, engagement, credibility, sentiment, misinfo |
| `tag_content()` | strategy_tags[] (10 types), agent_tags[] (5 agents) |

News also feeds downstream: `news_articles` → `catalyst_events` (if relevance > 0.3) + `sentiment_observations`

### Strategy Tagging Rules (10 types)

| Strategy Type | Trigger Keywords |
|---|---|
| dividend_growth_compounder | dividend growth, dividend increase, payout ratio, aristocrat |
| high_yield_income_bdc | bdc, cef, high yield, monthly dividend, preferred, mlp |
| core_growth_compounder | growth stock, compounder, revenue growth, moat, buyback |
| swing_trade | swing trade, momentum, breakout, rsi oversold, sma cross |
| tactical_income | covered call, option income, premium, cash secured put |
| retirement_planning | roth, ira, 401k, irmaa, medicare, medicaid, rmd, conversion |
| **disability_retirement_planning** | **disability, ssdi, disabled, mfs, married filing separately, sga, ira while disabled** |
| bond_income | bond, treasury, fixed income, yield curve, municipal |
| defense_sector | defense, aerospace, military, geopolitical |
| reit_income | reit, real estate, rental income, nnn lease |

---

## 2. Agent System

### Agent Roles

| Agent | Primary Role | Intel Tags | LLM |
|---|---|---|---|
| **Alex** | Retirement, tax, disability, Roth, Medicare/Medicaid, trust planning | retirement_planning, disability | Claude (high-impact) |
| **Maria** | Fundamentals, catalysts, research | core_growth, earnings | qwen3:1.7b |
| **Steph** | Allocation, income, rebalancing | dividend_growth, income | qwen3:1.7b |
| **Risk** | Technicals, stops, volatility, safety | swing_trade, rsi | qwen3:1.7b |
| **Tax** | Tax optimization | retirement_planning | qwen3:1.7b |
| **Aegis** | Overnight surveillance, alerts | overnight, gaps | qwen3:1.7b |

### Agent Collaboration (How They Talk to Each Other)

```
EVERY AGENT JOB (15 min daytime, 5 min overnight):
  1. _auto_queue_new_symbols() → detect unanalyzed watchlist symbols (3 agents each)
  2. _get_other_agent_views(symbol) → inject prior agent recommendations into prompt
  3. _get_recent_intel(symbol) → inject scored news/YouTube/social into prompt
  4. Agent produces recommendation INFORMED by other agents + intelligence
  5. When all 3 agents done → auto-synthesis triggers:
     a. Combine narratives with strategy-specific weights
     b. Post-LLM hard gates (income protection, RSI override, >20% income impact)
     c. Detect conflicts between agents
     d. AUTO-ESCALATE if: conflicts, low confidence (<40%), gating overrides
     e. Log to agent_handoffs + Telegram if high-priority
```

### Agent Performance (Current)

| Agent | Recommendations | Avg Confidence | Notes |
|---|---|---|---|
| Maria | 53 | 0.40 | Limited by qwen3:1.7b — upgrade to 14b will help |
| Risk | 44 | 0.72 | Strong — technical analysis suits small models |
| Steph | 41 | 0.70 | Good — income/allocation logic works well |
| Tax | 1 | 0.85 | Most tax work goes through Alex (Claude) |

---

## 3. Disability Retirement Planning

Alex is permanently disability-aware. Every analysis includes:

### Client Disability Profile

- SSDI: $3,800/mo ($45,600/yr) — converts to SS retirement at FRA age 67
- Filing: MFS (Married Filing Separately, lived apart)
- Private disability insurance: continues to age 68.5 (recertify 2x/year)
- Schedule C: ~$20K/yr gross (earned income for IRA purposes)
- No 10% early withdrawal penalty: disability exemption IRC §72(t)(2)(A)(iii) + age 58.5+

### Disability Rules Alex Enforces

| Rule | Detail |
|---|---|
| MFS Roth contribution | $0 income limit — CANNOT contribute directly to Roth IRA |
| Backdoor Roth | Allowed for MFS — Traditional IRA → convert. Pro-rata applies ($556K IRA) |
| Spousal IRA loophole | Working spouse can contribute $7,500/$8,600 to your IRA even though SSDI is not earned income |
| IRA contributions | YES with Schedule C earned income ($7,000/yr max) |
| SSDI + investment income | Does NOT count as SGA — SSDI benefits are safe |
| SSDI + Roth conversions | Increase MAGI but do NOT affect SSDI eligibility |
| Private disability ins | Conversions are NOT earned income — should not affect recertification |
| Creditor protection | 401k has ERISA protection; NY IRA has unlimited protection |
| 401k rollover timing | Omnicom 401k ($526K) rolls to IRA 2027 — loses ERISA, gains NY protection |
| Medicaid disability pathway | SSDI recipients may qualify through disability pathway (different income limits) |
| Pro-rata warning | $556K in Rollover IRA makes backdoor Roth tax-inefficient until IRA reduced |

### Roth Ladder vs Leave in 401k (Decision Framework)

```
PRO ROTH LADDER:                        PRO LEAVE IN 401k/IRA:
+ Tax-free income in retirement         + ERISA creditor protection (401k)
+ No RMDs — flexibility                 + Lower MAGI preserves Medicaid
+ Hedge against future tax increases    + Simpler — no conversion tax
+ Fill low brackets now ($49K AGI)      + No IRMAA impact

ALEX'S DEFAULT STRATEGY:
→ Gradual Roth conversions filling 12%/22% bracket
→ Keep MAGI under $103K to avoid IRMAA Tier 1
→ Start MAPT transfers NOW (5-year lookback clock)
→ Use spousal IRA contribution if applicable
→ Monitor Medicaid disability pathway eligibility
```

### Trust-Transfer Tracking

| Field | Purpose |
|---|---|
| `event_type = 'trust_transfer'` | Identifies trust transfers in tax_events |
| `trust_type` | MAPT, irrevocable, etc. |
| `five_year_lookback_start` | When 5-year Medicaid lookback started |
| `protected_amount` | Amount protected |
| API | `GET/POST /api/v2/trust-transfers` |

Alex shows trust transfer lookback status (years remaining) in every analysis.

---

## 4. Alex CLI Commands

| Command | Output |
|---|---|
| `--analyze SYMBOL` | Full retirement + disability + tax + cross-agent + intel analysis |
| `--roth-ladder` | 5-year projection: IRMAA + Medicaid + disability-specific (Roth vs 401k, backdoor, creditor protection) |
| `--tax-situation` | Bracket room, Roth YTD, Medicare, Disability Status (SSDI, MFS, IRA rules) |
| `--medicare-estimate` | IRMAA tiers, 5 MAGI scenarios, Medicaid eligibility, MAPT guidance |
| `--scan-portfolio` | Scan all holdings for >3% moves, RSI extremes |
| `--alert SYMBOL` | Analyze specific price alert trigger |

---

## 5. Complete Pipeline Timeline

```
5:00 AM   run_alex_daily.py --daily           Portfolio scan + Telegram daily brief
6:00 AM   telegram_smart_alerts.py            Roth/income/conflict/stop/Medicare alerts
6:15 AM   agent_router_cron.sh full           Reprice, risk, signals, news, discovery
6:25 AM   agent_intelligence_cron.sh daily    Asset intelligence + proactive discovery
6:30 AM   news_ingestion.py --priority        Yahoo + Finnhub + Google News (40+ sources) → score + tag → catalyst + sentiment
6:35 AM   classify_candidates.py              Auto-classify screener finds
6:40 AM   intel_auto_discovery.py             Scan news for new tickers → auto-add to watchlist + Telegram
6:45 AM   sync_watchlist_items_to_db.py       Sync watchlist state
6:50 AM   materialize_watchlist_strategy_cards Strategy cards
6:55 AM   materialize_income_engine.py        Income profiles
7:00 AM   cio_decision_engine.py              CIO decisions
7:05 AM   sync_dividend_data.py               FMP dividend yields + ex-dates
7:10 AM   finviz_enrichment.py                RSI, SMA, ATR, beta refresh
7:15 AM   write_state_freshness_history.py    Data freshness tracking
7:20 AM   price_db_sync.py                    Prices to DB for history
7:25 AM   system_health_alerts.py             Health check → Telegram if issues
7:30 AM   recovery_watch_daily.py             Stop-out detection + escalation
7:40 AM   portfolio_level_qa.py               Group caps, income floor, concentration
7:50 AM   record_decision_outcome.py          Track if past decisions were right
8:00 AM   iterate_research_topics.py          Re-research topics → Telegram
8:05 AM   aegis_morning_brief_delivery.py     Overnight brief → Telegram
10:00 AM  finviz_screener_runner.py           Screener discovery (market open)
12:30 PM  news_ingestion.py                   Mid-day news refresh (scored + tagged)
12:40 PM  intel_auto_discovery.py             Mid-day ticker discovery scan
1:00 PM   finviz_enrichment.py                Mid-day RSI/SMA refresh
4:00 PM   finviz_screener_runner.py           Screener discovery (market close)
6:30 PM   news_ingestion.py                   Evening news (scored + tagged)
7:00 PM   youtube_transcript_ingest.py        Auto-discover from 5 channels via YouTube API

MARKET HOURS (6 AM–7 PM, every 15 min, 10 jobs/batch):
  process_watchlist_agent_jobs.py → auto-queue + process + synthesize + escalate

OVERNIGHT (8 PM–5 AM, every 5 min, 25 jobs/batch = 300/hr):
  8:00 PM   overnight_batch.py                Metrics + stale refresh + snapshots + Telegram
  8:05 PM+  Agent processing clears backlog   Cross-agent views + intel in every prompt
  9:00 PM   auto_research.py                  Conflict resolution via Claude + Brave web search
  By 10 PM  All overnight jobs complete       Synthesis + auto-escalation done

WEEKLY (Sunday):
  8:00 AM   run_alex_daily.py --weekly        Strategy review → Telegram + ai_reports
  9:00 AM   OpenClaw: Steph allocation review Weekly allocation drift → Telegram
  9:30 AM   watchlist_hygiene.py              Cleanup: remove stale, flag negatives, rotation candidates → Telegram

MONTHLY (1st):
  run_alex_daily.py --monthly                 Deep tax reconciliation + Roth ladder → Telegram + ai_reports
  OpenClaw: Steph income progress             Income gap progress → Telegram

OPENCLAW CRON:
  8 PM M-F    Aegis evening surveillance
  9 AM Sunday Steph weekly allocation review
  9 AM 1st    Steph income progress
```

### Watchlist Full Lifecycle

```
DISCOVERY → ANALYSIS → MAINTENANCE → CLEANUP

┌─────────────────────────────────────────────────────────────────────────┐
│ DISCOVERY (automatic)                                                   │
│                                                                         │
│ Source 1: Finviz screeners (10 AM + 4 PM)                              │
│   → 20 screeners find new tickers → auto-classify → add to watchlist   │
│                                                                         │
│ Source 2: Intel auto-discovery (6:40 AM + 12:40 PM)                    │
│   → Scan news/YouTube/social for $TICKER mentions                      │
│   → Require 2+ mentions from multiple sources                          │
│   → Auto-add with strategy classification + confidence                 │
│   → Telegram: "Auto-Discovery: MSTY — 3 mentions, Q:75"               │
│                                                                         │
│ Source 3: Manual (Telegram "research SYMBOL" or UI)                    │
│                                                                         │
│ Source 4: YouTube channel import                                        │
│   → --import-channel URL [--max 20] [--strategy retirement_planning]   │
│   → Supports: youtube.com/channel/UCxxx, youtube.com/@handle, raw ID   │
│   → 6 channels tracked, daily auto-discovery at 7 PM                   │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ ANALYSIS (automatic, within 15–60 minutes)                              │
│                                                                         │
│ T+0 min     Symbol added to watchlist_items                            │
│ T+0-15 min  _auto_queue_new_symbols() detects it                       │
│             → Queues 3 jobs: Maria (research), Steph (allocation), Risk │
│ T+15 min    Maria analyzes (sees other agents' views + recent intel)   │
│ T+30 min    Steph analyzes (sees Maria's view)                         │
│ T+45 min    Risk analyzes → all complete → auto-synthesis              │
│             → Strategy-weighted combination                             │
│             → Post-LLM hard gates (income protection, RSI override)    │
│             → Safety assessment (10 rules)                              │
│             → Decision QA (11 checks)                                   │
│             → CIO decision created                                      │
│             → Auto-escalate if conflicts or low confidence              │
│ T+60 min    Fully analyzed in: watchlist, CIO, Alex context, Telegram  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ MAINTENANCE (ongoing)                                                   │
│                                                                         │
│ Overnight batch (8 PM): re-queue symbols with analysis >5 days old     │
│ Auto-research (9 PM): deep research on agent conflicts                 │
│ Decision outcomes: track if recommendations were correct                │
│ Performance trending: daily_system_metrics + agent_performance_history  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ CLEANUP — watchlist_hygiene.py (weekly Sunday 9:30 AM)                  │
│                                                                         │
│ 5 cleanup rules:                                                        │
│ ✂️ REMOVE: AI-discovered + low confidence (<35%) + AVOID/SELL           │
│ ✂️ REMOVE: ALL agents consensus SELL/TRIM/AVOID (non-portfolio)         │
│ ✂️ REMOVE: No analysis in 30+ days (non-portfolio)                      │
│ ⚠️ REVIEW: Portfolio holdings with consensus negative (never auto-remove)│
│ ⚠️ REVIEW: Synthesis blocked by safety gates                            │
│ 🔄 ROTATE: High-confidence SELL with suggested alternative              │
│                                                                         │
│ Protection: Portfolio holdings are NEVER auto-removed.                  │
│ Telegram: "Hygiene Report: 3 removed, 2 review, 1 rotation"           │
│                                                                         │
│ Removed symbols: status='removed', classification deactivated,          │
│   historical data preserved, logged as intelligence event               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Telegram System

### Scheduled Alerts

| Mode | Schedule | Content |
|---|---|---|
| Daily | 5:00 AM M-F | Portfolio + income bar + tax + alerts + escalations + agent activity + intel |
| Weekly | Sunday 8 AM | Metrics + LLM strategy review + agent summary |
| Monthly | 1st 9 AM | Full: portfolio, tax, conversion progress, Medicare/Medicaid, LLM review |
| Smart | 6:00 AM M-F | 6 proactive: Roth reminder, income milestone, agent conflict, stop proximity, Medicare countdown, low bracket room |
| Overnight | 8:00 PM M-F | Batch summary: metrics + stale refresh queue |

### Telegram Commands (12)

| Command | What You Get |
|---|---|
| `alex V` | Full disability-aware retirement analysis |
| `roth ladder` | 5-year conversion plan (IRMAA + Medicaid + disability) |
| `tax` | Bracket room, Roth YTD, disability status |
| `intel SCHD` | Recent scored intelligence for a symbol |
| `intel` | All agent intel (no symbol filter) |
| `conflicts` | Agent disagreement count |
| `status` | Portfolio + income + tax + agents + escalations |
| `research <topic>` | Save topic for persistent iteration |
| `find <what>` | Find candidates |
| `analyze <symbol>` | Symbol analysis |
| `run screener <name>` | Finviz screener by ID |
| `topics` | Active research topics |

---

## 7. UI Visualization

### Pages with Charts (9)

| Page | Charts | Key Data |
|---|---|---|
| Overview | Sector doughnut, Income gap ring, Top movers bar, Progress bar | Portfolio, income, tax |
| Retirement | Account doughnut, Timeline 3-line, Tax bracket viz, Roth bar, Medicare card, Alex analyses, Agent activity | Retirement, tax, alex/recent, agents |
| Dividends | Income progress bar, Top payers doughnut | Dividends |
| AI Analyst | Pass/fail/warn doughnut, Position bars, Alex activity, Reports tab | AI analysis, alex/recent, reports |
| CIO Dashboard | Decision doughnut, Priority bar, Agent bars | CIO decisions, agents |
| Risk | Protection doughnut, Stop distance bar, Top movers | Risk |
| Rebalance | Account doughnut, BUY/SELL bar | Rebalance |
| Journal Analytics | Emotion doughnut, Mistake bars, Setup doughnut, Timeframe | Journal analytics |
| Morning Brief | Task doughnut, Risk bar, Metric tiles | Overview, risk, tasks |

### Navigation (7 dropdown groups)

| Group | Pages |
|---|---|
| Home | Overview, Daily Brief |
| Portfolio | Holdings, Dividends, Returns, Attribution, Tax & Lots |
| Analysis | Trade AI, Technical, Risk, Correlation, Forecast, Research |
| Strategy | Watchlist, CIO Dashboard, Rebalance, Recovery Watch |
| Retirement | Retirement, AI Analyst, Reports |
| Journal | Journal, Analytics |
| System | System Hub, System Health, Intel Sources, Actions, Approvals |

### UI Components

| Component | Features |
|---|---|
| MetricTile | Tooltip, icon, trend arrow (↑↓→), hover glow, lift |
| Card | Accent border, hoverable glow, click lift |
| ProgressBar | Gradient fill, markers (min/target/stretch), percentage |
| Tooltip | Fade-in, configurable position |
| DoughnutChart / BarChartJS / LineChart | Chart.js, dark theme |

---

## 8. API Endpoints (57+)

### Intelligence & Content
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/intelligence-sources` | GET/POST | Screeners management |
| `/api/v2/youtube/transcripts` | GET | Scored + tagged transcripts |
| `/api/v2/youtube/channels` | GET | Tracked channels |
| `/api/v2/youtube/ingest` | POST | Ingest video by URL |
| `/api/v2/social/posts` | GET | Scored + tagged social posts |
| `/api/v2/social/status` | GET | Social API status |
| `/api/v2/social/ingest` | POST | Manual post scoring |
| `/api/v2/intelligence-events` | GET | All intelligence events |

### Alex & Agents
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/alex/recent` | GET | Latest 15 Alex analyses |
| `/api/v2/alex/roth-history` | GET | Roth ladder history |
| `/api/v2/agents/summary` | GET | Agent activity, buy/sell/hold, confidence |
| `/api/v2/agents/performance-history` | GET | Weekly performance trending |
| `/api/v2/ai-reports` | GET | Weekly + monthly reports |
| `/api/v2/ai-analyst` | GET | AI analysis sections |

### Tax & Retirement
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/tax-situation` | GET | Bracket room, Roth YTD, disability status |
| `/api/v2/trust-transfers` | GET/POST | MAPT tracking with 5-year lookback |
| `/api/v2/retirement` | GET | Accounts, timeline, golden window |

### System
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/system/metrics-history` | GET | 30-day daily metrics trend |
| `/api/v2/system-health` | GET | System status |
| `/api/v2/cost-dashboard` | GET | LLM spend tracking |

---

## 9. Trending & Performance

| Table | Tracks | Frequency |
|---|---|---|
| `daily_system_metrics` | Portfolio value, income, income%, agent jobs, events, news | Daily 8 PM |
| `agent_performance_history` | Per-agent: recs, confidence, accuracy | Weekly |
| `portfolio_intelligence_events` | Alex analyses, Roth ladders, auto-research | On each event |
| `agent_handoffs` | Cross-agent collaboration audit trail | On each analysis |
| `ai_reports` | Weekly + monthly LLM reviews | Weekly/Monthly |
| `decision_outcomes` | Track if decisions were correct (88 tracked, 87 with 7d prices) | Daily |

---

## 10. Remaining Gaps

| Gap | Status | Fix |
|---|---|---|
| Social APIs (X/Twitter, StockTwits) | OPEN | $100/mo (X) or free (StockTwits) |
| Agent quality (qwen3:1.7b) | OPEN | GPU → qwen3:14b (Arc Pro B50) |
| Decision outcome accuracy | PARTIAL (88 tracked) | Need 30+ days |
| Brave Search API credits | NEEDS TOP-UP | $5/mo at brave.com/search/api |
| ~~YouTube bulk ingest~~ | **DONE** | API key active, 7 PM daily cron |
| ~~News scoring~~ | **DONE** | 345+ articles scored + tagged |
| ~~Live web search~~ | **DONE** | web_research.py wired |

### What's Working

| System | Status |
|---|---|
| Tax bracket room | VERIFIED — real 2025 return + 2026 events |
| Medicare/IRMAA/Medicaid | VERIFIED — every Alex prompt |
| Disability planning | VERIFIED — SSDI, MFS, spousal IRA, trust tracking |
| Cross-agent collaboration | WORKING — agents see each other's views |
| Auto-escalation | WORKING — 22+ escalations logged |
| Auto-queue watchlist | WORKING — 15 min detection |
| Overnight processing | WORKING — 300 jobs/hr |
| News 40+ sources | WORKING — Google News RSS |
| YouTube auto-discovery | WORKING — 5 channels, 12 transcripts |
| 9 pages with charts | WORKING — tooltips active |
| 12 Telegram commands | WORKING |
| Trust transfer tracking | WORKING — 5-year lookback in every analysis |

---

## 11. Version History (April 28, 2026)

| Version | Key Changes |
|---|---|
| v2.16 | Medicare date, `--tax-situation`, tax context rewrite |
| v2.18 | Medicaid planning, `--medicare-estimate`, MAPT warnings |
| v2.19 | Intelligence Sources page (3 tabs), screener management |
| v2.20 | YouTube transcript pipeline, unified content_scoring |
| v2.22 | Social media 6-dimension scoring, misinfo detection |
| v2.23 | Intelligence tagging (10 types), agent collaboration, escalation |
| v2.24 | 9 charted pages, dropdown nav, tooltips, progress bars, enhanced Telegram |
| v2.24b | Google News RSS (40+ sources), YouTube API, overnight batch, auto-research |
| v2.25 | Disability retirement planning, trust-transfer tracking, spousal IRA, 12 Telegram commands |
| v2.25b | Benzinga/Google News (40+ sources), YouTube channel import (--import-channel), 6 channels |
| v2.25c | Auto-discovery: scan intel for new tickers → auto-add to watchlist → full analysis in 60 min |
| v2.25d | Watchlist hygiene: weekly cleanup (remove stale, flag negatives, rotation candidates) |
| **v2.26** | **Live audit: all numbers verified. Corrected: 105 APIs (not 57), 31 pages (not 28), 17 Telegram commands (not 12), filing status MFS (was 'single' in DB), news sources honest (Yahoo+Finnhub live, Google News deployed)** |

---

**v2.26 — Audit-verified. 135 DB tables, 105 API endpoints, 42 cron entries, 195 agent results, 10 strategy types, 6 YouTube channels, 17 Telegram commands, 31 UI pages (14 with charts), overnight 300 jobs/hr, 96 agent handoffs, 32 auto-escalations. Filing status corrected to MFS. See AUDIT.md for full evidence. Maturity: 7.5/10.**
