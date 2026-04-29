# Trade AI v12 System Bible v2.46

**April 29, 2026 | ms01-openclaw | 9 Data Sources + Monthly Report + Agent Autonomy + Learning Loop**

All numbers verified against live system. Includes April 29 incident response + SEC EDGAR + yfinance + Alpha Vantage.
See `TRADE_AI_V12_SYSTEM_BIBLE_V2_26_AUDIT.md` for original audit evidence.

---

## System at a Glance (Verified April 29)

| Metric | Verified Value | Evidence |
|--------|-------|---------|
| Portfolio | $1,203,691 | holdings.json (live) |
| Annual income | $14,285/yr (26% of $55K target) | dividend_calendar.json |
| SSDI | $3,800/mo ($45,600/yr) | personal_situation |
| Filing status | MFS | personal_situation (corrected) |
| Tax bracket | 12% — room: $66,883 | personal_tax_history |
| DB tables | **146** | information_schema count |
| API endpoints | 115+ | grep api_v2.py |
| UI pages | 31 (14 with charts) | ls pages/*.tsx |
| Cron entries | **57** | crontab -l |
| Telegram commands | 13 unique (17 parse patterns) | telegram_command_handler.py |
| Agent results | **198** | watchlist_agent_results |
| Agent handoffs | **110 total** (32+ escalations) | agent_handoffs |
| Strategy types | 10 | content_scoring.py |
| YouTube channels | **37 active** (47 trusted scores), 12 transcripts stored | youtube_channels |
| News articles | **552 from 50 sources** | news_articles |
| SEC filings | **4 Form 4 insider filings** | sec_form4 |
| Market quotes | **3 yfinance quotes** | market_quotes |
| Fundamentals | **15 Alpha Vantage metrics** | fundamental_data |
| FRED macro | **7 series LIVE** (DFF, T10Y2Y, UNRATE, CPI, VIX, MORTGAGE30US, SP500) | fred_economic_series |

### Data Sources Feeding Agents (9 active)

| Source | Type | Articles/Records | API Key | Status |
|---|---|---|---|---|
| Yahoo RSS | News | 365 | None needed | ACTIVE — 3x daily |
| Finnhub | News | 32 | FINNHUB_API_KEY | ACTIVE — 3x daily |
| Google News RSS | News (40+ outlets) | 155 | None needed | ACTIVE — Benzinga, SA, Morningstar, Barrons, Bloomberg |
| YouTube Data API | Transcripts | 12 stored (37 channels tracked) | YOUTUBE_API_KEY | ACTIVE — daily 7 PM (3/channel) + backfill mode (50/channel) |
| SEC EDGAR | Form 4 insider | 4 | None needed | ACTIVE — 8 PM daily |
| yfinance | Real-time quotes | 3 | None needed | ACTIVE — 7:15 AM daily |
| Alpha Vantage | Fundamentals (15 metrics) | 15 | ALPHA_VANTAGE_API_KEY | ACTIVE — Monday 8 AM |
| FMP | Dividends, yields | 34 symbols | FMP_API_KEY | ACTIVE — 7:05 AM daily |
| **FRED** | **Macro (7 series)** | **7 live** | **FRED_API_KEY** | **ACTIVE — daily 6:30 AM** |

### Not Yet Active

| Source | Why | Cost |
|---|---|---|
| Brave Search | 402 Payment Required | $5/mo |
| Social (X/StockTwits) | No API keys | $100/mo (X) or free (StockTwits) |
| SEC 13F | Schema ready, quarterly parser TBD | Free |
| SEC XBRL | Schema ready, XBRL parser TBD | Free |

---

## System Trust Matrix

### HIGH TRUST — Rely on these

| System | Why | Evidence |
|---|---|---|
| Portfolio tracking | Real broker data, 4 accounts | holdings.json from Schwab/Fidelity imports |
| Tax bracket math | Computed from real 2025 return + 2026 events | personal_tax_history + tax_events |
| Income gap calculation | FMP API dividends, real yield data | income_asset_profiles (41 symbols) |
| DB infrastructure | 142 tables, PostgreSQL, proper indexes | Live verified |
| API layer | 105+ endpoints, all returning data | curl verified |
| Cron pipeline | 45 entries, proper paths, overnight 300/hr capacity | crontab verified |
| yfinance quotes | Real-time prices, PE, yield, 52wk range | 3 quotes tested |
| Alpha Vantage fundamentals | 15 metrics per symbol (PE, EPS, margins, target) | V tested: 15 metrics |
| SEC Form 4 | Insider transactions from data.sec.gov | 4 filings (V, LMT) |
| Classification engine | 55 symbols, strategy-based rules, no hard-coded tickers | ticker_strategy_classifications |
| Safety gates | Income protection, RSI override, position sizing blocks | 10 blocked syntheses in history |

### MEDIUM TRUST — Functional but quality-limited

| System | Limitation | Impact |
|---|---|---|
| Agent analysis (Maria/Steph/Risk) | qwen3:1.7b model — Maria avg confidence 0.49 | Shallow narratives, low reasoning depth |
| Synthesis pipeline | Strategy-weighted but LLM quality limits output | Directional, not precise |
| News ingestion | **46 sources live: Yahoo RSS (365) + Finnhub (32) + Google News RSS (120)** — Seeking Alpha, Motley Fool, Morningstar, Barron's, Bloomberg + 30 more | 85% of Google News articles untagged (short summaries = fewer keyword matches) |
| Content scoring | Keyword-based, not semantic | Good for tagging, not for nuance |
| Cross-agent collaboration | Agents see each other's views, but still limited by 1.7B quality | Better than isolated, but not deep reasoning |
| YouTube transcripts | 12 transcripts from 6 channels. IP rate-limiting blocks some fetches | Intermittent, depends on YouTube's mood |
| Alert system | Smart alerts work (Roth, stops, conflicts) but based on threshold rules | Not predictive, reactive only |

### LOW TRUST — Do not rely for decisions

| System | Reality | What to do instead |
|---|---|---|
| CIO decisions | 55 proposed, 0 acted on, 0 evaluated | Treat as suggestions only. Human review required |
| Decision outcomes | 88 tracked, 87 with 7d prices, but NO accuracy evaluation | Pipeline exists, needs 30+ days of accumulation |
| Agent performance scoring | 2 entries in agent_performance_history | Too little data to judge accuracy |
| Signal fusion | 166 fused signals but keyword-based sentiment | Directional signal only |
| Auto-research (Brave) | Code wired but API returns 402 (needs $5 credit) | Not active |

### NOT IMPLEMENTED / EMPTY

| System | Status |
|---|---|
| Social intelligence | 3 manual test posts. No API keys (X: $100/mo, StockTwits: free) |
| Signal clustering | 0 records in signal_clusters |
| MARL learning | 1 simulation run, shadow mode only |
| Real-time news monitoring | No streaming — batch 3x daily |

### RECENTLY FIXED (code deployed, awaiting production validation)

| System | Status | Evidence |
|---|---|---|
| Decision audit trail | `decision_inputs` table created + wired into synthesis | 0 records — awaiting next synthesis cycle |
| Aegis intelligence events | INSERT added to `aegis_morning_brief_delivery.py` | 0 events — awaiting next 8:05 AM cron |
| Learning loop | `get_outcome_feedback()` wired into all agent prompts + Alex | Agents see CORRECT/WRONG labels for past decisions. Tested: SCHD, V, RTX outcomes visible |
| News 46 sources | Savepoint fix + URL dedup applied | 517 articles, 46 sources verified in DB |

---

## Operator Decision Framework

### When to ACT on a system recommendation

**ALL of these must be true:**
- `synthesis.recommendation` exists (not just agent-level)
- `synthesis.confidence` > 60%
- `safety_status` = safe or actionable
- No unresolved agent conflicts
- Not an income-critical position (>20% of income) OR you've reviewed it manually
- Decision is less than 7 days old

### When to REVIEW (human judgment required)

- Income asset with TRIM/SELL recommendation
- Agent conflict (BUY vs SELL on same symbol)
- Confidence between 40-60%
- Escalation triggered (auto-escalation logged in agent_handoffs)
- Position >5% of portfolio weight
- Any Roth conversion recommendation (always verify with CPA)

### When to IGNORE

- Confidence < 40%
- Decision from single agent without synthesis
- CIO decisions still in 'proposed' status with no human review
- Any decision older than 14 days
- Anything marked 'baseline' or 'synthetic'

---

## YouTube Transcript Pipeline — Complete Methodology

### How Transcripts Are Ingested

```
1. CHANNEL TRACKING (37 active channels across 4 strategies)
   └→ youtube_channels table: channel_id, name, strategy_focus, last_checked
   └→ Strategies: dividend_growth_compounding (10), swing_trading (9),
      retirement_ssdi_roth_tax (5), market_trends_sectors (9), other (4)

2. DAILY PULL (7 PM weekdays via cron)
   └→ youtube_transcript_ingest.py --all-channels
   └→ YouTube Data API: list latest 3 videos per channel via uploads playlist
   └→ For each video: check if video_id already in DB (dedup)
   └→ 37 channels × 3 videos = up to 111 videos checked daily

2b. AUTOMATED BACKFILL (youtube_backfill_manager.py — runs until complete)
   └→ Cron: every 4 hours until all 37 channels completed
   └→ Processes 5 channels per batch (retirement/SSDI prioritized first)
   └→ 50 videos per channel (~12 months of weekly uploads)
   └→ State machine: pending → in_progress → completed / rate_limited
   └→ Rate limit handling:
      • Detects YouTube IP blocks (429/IpBlocked)
      • Stops batch on rate limit (saves API calls)
      • Waits 4 hours before retrying rate_limited channels
      • 3 consecutive transcript failures = rate_limited (safety cutoff)
   └→ Tracking: youtube_backfill_status table (per-channel progress)
      CLI: --status (matrix), --reset (restart all)
   └→ Telegram progress updates on each batch
   └→ Estimated: ~3 days to complete 37 channels with rate limits
   └→ Self-exits when all channels completed (cron harmless after that)

3. TRANSCRIPT FETCH (2 methods, fallback chain)
   └→ Method 1: youtube-transcript-api library (English captions)
   └→ Method 2: timedtext scraping (fallback if IP-blocked)
   └→ If both fail: video skipped, no error propagated

4. RAW STORAGE (no cleaning)
   └→ Store up to 50,000 chars of raw auto-generated caption text
   └→ Includes "um", "uh", filler words, misrecognitions
   └→ NO text cleaning, NO summarization applied
   └→ Current total: 12 transcripts, 0.16 MB

5. SCORING (first 5,000 chars scored — deterministic, keyword-based)
   Quality Score (0-100):
     Base: 40 (YouTube default)
     Trusted channel boost: 55-80 (18 channels in trusted list)
     Penalty: short text (<100 chars: -30, <500 chars: -10)
     Penalty: clickbait signals (🚀, "guaranteed", "!!!!"): -15
   
   Relevance Score (0-100%):
     High keywords (27): +15% each (dividend, yield, roth, ira, retirement...)
     Medium keywords (20): +8% each (earnings, guidance, PE ratio, analyst...)
     Low keywords (11): +3% each (stock, market, bull, bear...)
     Symbol mention: +10% each ($V, $SCHD, etc.)

6. TAGGING (rule-based, not ML)
   └→ Strategy tags: 10 types (dividend_growth, retirement_planning, etc.)
   └→ Agent tags: 5 agents (Alex, Maria, Steph, Risk, Aegis)
   └→ Matching: if ANY keyword from strategy/agent list appears → tagged

7. VALIDATION STATUS
   └→ ai_validated: Quality ≥ 60 AND Relevance ≥ 30%
   └→ low_confidence: Quality < 30 OR Relevance < 10%
   └→ unscored: everything in between

8. AVAILABLE TO AGENTS via intel_query.get_intel_summary()
```

### Retention & Purge

- **Tiered retention**: Q≥75 forever, Q50-74 12 months, Q<50 90 days
- `purge_after` dates set automatically on every transcript
- Monthly cron: `--purge-expired` deletes transcripts past their purge date
- Current storage: 0.16 MB (12 transcripts). Projected: ~100 MB/year

### Channel Discovery (Agent-Driven)

```
MONTHLY (1st of month via cron):
  youtube_channel_discovery.py --discover

1. Search YouTube for channels matching 10 strategy-aligned queries:
   - "dividend growth investing 2026"
   - "retirement income strategy SSDI disability"
   - "Roth conversion ladder strategy"
   - "high yield income BDC CEF investing"
   - "covered call ETF income strategy"
   - etc.

2. For each discovered channel:
   - Get subscriber count + video count via YouTube Data API
   - Score: keyword relevance + subscriber quality + upload consistency
   - Classify: ADD (Q≥50), REVIEW (Q≥30), SKIP (Q<30)

3. Store in youtube_channel_candidates table (status='pending')

4. Human reviews candidates:
   python3 scripts/youtube_channel_discovery.py --list-candidates
   python3 scripts/youtube_channel_discovery.py --approve CHANNEL_ID

5. Approved channels added to youtube_channels → daily 7 PM auto-ingest
```

### Transcript Processing — Full Hybrid Pipeline (v2.35 — `transcript_processor.py`)

6-step pipeline built for scale (tested on 12, designed for 1000+):

```
RAW TRANSCRIPT
  │
  ▼
STEP 1: CLEAN (deterministic, no LLM)
  Remove fillers: um, uh, you know, like, basically, sort of, kind of
  Collapse whitespace, sentence capitalization
  → cleaned_text column
  │
  ▼
STEP 2: EXTRACTIVE PRE-FILTER (TextRank via Sumy)
  Keep top 35% most important sentences using TextRank algorithm
  Reduces noise before sending to LLM
  Tested: 20,088 chars → 11,804 chars (59% kept) on PPC Ian
  Falls back to truncation if Sumy fails
  → Used as input for Step 3 (not stored separately)
  │
  ▼
STEP 3: ABSTRACTIVE STRUCTURED SUMMARY (LLM) — v2.36 enhanced schema
  Strict JSON with validation + 1 retry on failure:
  {
    "summary": "150-250 word professional overview",
    "key_points": ["point 1", ...] (5-8 concise factual points),
    "action_items": ["recommendation 1", ...] (max 6),
    "tickers_mentioned": ["SCHD", "V", "JEPI"],
    "retirement_relevance": "high | medium | low",
    "relevance_score": 0-100,               ← NEW v2.36
    "main_topics": ["roth_conversion_ladder", "income_gap_strategy"],  ← NEW v2.36
    "llm_confidence": 0-100                 ← NEW v2.36
  }
  Required keys validated: summary, key_points, retirement_relevance
  If missing → retry once with same prompt
  Routing: Claude for Q≥70 videos, local model for rest
  Results: 8/12 transcripts with full schema (relevance 85-95, confidence 90-95)
  → summary column + structured_json JSONB column
  │
  ▼
STEP 4: SUB-TAGGING (12 retirement-specific regex patterns)
  roth_conversion_ladder  │ ssdi_ira_rules         │ medicaid_trust_planning
  disability_spousal_ira  │ irmaa_medicare         │ income_gap_strategy
  tax_bracket_management  │ covered_call_income    │ dividend_growth
  rmd_planning            │ 401k_rollover          │ bond_ladder
  → sub_tags JSONB column
  │
  ▼
STEP 5: CROSS-CHANNEL DEDUPLICATION
  Jaccard similarity on word 5-gram fingerprints
  Compares transcripts across different channels
  Threshold: 40% similarity = flagged as potential duplicate
  Same-channel comparisons skipped (expected overlap)
  CLI: python3 scripts/transcript_processor.py --dedup
  → Report only (does not auto-delete — human review)
  │
  ▼
STEP 6: TIERED PURGE DATES
  Q ≥ 75: keep forever (Ben Felix Q:80)
  Q 50-74: purge after 12 months (PPC Ian Q:65 → Apr 2027)
  Q < 50: purge after 90 days (zoo video Q:30 → Jul 2026)
  Monthly cron: --purge-expired deletes past-due transcripts
  → purge_after column
```

### Agent Integration (How Agents See Transcript Data)

Agents receive structured YouTube intelligence via `intel_query.get_intel_summary()`:
```
[youtube] Q:70 When Individual Bonds Make Sense (bond income)
  — Summary text from LLM...
  • Key point 1 (from structured_json.key_points)
  • Key point 2
  → Action item (from structured_json.action_items)
```

### Unified Agent Data Source Config

`config/agents_data_sources.yaml` — single source of truth defining for each agent:
- Which data sources they consume (news, YouTube, SEC, yfinance, AV, FRED, FMP)
- What specific data they get from each source
- Automated triggers (insider buys, rate changes, dividend cuts, RSI extremes)

### What Is NOT Done (Remaining Limitations)

- No semantic understanding ("Apple stock is terrible" would match AAPL positively)
- No caption quality detection (auto-generated vs manual not distinguished)
- Summaries depend on 1.7B model for Q<70 transcripts (Claude used for Q≥70)
- Sub-tags are regex-based, not semantic (may miss creative phrasings)
- Dedup is report-only — does not auto-delete (requires human review)

---

## Intelligence Limitations (Honest Assessment)

### What the scoring engine CANNOT do

- **No semantic understanding** — keyword matching only. "Apple stock is rotten" scores positive for AAPL
- **No sentiment depth** — "bearish", "upgrade" are binary signals, not nuanced
- **No entity disambiguation** — $V matches both Visa and any text containing "$V"
- **No real-time processing** — batch 3x daily. Breaking news takes 4-8 hours to enter pipeline
- **No social intelligence** — stub only, 3 manual test posts
- **No web search in production** — Brave wired but 402 error, no credits

### What the agents CANNOT do

- **Cannot reason deeply** — qwen3:1.7b is the primary model. Maria's avg confidence is 0.49
- **Cannot verify facts** — no real-time data lookup during analysis
- **Cannot learn from mistakes** — no feedback loop from decision outcomes to future prompts
- **Cannot communicate in real-time** — see prior views, not live discussion
- **Alex (Claude) is the only high-quality reasoner** — but only runs on-demand, not in overnight batch

### Data lineage gap

`decision_inputs` table created and wired into synthesis pipeline. Records which agent results and news articles fed into each CIO decision. **Status: table exists, code wired, 0 records yet (will populate on next overnight synthesis cycle). UNTESTED in production.**

---

## 1. News Pipeline (VERIFIED — tested without bias April 28)

### Live in DB (517 articles, 46 distinct sources)

| Source | Articles | Notes |
|---|---|---|
| Yahoo RSS | 365 | Primary. Free, always active |
| Finnhub | 32 | Requires API key |
| Google News RSS | 120 | **FIX APPLIED**: savepoint fix + dedup by URL (not title). 40+ outlets captured |

### Top Google News sources now live

| Source | Articles | Status |
|---|---|---|
| Seeking Alpha | 10 | VERIFIED in DB |
| Motley Fool | 10 | VERIFIED in DB |
| Morningstar | 5 | VERIFIED in DB |
| MarketBeat | 6 | VERIFIED in DB |
| Barron's | 2 | VERIFIED in DB |
| Bloomberg | 1 | VERIFIED in DB |
| + 30 more | 86 | Various (GuruFocus, TipRanks, IBD, Kiplinger, InvestorPlace, etc.) |

### Known limitation

85% of Google News articles (102/120) have NO strategy tags. Reason: Google News summaries are very short (just the title repeated), so keyword-based tagging finds fewer matches. These articles are still stored, scored, and available to agents — they just don't route to specific strategies.

### Benzinga API

Placeholder in `.env`. No API key configured. Will activate with `BENZINGA_API_KEY`.

### Downstream feed

`news_articles` → `catalyst_events` (if relevance > 0.3) + `sentiment_observations`. Uses savepoints so failures don't abort the main transaction.

### What was broken and how it was fixed

**Root cause**: `_feed_downstream()` had `conn.rollback()` in exception handlers. When a downstream INSERT failed (constraint violation), it rolled back the ENTIRE transaction — including the news_articles INSERT that had already succeeded.

**Fix**: Replaced `conn.rollback()` with PostgreSQL savepoints (`SAVEPOINT`/`ROLLBACK TO SAVEPOINT`). Also fixed dedup: Google News articles now dedup by URL only (their URLs are unique even when titles overlap with Yahoo).

---

## 2. Agent System (Verified)

| Agent | Results | Avg Confidence | Min | Max | Quality |
|---|---|---|---|---|---|
| Maria (Research) | 71 | 0.49 | 0.00 | 0.85 | **Low** — limited by 1.7B model |
| Risk (Technical) | 63 | 0.71 | 0.00 | 0.85 | **Medium** — technical analysis suits small models |
| Steph (Allocation) | 60 | 0.71 | 0.20 | 0.95 | **Medium** — income/allocation logic works |
| Tax | 1 | 0.85 | 0.85 | 0.85 | **Insufficient data** — barely used |
| Alex (Claude) | On-demand | N/A | N/A | N/A | **High** — Claude-powered, but only runs when you ask |
| Aegis | Scripts exist | N/A | N/A | N/A | **Not producing intelligence events** (0 in DB) |
| Full Chain | Script exists | N/A | N/A | N/A | **Not used** on real symbols |

---

## 3. Disability Retirement Planning (Verified)

48 disability-related references in `alex_retirement_advisor.py`. Every Alex analysis includes:

| Rule | Verified In |
|---|---|
| SSDI $3,800/mo status | Every prompt + --tax-situation output |
| MFS filing (corrected in DB) | personal_situation + personal_tax_history |
| No 10% penalty (disability + age) | Analyze + Roth ladder prompts |
| Spousal IRA loophole | _format_tax_context() |
| Backdoor Roth (MFS workaround) | Roth ladder prompt |
| Pro-rata warning ($556K IRA) | Roth ladder prompt |
| Creditor protection (ERISA vs NY) | Analyze + Roth ladder prompts |
| Medicaid disability pathway | _format_tax_context() |
| Trust transfer tracking | 4 DB columns exist, API works, 0 transfers recorded |

---

## 4. Telegram Commands (13 unique, 17 parse patterns)

| Command | Parse Pattern | Status |
|---|---|---|
| `help` | help | VERIFIED |
| `status` | status | VERIFIED — full dashboard with portfolio/income/tax/agents |
| `tax` | tax | VERIFIED — bracket, room, Roth YTD, disability status |
| `intel [SYMBOL]` | intel, intel SYMBOL | VERIFIED — scored intelligence |
| `conflicts` | conflicts | VERIFIED — agent disagreement count |
| `alex SYMBOL` | alex SYMBOL | VERIFIED — Claude-powered retirement analysis |
| `retirement SYMBOL` | retirement SYMBOL | Alias for alex |
| `roth ladder` | roth ladder / roth conversion | VERIFIED — 5-year projection |
| `research TOPIC` | research TOPIC | VERIFIED — persistent topic |
| `find WHAT` | find WHAT | VERIFIED — discovery + persist |
| `analyze SYMBOL` | analyze SYMBOL | VERIFIED — LLM analysis |
| `run screener NAME` | run screener NAME | VERIFIED |
| `topics` | topics | VERIFIED — list active research |

---

## 5. UI Pages (31 verified, 14 with charts)

| Page | Charts | Key Data |
|---|---|---|
| Overview | Sector doughnut, Income gap ring, Top movers bar, Progress bar | VERIFIED |
| Retirement | Account doughnut, Timeline 3-line, Tax bracket, Roth bar, Medicare, Alex analyses, Agent activity | VERIFIED |
| Dividends | Income progress bar, Top payers doughnut | VERIFIED |
| AI Analyst | Pass/fail doughnut, Position bars, Alex activity, Reports tab | VERIFIED |
| CIO Dashboard | Decision doughnut, Priority bar, Agent bars | VERIFIED |
| Risk | Protection doughnut, Stop distance bar, Top movers | VERIFIED |
| Rebalance | Account doughnut, BUY/SELL bar | VERIFIED |
| JournalAnalytics | Emotion doughnut, Mistake bars, Setup doughnut, Timeframe | VERIFIED |
| MorningBrief | Task doughnut, Risk bar, Metric tiles | VERIFIED |
| Portfolio | Charts present | VERIFIED |
| Forecast | Charts present | VERIFIED |
| Returns | Charts present | VERIFIED |
| Journal | Charts present | VERIFIED |
| TradeAI | Charts present | VERIFIED |
| + 17 more pages | No charts | Functional but text/table only |

### Intelligence Sources Page (`/v2/intelligence-sources`)

Header shows **"72 sources configured"** = sum of all items across 3 tabs:

| Tab | Count | What It Shows |
|---|---|---|
| **Screeners (20)** | 20 Finviz screeners | Name, strategy, URL, keywords, sources, added_by, schedule |
| **YouTube (12)** | 12 stored transcripts | Channel, title, duration, quality, relevance, status, keywords |
| | 37 tracked channels | Listed below transcript table with strategy focus |
| **Social (3)** | 3 manual test posts | Platform, user, text, quality, sentiment, validation |

**Why YouTube says "(12)" not "(37)":** The tab count shows transcripts stored in DB, not channels tracked. 37 channels are tracked but backfill is still processing — only 12 transcripts ingested so far. As backfill completes (~3 days), this number will grow to 500+ transcripts.

**Scoring status breakdown (current 12 transcripts):**
- ai_validated (Q≥60 + R≥30%): PPC Ian (3), Rob Berger (2) = 5 transcripts
- unscored (middle ground): Ben Felix, InvestKaki, Strong Man = 3 transcripts
- low_confidence (Q<30 or R<10%): Rational Reminder, Rob Berger bonds, zoo = 3 transcripts
- too short for scoring: zoo video = 1 transcript

---

## 6. Pipeline Timeline (Verified against crontab)

```
5:00 AM   Alex daily scan → Telegram
6:00 AM   Smart alerts (Roth/income/conflicts/stops/Medicare) → Telegram
6:15 AM   Agent router full refresh
6:25 AM   Agent intelligence daily
6:30 AM   News ingestion (Yahoo + Finnhub + Google News [pending]) → score + tag
6:35 AM   Classify candidates
6:40 AM   Intel auto-discovery (scan for new tickers)
6:45 AM   Sync watchlist
6:50 AM   Materialize strategy cards
6:55 AM   Income engine
7:00 AM   CIO decisions + dividend sync
7:10 AM   Finviz enrichment (RSI, SMA, ATR)
7:15-7:50 Freshness, prices, health, recovery, QA, outcomes
8:00 AM   Research topics + Aegis brief → Telegram
10:00 AM  Finviz screeners (market open)
12:30 PM  News refresh + 12:40 PM intel discovery
1:00 PM   Enrichment refresh
4:00 PM   Finviz screeners (market close)
6:30 PM   Evening news
7:00 PM   YouTube auto-discover (6 channels)

OVERNIGHT (8 PM–5 AM, every 5 min, 25 jobs/batch = 300/hr):
  8:00 PM   Metrics + stale refresh + snapshots
  9:00 PM   Auto-research (conflicts via Claude)
  
WEEKLY (Sunday): Strategy review + allocation check + watchlist hygiene
MONTHLY (1st): Deep tax reconciliation + Roth ladder + income progress
```

---

## 7. Remaining Gaps (Honest — updated April 29)

| Gap | Impact | Cost to Fix |
|---|---|---|
| Agent quality (qwen3:1.7b) | Maria confidence 0.49, shallow reasoning | GPU → qwen3:14b (hardware pending) |
| Brave Search API | Wired but 402 Payment Required | $5/mo |
| Social APIs | 3 manual test posts, no live data | $100/mo (X) or free (StockTwits) |
| Decision outcome evaluation | 88 tracked but 0 accuracy scored | Needs 30+ days |
| Signal clustering | 0 records | Not implemented |
| MARL | 1 shadow run | Not functional |

### Gaps CLOSED (April 28-29)

| Gap | Fix | Status |
|---|---|---|
| ~~News limited to 2 sources~~ | Savepoint fix + URL dedup. 552 articles, 46 sources | **VERIFIED** — preflight confirms |
| ~~Decision audit trail~~ | `decision_inputs` table created + wired into synthesis | **DEPLOYED** — 0 records, populates on next synthesis |
| ~~Learning loop~~ | `get_outcome_feedback()` in every agent + Alex prompt | **WORKING** — tested with SCHD, V, RTX outcomes |
| ~~Aegis intelligence~~ | INSERT added to `aegis_morning_brief_delivery.py` | **DEPLOYED** — will produce events on next cron |
| ~~Finviz broken~~ | URL `/export.ashx` → `/export`, `.env` sourcing in launcher | **VERIFIED** — 41 tickers via preflight check |

---

## 8. Production Incident Log — April 29, 2026

### What Broke (reported by John at 7 AM)

| Issue | Symptom |
|---|---|
| No scalp candidates | Trade AI runner producing 0 GO/WAIT tickers |
| No morning brief | Aegis brief not delivered |
| Stop briefs showing $0.00 | Price and stop fields empty in Telegram |

### Root Cause Analysis (all pre-existing, NOT caused by April 28 session)

| Issue | Root Cause | When It Actually Broke | Evidence |
|---|---|---|---|
| **Finviz 0 tickers** | Finviz changed URL from `/export.ashx` → `/export` (301 redirect) | External change by Finviz (unknown date) | Yesterday's log: 13 tickers. Today: 0 + "No tickers" |
| **Finviz cookie not loaded** | `run_continuous.sh` never sourced `.env` file. `os.getenv("FINVIZ_COOKIE")` returned empty | Pre-existing launcher bug. Worked when env was set by other mechanism | Launcher had no `source .env` line |
| **Ollama warm-up 404** | Hardcoded `qwen3:14b` but only `1.7b` installed | Pre-existing mismatch | Line 114: `"model":"qwen3:14b"` |
| **Stop briefs $0.00** | `portfolio_orchestrator.py` line 210: `"price": 0, "stop_price": 0` hardcoded in fallback | Pre-existing bug in orchestrator | Code inspection confirms |
| **Morning brief crash** | Export path pointed to deleted `docs/handoff_2026-04-19/` directory | Pre-existing since old docs cleanup | Directory does not exist |

### Fixes Applied

| Fix | File | Change |
|---|---|---|
| Finviz URL | `assets/screeners.yaml` + 3 scripts | `/export.ashx` → `/export` |
| .env sourcing | `linux_launchers/run_continuous.sh` | Added `set -a; source .env; set +a` |
| Ollama model | `scripts/trade_ai_orchestrator.py` | `qwen3:14b` → `qwen3:1.7b` |
| Pipeline abort | `scripts/trade_ai_orchestrator.py` | Graceful fallback to cached tickers instead of `return 1` |
| Stop prices | `scripts/portfolio_orchestrator.py` + `scripts/stop_decision_brief.py` | Pass real prices from alerts + enrichment cache fallback |
| Brief export | `scripts/aegis_morning_brief_delivery.py` | Fixed path to `docs/` |
| **Value desync** | `scripts/api_v2.py` (aegis/chat-context) | Aegis showed stale $1,197,222 vs live $1,203,691. Now reads LIVE from holdings.json |
| **Header tape 0s** | `scripts/api_v2.py` (overview) | Header showed `0 GO · 0 WAIT` while Trade AI page showed `1 GO · 4 WAIT`. Root cause: `run_summary.json` uses snake_case (`go_count`) but overview read camelCase (`goCount`). Fixed: reads both with fallback |

### Data Sync Verification (all APIs cross-checked April 29)

| Source | Value | In Sync |
|---|---|---|
| `holdings.json` | $1,203,691 | LIVE |
| API `/api/v2/overview` | $1,203,691 | YES |
| API `/api/v2/overview` trade_ai | GO:1 WAIT:4 label:0700 | **FIXED** (was 0s) |
| API `/api/v2/trade-ai` | GO:1 WAIT:4 tickers:6 top:KALV | YES |
| Aegis `/api/v2/aegis/chat-context` | $1,203,691 | **FIXED** (was $1,197,222) |
| Telegram Portfolio Intel (7:07 AM) | $1,203,691 | YES |
| Telegram Scalp (8:14 AM) | KALV GO-tier, WALD NEW GO | WORKING |
| Stop briefs (next trigger) | Will show real prices | FIXED |

### camelCase vs snake_case Audit

All internal state files use snake_case. Verified no remaining mismatches:
- `run_summary.json`: `go_count`, `wait_count`, `run_label`, `date` (snake_case)
- `holdings.json`: `total_value`, `day_change`, `day_change_pct` (snake_case)
- `risk_management.json`: `stop_price`, `dist_pct`, `market_value` (snake_case)
- API `overview` now reads both formats with fallback: `tai.get("goCount", tai.get("go_count", 0))`
- External APIs (Yahoo Finance, Finviz CSV) correctly use their own formats

### Prevention: System Preflight Check

**`scripts/system_preflight_check.py`** — 19-point health check. Run before AND after any session:

```bash
python3 scripts/system_preflight_check.py
```

| Check | What It Catches |
|---|---|
| FINVIZ_COOKIE exists + has auth tokens | Cookie expiry / missing |
| Finviz CSV download + returns tickers | URL changes, auth failures |
| Ollama responds with correct model | Model name mismatches |
| 3 API endpoints return OK | Server crashes, route errors |
| Database tables + article + agent counts | DB connection, data loss |
| Systemd services active | Service crashes |
| State files fresh (<24h) | Stale data, failed imports |
| Screener URLs use `/export` not `.ashx` | Finviz URL format changes |

**Current result: 18/19 PASS** (portfolio-server runs via nohup, not systemd — expected)

---

## Maturity Score (Honest — updated April 29 after SEC + market data)

| Component | Score | Change | Justification |
|---|---|---|---|
| Infrastructure (DB, API, cron) | **97%** | +1% | 143 tables, 105+ APIs, 48 crons, preflight check, weekly backup, DB backup |
| Data ingestion | **85%** | +7% | 8 active sources: 50 news outlets + YouTube + SEC + yfinance + Alpha Vantage + FMP. Only social + FRED missing |
| Agent intelligence | 55% | — | 198 results but 1.7B quality. Cross-agent + outcome feedback + SEC + fundamentals in prompts |
| Decision system | 58% | — | `decision_inputs` wired. Outcome tracking active. 0 human-evaluated |
| Disability/tax planning | 85% | — | Alex comprehensive. Trust tracking, MFS, spousal IRA |
| UI/visualization | 80% | — | 31 pages, 14 charts, dropdown nav, tooltips |
| Automation | **91%** | +3% | Full lifecycle + SEC/yfinance/AV crons + 23-point preflight gate + weekly backup + DB backup + garbage cleanup |
| Learning/feedback | 35% | — | Outcome → prompt feedback working. Still needs 30d data |
| **Overall** | **74%** | +1% | Infrastructure 97%, Automation 91% (gates + backups + garbage cleanup) |

**What moved:**
- Data ingestion: 85% — 8 active sources covering news (50 outlets), transcripts, SEC filings, real-time quotes, fundamentals, dividends
- Automation: 88% — SEC daily, yfinance daily, Alpha Vantage weekly, plus preflight check for prevention
- Infrastructure: 96% — 142 tables (was 135), 7 new tables this session

**What didn't move:**
- Agent quality still 1.7B (hardware upgrade needed)
- Social intelligence still empty (API keys needed)
- FRED macro not active (needs free API key)
- 0 decisions acted on or human-evaluated
- Decision lineage table deployed but 0 records populated

---

## 9. Version History

| Version | Key Changes |
|---|---|
| v2.16–v2.18 | Medicare, Medicaid, IRMAA, tax context |
| v2.19–v2.20 | Intel Sources page, YouTube pipeline, content scoring |
| v2.22–v2.23 | Social scoring, intelligence tagging, agent collaboration |
| v2.24 | Charts (14 pages), dropdown nav, Telegram enhancements, overnight batch |
| v2.25 | Disability planning, trust tracking, auto-discovery, watchlist hygiene |
| v2.26 | Audit: verified all numbers, found contradictions |
| v2.27 | Honest rewrite: removed contradictions, Trust Matrix, Operator Framework, Intelligence Limitations |
| v2.28 | 4 critical fixes: news 46 sources, Aegis events, decision_inputs, learning loop |
| v2.29 | April 29 incident response: Finviz URL, .env sourcing, ollama model, stop prices, header tape sync, preflight check |
| v2.30 | SEC EDGAR Form 4 + yfinance + Alpha Vantage + agent YAML config |
| v2.31 | YouTube channel auto-discovery. Full transcript methodology documented |
| v2.32 | Transcript processor: cleaning, LLM summaries, 12 sub-tags, purge dates |
| v2.33 | Structured YouTube JSON, 9 data sources in every prompt, service restart fix |
| v2.34 | Breakage gates (23-point preflight), weekly backup zip, garbage cleanup (43 MB), restore guide |
| v2.35 | Full hybrid transcript pipeline: TextRank extractive + structured JSON + cross-channel dedup + agents_data_sources.yaml |
| v2.36 | Enhanced structured JSON: relevance_score, main_topics, llm_confidence. Alex context 400→1200 chars |
| v2.37 | Complete 9/9 structured JSON schema. timestamped_highlights from timed segment analysis |
| v2.38 | 37 YouTube channels, 47 trusted scores, manual backfill mode |
| v2.39 | Automated backfill manager: processes 5 channels/batch every 4 hours until all 37 complete. Rate limit detection + 4h cooldown + auto-retry. State tracking in youtube_backfill_status table. Retirement/SSDI channels prioritized. ~3 days to complete.** |

### What Alex Sees in Every Analysis (v2.33 — verified)

```
SEC FORM 4: VISA INC. insider transactions (2026-03-12)
YFINANCE: $309.30 | PE:26.9 | Yield | 52wk: $294-$376
ALPHA VANTAGE: 200DMA=332.98, 50DMA=309.96, AnalystTarget=$392.33, Beta=0.80
YOUTUBE (structured):
  [Q:70] When Individual Bonds Make Sense
    • Individual bonds offer more control over when to sell
    • Bond funds can experience value drops
    → Consider using bond funds if you prefer lower fees
NEWS (50 sources): scored + tagged articles from SA, Morningstar, Barrons...
SOCIAL: scored posts
OUTCOME FEEDBACK: past CORRECT/WRONG decisions
CROSS-AGENT: Maria/Steph/Risk latest views
MACRO: FRED data (when API key added)
```

---

## Breakage Prevention (v2.34)

### 3 Gates

| Gate | When | What It Catches |
|---|---|---|
| **Preflight check (23 tests)** | Run manually: `python3 scripts/system_preflight_check.py` | Finviz cookie/URL, ollama, APIs, data sync, header values, stops, runner output |
| **Service startup gate** | Every `tradeai-continuous.service` start | Preflight runs automatically before Trade AI runner launches, logged to `preflight-YYYYMMDD.log` |
| **Data sync checks** | Part of preflight | Aegis portfolio value matches overview, header GO matches Trade AI page, stop prices exist |

### Preflight Check — 23 Tests

| Category | Tests |
|---|---|
| Finviz (5) | Cookie exists, has .ASPXAUTH, has .AspNetCore.Session, CSV downloads, returns tickers |
| Ollama (1) | qwen3:1.7b responds |
| Portfolio Server (3) | /api/v2/overview, /api/v2/tax-situation, /api/v2/alex/recent all return OK |
| Database (3) | PostgreSQL connected, 143+ tables, news articles exist, agent results exist |
| Services (2) | tradeai-continuous active, portfolio-server check |
| State Files (3) | holdings.json, enrichment cache, dividend calendar all <24h old |
| Screener Config (2) | Both screener URLs use `/export` not `.ashx` |
| Data Sync (2) | Aegis value matches overview, header GO matches Trade AI |
| Trade AI Runner (1) | Latest run has tickers, GO count valid |
| Stop Integrity (1) | Stops have real prices (not $0) |

---

## Backup System (v2.34)

### Weekly Full Backup

**`scripts/full_system_backup.py`** — creates single dated zip with everything needed for bare-metal restore:

| What | Included |
|---|---|
| Database | Full PostgreSQL dump (143 tables, ~3.8 MB compressed) |
| .env | API keys + passwords (+ sanitized version with keys masked) |
| Crontab | Full crontab (~46 active entries) |
| OpenClaw | Gateway config, cron jobs, Steph + Aegis SOULs |
| Systemd | 21 service/timer files |
| Configs | screeners.yaml, agent YAML |
| Launchers | 14 shell scripts |
| State files | holdings, enrichment, dividends, risk, stops, retirement |
| Docs | All Bible versions + Restore Guide |
| Restore instructions | 13-step bare-metal guide embedded in zip |

**Schedule:**
- Weekly full zip: Sunday 1 AM → `docs/backups/trade_ai_backup_YYYYMMDD.zip` (keeps 4 weeks)
- Daily DB dump: 2 AM → `backups/db/trade_ai_YYYYMMDD.sql.gz` (keeps 7 days)
- Archive cleanup: Sunday 3 AM → delete archived garbage older than 7 days

**Output:** `docs/backups/trade_ai_backup_20260429.zip` (3.8 MB, 70 files)

### Restore from Backup

See `docs/RESTORE_GUIDE.md` or `RESTORE_FROM_THIS_BACKUP.md` inside the zip.
13 steps: clone → .env → venv → DB restore → crontab → OpenClaw → systemd → configs → launchers → state → services → UI build → preflight verify.

---

## Garbage Cleanup (v2.34)

| Cleaned | Count | Action |
|---|---|---|
| Script .bak files | 55 files (78K lines) | Archived 7 days → auto-delete |
| Old dist backup dirs | 3 dirs (2 MB) | Archived |
| OpenClaw .json.bak files | 10 files | Archived |
| portfolio_server.log | 42 MB → 50 KB | Truncated to last 1000 lines |
| Empty .log files | 11 files | Deleted |
| __pycache__ dirs | 226 dirs | Deleted |
| **Total recovered** | **~43 MB immediate** | **17 MB in archive (7-day auto-delete)** |

---

**v2.40 — Automated YouTube backfill: 37 channels processing 50 videos each (~1,850 total) every 4 hours until complete. Rate limit detection + cooldown + auto-retry. Retirement/SSDI channels first. State tracked in DB. ~3 days to full 12-month coverage. Maturity: 74%.**

---

## Qualified Intelligence Pipeline (v2.40)

### How It Works

```
RAW DATA (552 news, 12 YouTube, 4 SEC, 3 social)
  ↓ scored + tagged (content_scoring.py)
  ↓
QUALIFIED INTELLIGENCE (agent_watchlist_engine.py — daily 7 PM)
  Promotion criteria:
    News: relevance_score ≥ 0.7
    YouTube: quality_score ≥ 70 AND ai_validated
    SEC Form 4: all filings (inherently high-value)
  Currently: 14 qualified items (8 news, 4 SEC, 2 YouTube)
  ↓
WATCHLIST PROPOSALS (auto-generated)
  Symbols in qualified intel but NOT on watchlist
  Require 2+ mentions across sources
  Status: 'proposed' (needs human approval)
  ↓
DISCOVERY SUMMARY (daily Telegram)
  "What I Discovered Today" — top items + pending proposals
  Stored in agent_discovery_log
```

### What Alex Now Sees (v2.40)

```
QUALIFIED INTELLIGENCE (high-confidence verified):
  [news] Q:83 [RETIREMENT] How To Use 3 Retirement Accounts To Pay No Taxes
  [sec] Q:80 Form 4: VISA INC. insider transaction
  [youtube] Q:70 When Individual Bonds Make Sense
SEC FORM 4 + YFINANCE + ALPHA VANTAGE + YOUTUBE (structured) + NEWS + OUTCOME FEEDBACK + CROSS-AGENT
```

### Rotation Rules (v2.41 — strategy-aware)

| Strategy | Auto-Rotate? | Rule |
|---|---|---|
| dividend_growth_compounder | **NEVER** | HOLD unless dividend cut or payout unsafe |
| high_yield_income_bdc | **NEVER** | HOLD unless income floor threatened (>20% of income) |
| tactical_income | **NEVER** | HOLD unless yield drops below 4% |
| reit_income | **NEVER** | HOLD unless occupancy collapse |
| bond_income | **NEVER** | HOLD unless duration mismatch |
| swing_trade | YES | Rotate on RSI >75 or <25 + catalyst exhaustion |
| core_growth_compounder | YES | Rotate if PE >40 AND growth decelerating |
| retirement_planning | **NEVER** | Alex reviews: Roth ladder, tax bracket, SSDI impact |
| disability_retirement_planning | **NEVER** | Alex reviews: Medicaid, IRMAA, MFS implications |

**Protection**: Income and retirement assets are NEVER auto-rotated. Only swing/growth positions get rotation proposals, and even those require human approval.

### Weekly Retirement Health Check (Sunday 10 AM)

Claude-powered deep analysis:
1. Income gap progress (on track?)
2. Roth conversion pace (ahead/behind?)
3. Tax bracket room remaining
4. SSDI/disability considerations
5. Medicaid planning status
6. Top 3 actions for next week

Stored in `ai_reports` (type='weekly_health') + `agent_discovery_log` + Telegram

### Autonomous Engine Schedule

| Job | Schedule | What It Does |
|---|---|---|
| Promote qualified intel | Daily 7 PM | Scan news/YouTube/SEC → promote Q≥70 to qualified_intelligence |
| Propose watchlist adds | Daily 7 PM | Symbols in qualified intel not on watchlist → proposals |
| Propose rotations | Daily 7 PM | Check positions against strategy rotation rules |
| Discovery summary | Daily 7 PM | "What I Discovered Today" → Telegram + DB |
| Weekly health check | Sunday 10 AM | Deep retirement/disability check → Telegram + AI reports |

### DB Tables

| Table | Purpose | Records |
|---|---|---|
| `qualified_intelligence` | High-Q items from all sources | 14 |
| `watchlist_proposals` | Add/rotate proposals (human approval) | 6+ (per-account) |
| `agent_discovery_log` | Daily/weekly summaries | 2 |

---

## Account-Specific Rotation Proposals (v2.42)

### What Changed

`propose_rotations()` now generates **one proposal per account** instead of one per symbol. Each position held across multiple accounts gets separate proposals with SSDI-aware impact assessments.

### Proposal Fields

| Field | Purpose |
|---|---|
| `account_name` | Roth IRA, Rollover IRA, 401k, Taxable |
| `shares_to_sell` | Actual shares from holdings.json |
| `target_symbol` | What to rotate into (default: cash) |
| `review_date` | 14-day deadline for human review |
| `ssdi_impact` | none / conversion_taxable / capital_gains |
| `income_impact` | none / taxable_event |
| `irmaa_risk` | true if IRA/401k sale > $50K (could push MAGI up) |

### SSDI Impact Logic

| Account Type | SSDI Impact | IRMAA Risk |
|---|---|---|
| Roth IRA | none (tax-free) | false |
| Rollover IRA | conversion_taxable | true if > $50K |
| 401k | conversion_taxable | true if > $50K |
| Taxable | capital_gains | false |

### New API Endpoints (v2.42)

| Endpoint | Method | Description |
|---|---|---|
| `/api/v2/proposals` | GET | All proposals sorted by status (proposed first) |
| `/api/v2/proposals/decide` | POST | Approve/reject: `{id, decision: "approved"/"rejected"}` |
| `/api/v2/qualified-intelligence` | GET | Top 30 qualified intel items by quality |
| `/api/v2/discovery-log` | GET | Last 10 discovery summaries |

### Example Proposal Output

```
[rotate] SCHG in Roth IRA: 45 shares → cash. SSDI:none
[rotate] SCHG in Taxable: 120 shares → cash. SSDI:capital_gains
[rotate] SCHG in Rollover IRA: 200 shares → cash. IRMAA! SSDI:conversion_taxable
[rotate] TRP-LVAL in 401k: 85 shares → cash. IRMAA! SSDI:conversion_taxable
```

### Still Needed

- Brave Search: needs $5 credit top-up
- Social APIs: X ($100/mo) or StockTwits (free)
- GPU upgrade: qwen3:1.7b → 14b for better agent reasoning

---

## v2.43 — Config Sync + FRED Macro LIVE + Feedback Loop + Enhanced UI

### Hybrid YAML → DB Config System (Phase 1)

| Component | Detail |
|---|---|
| Script | `scripts/config_sync.py` — `--dry-run`, `--sync`, `--status` |
| Sources | `config/agents_data_sources.yaml`, `config/agents_sec_interaction.yaml`, `assets/screeners.yaml` |
| Tables | `agent_data_source_rules` (24 rows), `agent_sec_rules` (18 rows), `agent_intelligence_rules` (17 rows) |
| Behavior | Idempotent — INSERT ... ON CONFLICT DO UPDATE with changed_by + updated_at |

```
Agent Data Source Rules:
  Alex: 8 sources | Maria: 5 | Steph: 5 | Risk: 4 | Aegis: 2
Agent SEC Rules:
  Maria: 7 rules | Risk: 4 | Steph: 3 | Aegis: 3 | Alex: 1
Intelligence Rules:
  data_source: 6 | sec_agent: 5 | run_window: 4 | screener: 2
Total: 59 rules synced
```

### FRED Macro Data Pipeline — NOW LIVE

| Component | Detail |
|---|---|
| Script | `scripts/fred_data_ingest.py` (standalone wrapper) |
| Backend | `scripts/external_market_data_ingest.py` — `ingest_fred()` |
| Table | `fred_economic_series` (7 series: DFF, T10Y2Y, UNRATE, CPIAUCSL, VIXCLS, MORTGAGE30US, SP500) |
| Cron | Daily 6:30 AM weekdays |
| API | `/api/v2/macro-context` — returns formatted FRED context string |
| Agent injection | `get_macro_context()` auto-injected into every `get_intel_summary()` call |
| Status | **LIVE** — 7 series fetched, all agents receiving macro context |

**Live FRED Data (as of April 29, 2026):**
| Series | Value | Date |
|---|---|---|
| Federal Funds Rate (DFF) | 3.64% | 2026-04-28 |
| 10Y-2Y Yield Spread | 0.52 | 2026-04-28 |
| Unemployment (UNRATE) | 4.3% | 2026-03-01 |
| CPI (inflation) | 330.29 | 2026-03-01 |
| VIX | 17.83 | 2026-04-28 |
| 30Y Mortgage | 6.23% | 2026-04-23 |
| S&P 500 | 7,138.80 | 2026-04-28 |

```
CLI: python3 scripts/fred_data_ingest.py --test | --ingest | --context | --history [--days 90] | --status
```

### Human Feedback Loop (Phase 2)

| Component | Detail |
|---|---|
| Table | `agent_feedback_log` (proposal_id, symbol, decision, confidence_at_decision, confidence_adjustment) |
| Trigger | POST `/api/v2/proposals/decide` now auto-records feedback |
| Confidence adjustment | +0.05 per approval, -0.05 per rejection |
| Learning | `propose_rotations()` queries last 90 days of feedback to adjust future proposal confidence |
| API | `/api/v2/proposals/feedback` — returns feedback history + approval/rejection stats |

**Flow:**
```
Proposal created → User reviews on Retirement page → Approve/Reject
  → agent_feedback_log records decision + confidence adjustment
  → Next rotation cycle: adjusted confidence applied to same symbol/strategy
  → Repeatedly rejected symbols get lower confidence → less likely to be proposed
```

### Command Center Enhancements (Phase 3)

**Overview page:**
- Pending proposals widget (top 4 with SSDI/IRMAA badges, links to Retirement page)
- FRED macro context card (pre-formatted economic data)

**Retirement page:**
- Proposal decision history bar (approved vs rejected with approval rate bar)
- FRED macro economic context panel
- Existing approve/reject cards now include feedback recording

**Intelligence Sources page (added v2.42):**
- Qualified Intelligence tab (promoted high-quality items)
- Discovery Log tab (daily "What I Discovered" summaries)

### Enhanced Weekly Health Report (Phase 4)

| Field | v2.42 | v2.43 |
|---|---|---|
| Prompt length | 250 words | 300 words |
| Analysis points | 6 | 7 (added macro environment impact) |
| FRED context | Not included | Injected into prompt |
| Income data | Hardcoded | Live from dividend_calendar.json |
| Feedback stats | Not included | Human approval/rejection counts injected |
| Schedule | Sunday 10 AM | Sunday 10 AM (unchanged) |

### New API Endpoints (v2.43)

| Endpoint | Method | Description |
|---|---|---|
| `/api/v2/macro-context` | GET | FRED economic context string |
| `/api/v2/proposals/feedback` | GET | Feedback history + approval stats |

### New DB Tables (v2.43)

| Table | Purpose | Records |
|---|---|---|
| `agent_feedback_log` | Human approve/reject decisions with confidence adjustments | 0 (new) |
| `agent_data_source_rules` | YAML-synced agent data source configs | 24 |
| `agent_sec_rules` | YAML-synced SEC trigger rules per agent | 18 |
| `agent_intelligence_rules` | YAML-synced screener + data source + run window configs | 17 |

### Cron Additions (v2.43)

| Schedule | Script | What |
|---|---|---|
| 6:30 AM weekdays | `fred_data_ingest.py --ingest` | Daily FRED macro snapshot |

### OpenClaw Gateway

Fixed `xai:default` auth profile (removed invalid fields: model, api_key_env, base_url, note). Gateway restart confirmed.

---

## v2.44 — SSDI Rules + Auto-Execute + Proposal History Chart + Semantic Search

### Enhanced SSDI-Specific Rotation Rules (Phase 2)

| Check | Threshold | Action |
|---|---|---|
| **IRMAA projection** | MAGI + sale value > $103,000 (MFS) | irmaa_risk = true, warning appended |
| **MFS bracket ceiling** | MAGI + sale value > $94,300 (22% top) | income_impact = "bracket_jump" |
| **Medicaid 5-year lookback** | IRA distribution > $50,000 | Warning: large IRA distribution may affect lookback |
| **Capital gains MAGI** | Taxable sale est. gain pushes MAGI past IRMAA | irmaa_risk = true |
| **Roth IRA** | Always safe | ssdi_impact = "none", income_impact = "none" |

**Data sources for thresholds:**
- `personal_situation.json`: AGI, Roth YTD, bracket ceiling, SSDI annual
- Live MAGI calculation: base AGI + Roth conversions YTD + proposed sale value

### Auto-Execution Toggle (Phase 3)

| Setting | Value |
|---|---|
| Table | `agent_intelligence_rules` (rule_type='auto_execute', rule_key='low_risk') |
| Default | **DISABLED** (enabled: false) |
| Criteria | confidence ≥ 90%, ssdi_impact = "none", irmaa_risk = false, income_impact = "none" |
| Behavior | Auto-approves proposal + generates trade instruction. Logs only — no actual trade. |

**To enable:**
```sql
UPDATE agent_intelligence_rules
SET config = jsonb_set(config, '{enabled}', 'true')
WHERE rule_type = 'auto_execute' AND rule_key = 'low_risk';
```

### Trade Instructions (Phase 3)

| Field | Description |
|---|---|
| `trade_instructions` table | Generated on proposal approval (manual or auto) |
| Fields | proposal_id, symbol, action, account_name, shares, target_symbol, estimated_tax_impact, ssdi_note, irmaa_note |
| execution_type | "manual" (human-approved) or "auto_approved" (engine-approved) |
| instruction_text | Human-readable: "SELL 45 shares of SCHG in Roth IRA. Target: cash. No SSDI impact." |

### Proposal History Chart (Phase 1)

- `/api/v2/proposals/history` — 30-day daily breakdown of approved/rejected/proposed counts
- Stacked Bar chart on Retirement page using Chart.js
- Approval rate progress bar with percentage

### Semantic Search on Transcripts (Phase 4)

- YouTube queries now search `structured_json` (key_points, action_items, tickers_mentioned)
- New `search_transcripts(query)` function for topic-based transcript search
- `get_intel_for_symbol()` enhanced with summary + structured_json ILIKE matching

### New API Endpoints (v2.44)

| Endpoint | Method | Description |
|---|---|---|
| `/api/v2/proposals/history` | GET | 30-day daily breakdown for chart |
| `/api/v2/trade-instructions` | GET | Pending/executed trade instructions |

### New DB Table (v2.44)

| Table | Purpose | Records |
|---|---|---|
| `trade_instructions` | Actionable trade instructions from approved proposals | 0 (new) |

### Test Results (April 29, 2026)

| Test | Result |
|---|---|
| `config_sync.py --sync` | 59 rules synced (24 data source + 18 SEC + 18 intelligence) |
| `agent_watchlist_engine.py --test` | 14 qualified items, 4 proposals, discovery summary generated |
| `agent_watchlist_engine.py --daily` | Full pipeline: promote → propose → rotate → discover |
| `fred_data_ingest.py --test` | 7/7 FRED series live (Fed Rate 3.64%, VIX 17.83, SP500 7138.80) |
| `alex --analyze V --tax-advisor` | Full disability-aware analysis: Roth $43.7K + IRA $93.6K, IRMAA/Medicaid projections |
| `alex --roth-ladder` | 5-year projection: $126K converted, IRMAA Tier 1 starting 2028, Medicaid impact table |

---

## v2.45 — Retirement Timeline Chart Overhaul + FRED-Aware Projections

### Timeline Chart Fixes (Phase 1)

**Before (v2.44):** Y-axis showed "$1203K" for $1.2M values. Tooltips showed only `$1,203,691`.

**After (v2.45):**
- Y-axis: dynamic `$K` / `$M` formatting — `$1.2M`, `$5.3M`, `$8.5M`
- Tooltips show for each data point:

| Tooltip Field | Example |
|---|---|
| **Year & Age** | `2035 (Age 68)  ★ Golden Window Opens` |
| **Scenario** | `Base: $2,847,312` |
| **Rate assumption** | `Rate: 7.5% return (2.5% dividends + 5.0% growth)` |
| **YoY growth** | `YoY growth: +7.5% ($198,312)` |
| **Estimated dividends** | `Est. dividends: $71,183/yr` |
| **Milestone** | `★ Golden Window Opens — Disability Ends` |

- Milestone data points: larger (5px radius), white-bordered, highlighted
- Milestone annotations show base scenario projected value
- "Last updated" timestamp from `as_of` field

### FRED-Aware Projection Engine (Phase 2)

`portfolio_retirement.py` now reads FRED data to adjust return assumptions:

| FRED Condition | Rate Adjustment |
|---|---|
| Fed Funds Rate < 3.0% | +0.5% to base rate (low-rate equity boost) |
| Fed Funds Rate > 5.0% | -0.5% to base rate (high-rate drag) |
| Yield spread < 0 (inverted) | -1.0% to conservative (recession risk) |
| Normal conditions (3-5%, positive spread) | No adjustment (use defaults) |

**Current state (April 29, 2026):** DFF=3.64%, T10Y2Y=0.52 → normal range → rates unchanged at 5.5%/7.5%/9.6%

**Output JSON now includes:**
```json
"rate_assumptions": {
  "conservative": 0.055,
  "base": 0.075,
  "aggressive": 0.096,
  "fred_adjusted": false
}
```

### Update Frequency

| Trigger | What Updates |
|---|---|
| Portfolio pipeline (daily) | `retirement_roadmap.json` regenerated via `portfolio_orchestrator.py` |
| FRED daily 6:30 AM | Macro data refreshed → next roadmap generation uses latest rates |
| Manual: `build_retirement_roadmap()` | Can be called anytime with latest holdings |

### SSDI-Aware Retirement Projections

| Scenario | Assumes |
|---|---|
| Conservative (5.5%) | SSDI continues, minimal Roth conversions, 401k stays put |
| Base (7.5%) | Moderate Roth ladder ($25K/yr pre-golden, $50K/yr in golden window) |
| Aggressive (9.6%) | Full bracket-filling conversions, disability exemption utilized |
| All scenarios | $7,000/yr Roth contribution, disability penalty exemption, MFS filing |

### Milestone Markers

| Age | Year | Event |
|---|---|---|
| 59 | 2026 | No early withdrawal penalty |
| 67 | 2034 | SS Retirement @ FRA |
| 68.5 | 2036 | Golden Window Opens — Disability Ends |
| 73 | 2040 | RMD Age — Complete Roth Conversion |

---

## v2.46 — Monthly Performance Report + Agent Autonomy + Learning Loop

### Monthly Retirement Performance Report (Phase 1)

| Component | Detail |
|---|---|
| Function | `monthly_retirement_report()` in `alex_retirement_advisor.py` |
| CLI | `--monthly-report [--telegram]` |
| Telegram | `monthly report` command |
| Cron | 1st of month, 9 AM |
| Storage | `ai_reports` table (report_type='monthly_retirement') |

**Report contents (LLM-generated, ~400 words):**
1. YTD actual vs 3 scenarios (Conservative/Base/Aggressive) — which are we tracking?
2. Monthly trend (Jan–current month) — best/worst months
3. Rest of 2026 needed — required return to hit base scenario
4. Income gap analysis — $40K+ gap, progress, what closes it
5. 3-5 actionable suggestions (SSDI/Medicaid/IRMAA aware, specific $ amounts)

### Agent Autonomy Enhancements (Phase 2)

#### 1. Automated Outcome Evaluation

| Component | Detail |
|---|---|
| Function | `evaluate_past_decisions()` in `overnight_batch.py` |
| Schedule | Daily 5:30 AM weekdays |
| What it does | Scores past decisions at 7d using current market prices |
| Output | Updates `decision_outcomes.price_7d` + `outcome_score` |
| Learning | Extracts top 3 lessons → stores in `agent_intelligence_rules` (rule_type='outcome_lessons') |
| Injection | `intel_query.py` auto-injects lessons into every agent prompt |

**How the learning loop works:**
```
Agent makes recommendation → decision_outcomes recorded
  ↓ (7 days later)
outcome_eval checks: was the recommendation CORRECT or WRONG?
  ↓
Top 3 lessons extracted and stored in agent_intelligence_rules
  ↓
intel_query.py injects "OUTCOME LESSONS (learn from these):" into every agent prompt
  ↓
Agents see: "V: BUY at $295 → $311 (+5.4%) [CORRECT]"
  ↓
Future analysis is informed by past accuracy
```

#### 2. Proactive Intel Scan

| Component | Detail |
|---|---|
| Function | `proactive_intel_scan()` in `overnight_batch.py` |
| Schedule | Daily 6:45 AM weekdays |
| Criteria | qualified_intelligence Q≥75, last 24h, not already in agent queue |
| Action | Auto-queues symbols for full agent chain analysis |
| Limit | 5 symbols per scan |

#### 3. FRED-Aware Rotation Proposals

Rotation decisions now include macro context from FRED:
- **VIX > 25** → `[MACRO: VIX elevated — consider holding]`
- **Yield curve inverted** (T10Y2Y < 0) → `[MACRO: Recession risk]`
- **Fed rate > 5%** → `[MACRO: Bonds competitive]`

Context is appended to every rotation proposal reason.

#### 4. Agent Health Widget (Overview page)

| Field | Source |
|---|---|
| Per-agent confidence bar | `watchlist_agent_results` (30-day avg) |
| Total analyses count | `watchlist_agent_results` |
| Escalations (7d) | `agent_handoffs` (escalated=TRUE) |
| Pending proposals | `watchlist_proposals` (status='proposed') |
| Outcome accuracy | `decision_outcomes` (correct vs wrong, 30d) |

API: `/api/v2/agent-health`

### Telegram Commands (v2.46)

| Command | What |
|---|---|
| `monthly report` | Monthly retirement performance report |
| `alex V` | Full retirement analysis for V |
| `roth ladder` | 5-year Roth conversion ladder |
| `tax` | Current bracket + Roth room |
| `intel SCHD` | Recent intelligence for SCHD |
| `status` | Full system status |

### New Crons (v2.46)

| Schedule | Script | What |
|---|---|---|
| 5:30 AM weekdays | `overnight_batch.py --outcomes` | Score past decisions + extract lessons |
| 6:45 AM weekdays | `overnight_batch.py --proactive` | Auto-queue high-Q symbols for agent analysis |
| 1st of month 9 AM | `alex_retirement_advisor.py --monthly-report --telegram` | Monthly retirement report |
