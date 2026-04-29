# Trade AI v12 System Bible v2.24

**April 28, 2026 | ms01-openclaw | v2.24 — Full Pipeline Integration + Visualization + Smart Alerts**

---

## Changes Since v2.15

### v2.16 — Medicare/Medicaid + Tax Context Rewrite
| Change | Status |
|--------|--------|
| Medicare eligibility date (Dec 2026) in personal_situation DB | **DONE** |
| `--tax-situation` CLI flag | **DONE** — inline DB query, shows bracket room + Medicare |
| `_format_tax_context()` rewritten | **DONE** — includes Medicare date, IRMAA lookback note |
| Fix: `get_tax_context` scope issue in `__main__` | **DONE** — inline psycopg2 query |

### v2.18 — Medicaid Planning + Medicare Estimate
| Change | Status |
|--------|--------|
| Medicaid/trust awareness in every Alex analysis | **DONE** — MAPT 5-year lookback, NY income limits, asset countability |
| Medicaid warnings in Roth ladder prompt | **DONE** — MAGI vs Medicaid limits per year, tradeoff analysis |
| `--medicare-estimate` CLI flag | **DONE** — IRMAA tiers, 5 MAGI scenarios, Medicaid eligibility |
| NY Medicaid income limit ($20,124/yr) in all conversions | **DONE** |

### v2.19 — Intelligence Sources & Screeners Page
| Change | Status |
|--------|--------|
| `/v2/intelligence-sources` page | **DONE** — 3-tab UI (Screeners, YouTube, Social) |
| `finviz_screeners` extended with keywords, sources, added_by | **DONE** — 20 screeners |
| `GET/POST /api/v2/intelligence-sources` | **DONE** — upsert + soft delete |
| Nav link in Shell sidebar | **DONE** |

### v2.20 — YouTube Transcript Pipeline
| Change | Status |
|--------|--------|
| `youtube_transcript_ingest.py` | **DONE** — fetch, score, store transcripts |
| `youtube_transcripts` table | **DONE** — video_id, quality_score, relevance_score, validation_status |
| `youtube_channels` table | **DONE** — 5 seeded channels (Joseph Carlson, Dividend Bull, etc.) |
| `content_scoring.py` — unified scoring engine | **DONE** — quality, relevance, validation for all content |
| `GET /api/v2/youtube/transcripts` + `/channels` | **DONE** |
| `POST /api/v2/youtube/ingest` | **DONE** — ingest any YouTube URL from UI |
| YouTube tab in Intel Sources page | **DONE** — ingest form, channel list, scored table |

### v2.22 — Social Media Scoring
| Change | Status |
|--------|--------|
| `social_posts` table | **DONE** — 24 columns, engagement metrics, scoring |
| `score_social_post()` in content_scoring.py | **DONE** — 6-dimension scoring (relevance, recency, engagement, credibility, sentiment, misinfo) |
| `social_monitor.py` rewritten | **DONE** — scoring pipeline, stub ingestion for X/Reddit/StockTwits |
| `GET /api/v2/social/posts` + `/status` | **DONE** |
| `POST /api/v2/social/ingest` | **DONE** — manual post scoring |
| Social tab in Intel Sources page | **DONE** — API status, paste-and-score form, posts table |
| Misinfo detection (6 signals) | **DONE** — "guaranteed returns", "to the moon", etc. penalized |

### v2.23 — Intelligence Tagging + Agent Collaboration
| Change | Status |
|--------|--------|
| `tag_content()` in content_scoring.py | **DONE** — 9 strategy types, 5 agent mappings |
| `strategy_tags` + `agent_tags` columns on all content tables | **DONE** |
| All ingest scripts call `tag_content()` on store | **DONE** — news, YouTube, social |
| `intel_query.py` — agent intelligence query layer | **DONE** — get_intel_for_agent, get_intel_for_symbol, get_intel_summary |
| `agent_collab.py` — cross-agent collaboration | **DONE** — get_agent_context, log_handoff, check_escalation |
| Alex pulls cross-agent context (Maria/Steph/Risk) | **DONE** — injected into every analysis prompt |
| Escalation detection (conflicts, low confidence, missing agents) | **DONE** — flags logged to agent_handoffs |
| Handoff audit trail | **DONE** — all agent-to-agent pulls logged with timestamp |

---

## Current Architecture

### Unified Intelligence Pipeline

```
INGEST → SCORE → TAG → STORE → QUERY → INJECT INTO AGENT PROMPTS

Sources:              Scoring:                   Tagging:
├── Yahoo RSS         quality_score (0-100)      strategy_tags: [dividend_growth, retirement_planning, ...]
├── Finnhub           relevance_score (0-1.0)    agent_tags: [Alex, Maria, Steph, Risk, Aegis]
├── YouTube           validation_status
├── Social (stub)     matched_keywords
└── Finviz screeners  sentiment, misinfo_flags
```

### Agent Collaboration Flow

```
Alex --analyze V:
  1. Build position context (holdings, P&L, enrichment)
  2. Format tax context (bracket, Medicare, Medicaid)
  3. Pull scored intelligence tagged to Alex + symbol V
  4. Pull cross-agent context (Steph: ADD conf:0.85, Risk: RESEARCH_MORE conf:0.65)
  5. Check escalation (conflicts? low confidence? missing agents?)
  6. Send to LLM with all context
  7. Log handoffs to agent_handoffs table
```

### Strategy Tagging Rules (9 types)

| Strategy Type | Trigger Keywords |
|---|---|
| dividend_growth_compounder | dividend growth, dividend increase, payout ratio, aristocrat |
| high_yield_income_bdc | bdc, cef, high yield, monthly dividend, preferred, mlp |
| core_growth_compounder | growth stock, compounder, revenue growth, moat, buyback |
| swing_trade | swing trade, momentum, breakout, rsi oversold, sma cross |
| tactical_income | covered call, option income, premium, cash secured put |
| retirement_planning | roth, ira, 401k, irmaa, medicare, medicaid, rmd, conversion |
| bond_income | bond, treasury, fixed income, yield curve, municipal |
| defense_sector | defense, aerospace, military, geopolitical |
| reit_income | reit, real estate, rental income, nnn lease |

### Agent Responsibility Map

| Agent | Primary Role | Gets Intel Tagged With | Provides |
|---|---|---|---|
| Alex | Retirement, tax, Roth, Medicare/Medicaid | retirement_planning | Full retirement analysis |
| Maria | Fundamentals, catalysts, research | core_growth, earnings, upgrades | Research narratives |
| Steph | Allocation, income, rebalancing | dividend_growth, income, yield | Position sizing, account fit |
| Risk | Technicals, stops, volatility, safety | swing_trade, rsi, volatility | Hold/trim/stop signals |
| Aegis | Overnight surveillance, alerts | overnight, gaps, earnings surprise | Morning briefs |

---

## System Summary

| Metric | Value |
|--------|-------|
| Portfolio | ~$1,197,985 |
| Actionable recs | 22 |
| LLM providers | 4 (Local qwen3:1.7b, Grok, Claude, OpenAI) |
| Agents | 7 (Maria, Steph, Risk, Tax, Full Chain, Alex, Aegis) |
| DB tables | 125+ |
| UI pages | 28 |
| API endpoints | 40+ |
| Cron jobs | 21 |
| Intelligence sources | 20 screeners + 5 YouTube channels + social (stub) |
| Agent results stored | 129 (49 Maria, 41 Risk, 38 Steph, 1 Tax) |
| Maturity | **7.0 / 10** |

---

## Alex CLI Commands

| Command | What It Does |
|---|---|
| `--analyze SYMBOL` | Full retirement analysis with tax, cross-agent context, intel |
| `--roth-ladder` | 5-year conversion projection with IRMAA + Medicaid tradeoffs |
| `--tax-situation` | Current bracket room, Medicare date, conversion capacity |
| `--medicare-estimate` | IRMAA tiers, MAGI scenarios, Medicaid eligibility check |
| `--scan-portfolio` | Scan all holdings for significant moves (>3%, RSI extremes) |
| `--alert SYMBOL` | Analyze a specific price alert trigger |

---

## API Endpoints (New Since v2.15)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/intelligence-sources` | GET/POST | Screeners with keywords, sources, added_by |
| `/api/v2/intelligence-sources/delete` | POST | Soft-delete a screener |
| `/api/v2/youtube/transcripts` | GET | Scored + tagged transcripts |
| `/api/v2/youtube/channels` | GET | Tracked YouTube channels |
| `/api/v2/youtube/ingest` | POST | Ingest a video by URL |
| `/api/v2/youtube/channels/add` | POST | Add a tracked channel |
| `/api/v2/social/posts` | GET | Scored + tagged social posts |
| `/api/v2/social/status` | GET | Which social APIs are configured |
| `/api/v2/social/ingest` | POST | Score and store a manual post |

---

## What Should John Trust?

| Category | Trust Level |
|---|---|
| Tax bracket room ($66,883) | **Yes** — computed from real 2025 return + 2026 events |
| Medicare/IRMAA estimates | **Yes** — thresholds are 2026 actuals |
| Medicaid warnings | **Directional** — NY income limits real, verify with elder law attorney |
| "Alex says convert $X at 22%" | **Directional** — math is correct, verify timing with CPA |
| Cross-agent context (Steph/Risk views) | **With caution** — 1.7B model quality |
| Unified scoring (quality/relevance) | **Yes** — keyword-based, deterministic, no hallucination |
| Strategy/agent tagging | **Yes** — rule-based, auditable |
| Portfolio value, income gap | **Yes** — real broker data |
| Daily scan alerts | **Yes** — real market data triggers |
| YouTube/social scored intel | **Useful but thin** — limited data so far |
| Social API ingestion | **Not active** — no API keys configured |
| Decision outcomes | **Ignore** — still mostly synthetic |

---

## Complete Data Pipeline Timeline (Weekday)

```
TIME        SCRIPT                              WHAT IT DOES                                    DATA IT PRODUCES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5:00 AM     run_alex_daily.py --daily           Portfolio scan + alerts                         Telegram alert, intelligence_events
6:00 AM     telegram_smart_alerts.py            Roth/income/conflict/stop/Medicare checks       Proactive Telegram alerts
6:15 AM     agent_router_cron.sh full           Reprice, risk, signals, news, discovery         holdings.json, risk.json, signals.json
6:25 AM     agent_intelligence_cron.sh daily    Asset intelligence + proactive discovery        ai_watchlist.json, candidates
6:30 AM     news_ingestion.py --priority        Yahoo + Finnhub + Google News (40+ sources) → SCORE + TAG    news_articles + catalyst_events + sentiment_observations
6:35 AM     classify_candidates.py              Auto-classify new screener finds                ticker_strategy_classifications
6:45 AM     sync_watchlist_items_to_db.py       Sync watchlist state to DB                      watchlist_items
6:50 AM     materialize_watchlist_strategy_cards Strategy cards for all symbols                  watchlist_strategy_cards
6:55 AM     materialize_income_engine.py        Income profiles per symbol                      income_asset_profiles
7:00 AM     cio_decision_engine.py              CIO-level decisions                             cio_decisions
7:00 AM     sync_dividend_data.py               FMP dividend yields + ex-dates                  ticker_dividend_data
7:00 AM     finviz_enrichment.py                RSI, SMA20/50/200, ATR, beta                   ticker_enrichment_cache.json
7:10 AM     write_state_freshness_history.py    Track data freshness                            state_freshness_history
7:20 AM     system_health_alerts.py             System health check                             Telegram if issues
8:00 AM     iterate_research_topics.py          Re-research active topics via LLM               research findings → Telegram
8:00 AM     (Sunday) run_alex_daily.py --weekly Weekly strategy review                          Telegram + ai_reports table
10:00 AM    finviz_screener_runner.py           Run 20 screeners, discover new tickers          ticker_strategy_classifications, watchlist_items
12:30 PM    news_ingestion.py --priority        Mid-day news refresh → SCORE + TAG              news_articles (scored + tagged)
1:00 PM     finviz_enrichment.py                Mid-day RSI/SMA refresh                        ticker_enrichment_cache.json
3:00 PM     (hourly) agent_router_cron.sh light Reprice positions                               holdings.json
4:00 PM     finviz_screener_runner.py           End-of-day screener run                         new candidates
6:30 PM     news_ingestion.py --priority        Evening news → SCORE + TAG                      news_articles (scored + tagged)

EVERY 15 MINUTES:
  process_watchlist_agent_jobs.py:
    1. Auto-queue new watchlist symbols (Maria + Steph + Risk)
    2. Process queued agent jobs → watchlist_agent_results
    3. Check synthesis readiness → run synthesis + safety gates
    4. Log cross-agent handoffs → agent_handoffs

OVERNIGHT (8 PM — after market close):
  overnight_batch.py:
    1. Record daily_system_metrics (portfolio value, income, income%, jobs, events, news)
    2. Find symbols not analyzed in 7+ days → queue 3 agent jobs each (Maria/Steph/Risk)
    3. Record agent_performance_history (weekly: recs, confidence, accuracy per agent)
    4. Send Telegram summary of overnight queue
    → Queued jobs process via 15-min cron over next 1-2 hours

MONTHLY (1st @ 9 AM):
  run_alex_daily.py --monthly    Deep tax reconciliation + Roth ladder     Telegram + ai_reports table
```

### Trending & Performance Tracking

| Table | What It Tracks | Frequency | API |
|---|---|---|---|
| `daily_system_metrics` | Portfolio value, income, income %, agent jobs, events, news count | Daily (8 PM) | `/api/v2/system/metrics-history` |
| `agent_performance_history` | Per-agent: total recs, avg confidence, accuracy | Weekly (Sunday) | `/api/v2/agents/performance-history` |
| `portfolio_intelligence_events` | Every Alex analysis, Roth ladder, CIO decision | On each event | `/api/v2/intelligence-events` |
| `agent_handoffs` | Cross-agent collaboration audit trail | On each analysis | `/api/v2/agents/summary` |
| `ai_reports` | Weekly + monthly LLM-generated reviews | Weekly/Monthly | `/api/v2/ai-reports` |
| `watchlist_synthesis_safety_history` | Safety gate results per synthesis | On each synthesis | — |
| `state_freshness_history` | Data staleness tracking | Daily (7:15 AM) | — |

### Agent Usage Pattern (Observed)

```
TIME OF DAY         AGENT JOBS PROCESSED
8 PM ████████████████████ (16)    ← Overnight batch queues start
9 PM ████████ (7)
10 PM █████████████████████████████████████████████████████ (53)  ← Peak processing
11 PM ███████████████████████████████████████████ (43)             ← Second peak
7 AM  █ (1)                        ← Morning stragglers
```

**Agents do 95% of their work between 8 PM and midnight** — this is correct.
The 15-min cron picks up overnight-queued jobs and processes 10 per cycle (4 cycles/hour = 40 jobs/hour).

### Agent Performance Snapshot

| Agent | Recommendations | Avg Confidence | Notes |
|---|---|---|---|
| Maria (Research) | 53 | 0.40 | Limited by qwen3:1.7b — upgrade to 14b will help |
| Risk (Technical) | 44 | 0.72 | Strong — technical analysis is well-suited to small models |
| Steph (Allocation) | 41 | 0.70 | Good — income/allocation logic works well |
| Tax (Tax) | 1 | 0.85 | Barely used — most tax work goes through Alex (Claude) |

### Watchlist → Full Analysis Timeline

When a new symbol is added to watchlist:

```
T+0 min     Symbol added to watchlist_items (via UI, Telegram, or screener)
T+0-15 min  process_watchlist_agent_jobs detects unanalyzed symbol
            → Auto-queues 3 jobs: Maria (research), Steph (allocation), Risk (technical)
T+15 min    Maria job processed → full narrative + recommendation stored
T+30 min    Steph job processed → allocation/income fit analysis stored
T+45 min    Risk job processed → technical/stop analysis stored
T+45 min    All 3 complete → synthesis triggered automatically
            → Strategy-weighted synthesis (income: 35% allocation, 10% technicals)
            → Post-LLM hard gates (income protection, RSI override)
            → Safety assessment (10 rules)
            → Decision QA (11 checks)
            → CIO decision created
T+60 min    Full analysis available in:
            → /v2/watchlist (strategy card)
            → /v2/cio (decision)
            → Alex context (cross-agent collaboration)
            → Telegram (if escalation triggered)
```

**Worst case: ~60 minutes from watchlist add to full analysis with CIO decision.**
**Best case: ~15 minutes (if no queue backlog).**

### Deleted Symbol Handling

When a symbol is removed from watchlist:
- `watchlist_items.status` → 'removed'
- Existing agent results preserved (historical)
- No new jobs queued
- Strategy cards remain but marked inactive
- Alex stops pulling cross-agent context for that symbol

### Data Flow Integration Map

```
INGEST LAYER (External → DB):
  Finviz Screeners ──→ ticker_strategy_classifications + watchlist_items
  Yahoo RSS/Finnhub ─→ news_articles (scored + strategy_tags + agent_tags)
  YouTube Transcripts → youtube_transcripts (scored + tagged)
  Social Posts ──────→ social_posts (scored + tagged)
  FMP Dividend API ──→ ticker_dividend_data
  Finviz Enrichment ─→ ticker_enrichment_cache.json (RSI, SMA, ATR)
  Portfolio Import ──→ holdings.json + portfolio DB tables

SCORING + TAGGING LAYER (on every insert):
  content_scoring.py:
    score_content()       → quality_score, relevance_score, validation_status
    score_social_post()   → 6-dimension scoring (relevance, recency, engagement, credibility, sentiment, misinfo)
    tag_content()         → strategy_tags[], agent_tags[]

AGENT LAYER (every 15 min):
  process_watchlist_agent_jobs.py:
    _auto_queue_new_symbols()  → detect + queue unanalyzed symbols
    process_jobs()             → Maria/Steph/Risk/Tax analysis
    _check_pending_synthesis() → auto-synthesize when all agents done
    Cross-agent handoffs       → logged to agent_handoffs table

INTELLIGENCE QUERY LAYER (on-demand):
  intel_query.py:
    get_intel_for_agent()    → pull scored intel tagged to an agent
    get_intel_for_symbol()   → pull intel mentioning a symbol
    get_intel_summary()      → formatted text for LLM prompt injection
  agent_collab.py:
    get_agent_context()      → pull other agents' views on a symbol
    check_escalation()       → detect conflicts, low confidence

DELIVERY LAYER:
  Alex analysis      → portfolio_intelligence_events + Telegram
  Daily/Weekly/Monthly → Telegram (formatted) + ai_reports (DB) + /v2/ai-analyst
  Smart alerts       → Telegram (6 proactive alert types)
  UI pages           → 28 pages, 9 with charts, dropdown nav
```

---

## Remaining Gaps

| Gap | Impact | Status | Fix |
|---|---|---|---|
| Social APIs not configured | No live social data | OPEN | Add TWITTER_BEARER_TOKEN ($100/mo) or STOCKTWITS_API_KEY (free) |
| Agent quality (1.7B) | Maria confidence 0.40, shallow narratives | OPEN | GPU upgrade → qwen3:14b (Arc Pro B50) |
| Decision outcomes tracking | 88 outcomes, 87 with 7d prices | PARTIAL | Need 30+ days for statistical accuracy |
| Brave Search API credits | Wired but 402 Payment Required | NEEDS TOP-UP | Top up at brave.com/search/api ($5/mo) |
| ~~YouTube channel bulk ingest~~ | ~~Need YouTube Data API key~~ | **DONE** | API key added, 10 transcripts ingested, cron at 7 PM daily |
| ~~News scoring basic~~ | ~~Default 0.5 relevance~~ | **DONE** | 345 articles backfilled with scores + tags |
| ~~No live web search~~ | ~~Intel limited to pre-loaded~~ | **DONE** | web_research.py + Brave API wired (needs credits) |

### What's Working Well (No Gaps)

| System | Status |
|---|---|
| Tax bracket room calculation | VERIFIED — real 2025 return + 2026 events |
| Medicare/IRMAA/Medicaid in all analysis | VERIFIED — every Alex prompt |
| Cross-agent collaboration | WORKING — agents see each other's views |
| Auto-escalation on conflicts | WORKING — 22 escalations logged today |
| Auto-queue new watchlist symbols | WORKING — 15 min detection |
| Overnight batch processing | WORKING — 300 jobs/hr capacity |
| 9 pages with charts | WORKING — all loading, tooltips active |
| Dropdown navigation | WORKING — 7 groups, no scrolling |
| Smart Telegram alerts | SCHEDULED — 6 AM weekdays |
| Daily/weekly/monthly reports | SCHEDULED — stored in DB + Telegram |
| News scoring + tagging on ingest | WORKING — every new article scored + tagged |
| 12 Telegram commands | WORKING — tax, intel, conflicts, status, etc. |

---

## Telegram Alert System

### Alert Schedule & Modes (`run_alex_daily.py`)

| Mode | Cron | Content |
|------|------|---------|
| **Daily** | 5:00 AM M-F | Portfolio + income progress bar + tax status + price alerts + escalations + agent activity (7d) + intel highlights |
| **Weekly** | Sunday 8 AM | Portfolio metrics + income bar + tax/Roth + LLM strategy review + agent summary |
| **Monthly** | 1st of month 9 AM | Full sections: portfolio, tax & conversion progress bars, Medicare/Medicaid status, LLM deep review, intel highlights |

### Daily Alert Format
```
📊 Alex Daily Brief — Apr 28
━━━━━━━━━━━━━━━━━━━━━━━━
🟢 Portfolio: $1.20M (+$520 today)
💰 Income: $14,285/yr [▓▓▓░░░░░░░░░░░░] 26%
🎯 Gap: $40,715 remaining to $55,000 target
🏦 Tax: 12% bracket | Room: $66,883 | Roth YTD: $35,000

⚡ 4 Alert(s):
🔴 *KTOS*: -3.6%
🔴 *RKLB*: -4.7%
🔵 *AVAV*: SMA20 cross (+0.5%)
🔵 *CSWC*: SMA20 cross (-0.3%)

🚨 Escalations:
  KTOS: risk_agent has low confidence
  V: Missing analysis from maria

🤖 Agent Activity (7d):
  Maria: 49 analyses (11 buy, 2 sell)
  Risk: 41 analyses (10 buy, 7 sell)
  Steph: 38 analyses (10 buy, 6 sell)

📰 Intel:
  [N] Q:83 How To Use 3 Retirement Accounts...
  [S] Q:74 $SCHD dividend growth...
━━━━━━━━━━━━━━━━━━━━━━━━
🔗 http://ms01-openclaw:7777/v2/
```

### Smart Proactive Alerts (`telegram_smart_alerts.py`)

| Alert Type | Trigger Condition | Schedule |
|---|---|---|
| **Roth Conversion Reminder** | Q4 with room remaining, or mid-year pace check | Weekly |
| **Low Bracket Room** | <$10,000 remaining before 22% bracket | Daily |
| **Income Milestone** | Annual income crosses $10K / $15K / $20K / $25K / $37.5K / $55K | Daily |
| **Agent Conflict** | Agents disagree BUY vs SELL on same symbol | Daily |
| **Stop Proximity** | Position within 3% of stop-loss price | Daily |
| **Medicare Countdown** | Monthly reminder (currently 217 days) | 1st of month |

**Recommended cron:**
```
0 6 * * 1-5  .venv/bin/python scripts/telegram_smart_alerts.py --check-all --telegram
```

### All Telegram Send Points (31 scripts)

| Script | Alert Type | Trigger |
|---|---|---|
| `run_alex_daily.py` | Daily/Weekly/Monthly briefs | Cron |
| `telegram_smart_alerts.py` | Roth/Income/Conflict/Stop/Medicare | Cron (6 AM) |
| `alex_retirement_advisor.py` | Position analysis alerts | On scan (>3% moves, RSI) |
| `recovery_watch_daily.py` | Stop-out escalation | Recovery detection |
| `aegis_morning_brief_delivery.py` | Overnight intelligence brief | 8 AM cron |
| `iterate_research_topics.py` | Research findings | Daily topic iteration |
| `system_health_alerts.py` | System health warnings | Monitoring cron |
| `portfolio_alerts.py` | Earnings/Dividend/Analyst/Technical | Market events |
| `telegram_cio_summary.py` | CIO decision summary | After synthesis |
| `stop_decision_brief.py` | Stop-loss decision notification | After stop trigger |
| `portfolio_monthly_report.py` | Monthly PDF/DOCX report delivery | 1st of month |

---

## UI Visualization Enhancement (v2.24)

### Pages with Charts

| Page | Charts | Data Sources |
|---|---|---|
| **Overview** | Sector doughnut, Income gap ring, Top movers bar, Income progress bar | overview, dividends, tax-situation APIs |
| **Retirement** | Account allocation doughnut, Timeline 3-line projection, Tax bracket viz, Roth progress bar, Medicare countdown | retirement, tax-situation, alex/recent, agents/summary APIs |
| **Dividends** | Income progress hero bar, Top 8 payers doughnut | dividends API |
| **AI Analyst** | Pass/fail/warn doughnut, Position allocation bar, Agent activity cards | ai-analyst, alex/recent, agents/summary APIs |
| **CIO Dashboard** | Decision action doughnut, Priority bar, Agent activity bars | cio-dashboard, cio-decisions, agents/summary APIs |
| **Risk** | Protection coverage doughnut, Stop distance bar, Top movers bar | risk API |
| **Rebalance** | Account allocation doughnut, BUY/SELL recommendation bar | rebalance API |
| **Journal Analytics** | Emotion doughnut, Mistake tags bar, Setup doughnut, Timeframe bar | journal/analytics API |
| **Morning Brief** | Task status doughnut, Risk positions bar, Metric tiles | overview, risk, tasks APIs |

### Shared UI Components

| Component | Features |
|---|---|
| `MetricTile` | Tooltip on hover, icon prefix, trend arrow (↑↓→), glow effect, lift animation |
| `Card` | Accent color border, hoverable glow, click handler with lift |
| `ProgressBar` | Gradient fill, marker lines (min/target/stretch), percentage display, sublabel |
| `Tooltip` | Fade-in animation, configurable position, dark glass style |
| `StatusIndicator` | Pulsing dot + colored label for live status |
| `DoughnutChart` | Custom colors, 65% cutout, dark tooltips |
| `BarChartJS` | Auto green/red by value sign, dark theme |
| `LineChart` | Area fill, tension curves, no-point style |

### Navigation (Dropdown Menus)

| Group | Pages |
|---|---|
| Home | Overview, Daily Brief |
| Portfolio | Holdings, Dividends, Returns, Attribution, Tax & Lots |
| Analysis | Trade AI, Technical, Risk, Correlation, Forecast, Research |
| Strategy | Watchlist, CIO Dashboard, Rebalance, Recovery Watch |
| Retirement | Retirement, AI Analyst, Reports |
| Journal | Journal, Analytics |
| System | System Hub, System Health, Intel Sources, Actions, Approvals |

---

## System Summary (Final — April 28, 2026)

| Metric | Value |
|--------|-------|
| Portfolio | ~$1,197,985 |
| Annual income | $14,285/yr (26% of $55K target) |
| LLM providers | 4 (Local qwen3:1.7b, Grok, Claude, OpenAI) |
| Agents | 7 (Maria, Steph, Risk, Tax, Full Chain, Alex, Aegis) |
| Agent results stored | 195 (cross-agent collaboration active) |
| Agent handoffs logged | 90 (22 escalations) |
| Intelligence events | 76 |
| DB tables | 135 |
| UI pages | 28 (9 with charts, dropdown nav) |
| API endpoints | 48+ |
| Cron entries | 40 (overnight: every 5 min, 25 jobs/batch) |
| Telegram commands | 12 |
| Telegram alert types | 11 (6 smart proactive + 5 scheduled) |
| Intelligence sources | 20 screeners + 5 YouTube channels + social (stub) |
| News articles | 345 (151 strategy-tagged, 345 scored) |
| Charts library | Chart.js (Doughnut, Bar, Line) |
| OpenClaw cron jobs | 3 (evening scan, weekly alloc, monthly income) |
| Web search | Brave API (wired, needs credits) |
| Maturity | **7.5 / 10** |

---

## Quick Wins Completed (Late Session)

| Fix | What |
|---|---|
| 80 .bak files deleted | Cleaned stale backups from UI src |
| income_target/minimum/stretch in DB | $55K/$37.5K/$67.5K in personal_situation (no more hardcoded) |
| Telegram `status` enhanced | Portfolio + income bar + tax + agents + escalations |
| 3 new Telegram commands | `tax`, `intel SYMBOL`, `conflicts` |
| Help text updated | 12 commands with examples |
| Portfolio snapshots | Daily snapshots for performance tracking (overnight_batch writes) |
| 9 symbols queued for synthesis | Gap closed — will process next cycle |
| Auto-queue new watchlist symbols | `_auto_queue_new_symbols()` runs every 15 min |
| Overnight batch processing | 8 PM: metrics + stale refresh + snapshots |
| Auto-research from conflicts | 9 PM: Brave web search + LLM research on agent conflicts |
| Aegis SOUL.md created | Surveillance personality + rules + escalation policy |
| OpenClaw memory enabled | Agents remember across sessions |
| OpenClaw cron: 3 jobs | Evening scan, weekly allocation, monthly income |
| Brave Search wired | `web_research.py` ready (needs account top-up for credits) |
| Overnight agent processing | Every 5 min, 25 jobs/batch (8 PM–5 AM) |

### Telegram Commands (Complete List)

| Command | What You Get |
|---|---|
| `alex V` | Full retirement analysis for V |
| `roth ladder` | 5-year Roth conversion plan with IRMAA + Medicaid |
| `tax` | AGI, bracket, 22% room, Roth YTD, conversion capacity |
| `intel SCHD` | Recent scored intelligence for a symbol |
| `intel` | All agent intel (no symbol filter) |
| `conflicts` | Agent disagreement count |
| `status` | Portfolio + income + tax + agents + escalations |
| `research <topic>` | Save topic for persistent research iteration |
| `find <what>` | Find candidates, saved for iteration |
| `analyze <symbol>` | Analyze symbol or sector |
| `run screener <name>` | Run a Finviz screener by ID |
| `topics` | List active research topics |
| `help` | All commands with examples |

### Overnight Agent Processing Schedule

```
TIME         FREQ      BATCH    CAPACITY
6 AM–7 PM    15 min    10 jobs  40/hr (market hours — light touch)
8 PM–midnight 5 min    25 jobs  300/hr (overnight — clear backlog)
midnight–5 AM 5 min    25 jobs  300/hr (overnight — continued)
Weekends     10 min    15 jobs  90/hr
```

Full portfolio refresh (55 symbols × 3 agents = 165 jobs): **~33 minutes**

### Auto-Research Pipeline

```
8:00 PM  overnight_batch.py → queue stale symbols + record metrics
8:05 PM  Agents start processing (every 5 min, 25/batch)
         Each agent sees other agents' prior views (cross-agent context)
         Each agent sees recent scored intel (tagged news/social)
9:00 PM  auto_research.py → find conflicts + high-impact decisions
         → Brave web search for context
         → Claude deep research on top 3 triggers
         → Findings stored as intelligence events
         → Available in next day's agent context
9:30 PM  All overnight jobs processed, synthesis complete
         → Conflicts auto-escalated to agent_handoffs
         → Telegram alerts for high-priority escalations
5:00 AM  Alex daily scan uses fresh overnight data
```

---

## Session Summary — What Was Built Today (April 28, 2026)

### v2.16–v2.18: Medicaid + Medicare + Tax
- Medicare eligibility (Dec 2026) wired into all Alex analysis
- `--medicare-estimate` CLI with IRMAA tiers + Medicaid eligibility
- Medicaid asset protection trust (MAPT) warnings in Roth ladder
- NY income limit ($20,124/yr) in every conversion analysis

### v2.19–v2.20: Intelligence Sources + YouTube
- `/v2/intelligence-sources` page (3 tabs: Screeners, YouTube, Social)
- `youtube_transcript_ingest.py` + DB table + API endpoints
- `content_scoring.py` unified scoring engine (quality + relevance + validation)
- 5 YouTube channels tracked, paste-and-ingest from UI

### v2.22: Social Media Scoring
- `score_social_post()` with 6-dimension scoring
- Misinfo detection (6 signals penalized)
- `social_monitor.py` with stub ingestion (ready for API keys)
- Social tab in Intel Sources page

### v2.23: Intelligence Tagging + Agent Collaboration
- `tag_content()` — 9 strategy types, 5 agent mappings
- All content tables get `strategy_tags` + `agent_tags` on insert
- `intel_query.py` — agents pull scored intel from their tagged pool
- `agent_collab.py` — cross-agent context injection, escalation detection, handoff audit
- Backfilled 345 news articles with scores + tags (151 tagged, 194 generic)

### v2.24: Visualization + Alerts + Pipeline Integration
- 9 pages enhanced with Chart.js (doughnut, bar, line charts)
- Dropdown navigation (7 groups, no more scrolling)
- MetricTile with tooltips, icons, trend arrows, hover glow
- ProgressBar component with gradient fill + markers
- Enhanced Telegram: daily brief with income progress bar, tax status, agent activity, intel highlights, escalations
- `telegram_smart_alerts.py` — 6 proactive alert types (Roth, income, conflicts, stops, Medicare)
- Auto-queue: new watchlist symbols get 3 agent jobs within 15 minutes
- Finviz screener runner + enrichment refresh added to cron
- Dividend sync added to cron
- `ai_reports` table + Reports tab in AI Analyst page
- `/api/v2/alex/recent`, `/api/v2/agents/summary`, `/api/v2/ai-reports` endpoints
- Fixed tax API serialization bug (dates + Decimals)
- Fixed nav dropdown clipping (overflow CSS)

---

**v2.24 — Full pipeline integration: every 15min auto-queue + agent analysis + synthesis, Finviz 2x daily, enrichment 2x daily, news 3x daily (scored+tagged), 6 smart proactive Telegram alerts, 9 charted pages, dropdown nav, tooltip components. New watchlist symbols fully analyzed within 15-60 minutes. Maturity: 7.5/10.**
