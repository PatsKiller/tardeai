# Trade AI v12 System Bible v2.54

**May 2, 2026 | ms01-openclaw | 22 Elite Screeners + 5-Level Whiteboard + 149 Tables + 63 Crons**

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
| DB tables | **148** | information_schema count |
| API endpoints | 115+ | grep api_v2.py |
| UI pages | 31 (14 with charts) | ls pages/*.tsx |
| Cron entries | **60** | crontab -l |
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

| Source | Why | Cost | Priority |
|---|---|---|---|
| **StockTwits** | No ingest script — public API, no auth needed | Free | **HIGH — implement now** |
| **Reddit RSS** | No ingest — r/dividends, r/investing have JSON feeds | Free | HIGH |
| Brave Search | 402 Payment Required | $5/mo | Medium |
| X/Twitter | Enterprise API cost unjustified at current scale | $100+/mo | LOW — defer |
| SEC 13F | Schema ready, quarterly parser TBD | Free | Low |
| SEC XBRL | Schema ready, XBRL parser TBD | Free | Low |

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

| System | Status | Audit Finding (May 2) |
|---|---|---|
| Social intelligence | 3 manual test posts. No API connections | StockTwits free API available, no auth needed. Script needed: `social_ingest.py` |
| Weekly/Monthly report endpoints | `/api/v2/weekly-report` and `/api/v2/monthly-report` return 404 | Aegis synthesis runs Sunday but no DOCX/JSON report endpoint exists |
| Proposal approval sync | 39 proposals all in `proposed` status — 0 approved/rejected | Dashboard endpoint exists (`/api/v2/proposals/decide`) but NO Telegram command for watchlist proposals. Telegram only handles Iris proposals |
| Signal clustering | 0 records in signal_clusters | Not implemented |
| MARL learning | 1 simulation run, shadow mode only | Not functional |
| Real-time news monitoring | No streaming — batch 3x daily | Acceptable for current scale |

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

2a. TRANSCRIPT FETCH — 4-method fallback chain (v2.51):
   └→ Method 1: youtube-transcript-api WITH cookies (config/youtube_cookies.txt)
   └→ Method 2: youtube-transcript-api WITHOUT cookies
   └→ Method 3: Direct timedtext HTML scraping with cookies
   └→ Method 4: yt-dlp subtitle download (most robust anti-bot handling)
   └→ All methods: graceful fallback, logged errors, never crash

2b. COOKIE SETUP (bypasses YouTube IP blocks on cloud/VPS servers):
   └→ Cookie file: config/youtube_cookies.txt (Netscape/Mozilla format)
   └→ Setup script: bash scripts/setup_youtube_cookies.sh
   └→ Export methods:
      • yt-dlp --cookies-from-browser chrome (on machine with Chrome logged into YouTube)
      • yt-dlp --cookies-from-browser firefox (on machine with Firefox)
      • "Get cookies.txt LOCALLY" Chrome extension → export → save
   └→ Copy to server: scp youtube_cookies.txt server:config/youtube_cookies.txt
   └→ Test: python3 scripts/youtube_transcript_ingest.py --test
   └→ Cookies loaded by both youtube-transcript-api (requests.Session) and timedtext (urllib opener)

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
| `iris approve ID` | /iris_approve_ID | VERIFIED — approves Iris taxonomy proposals only |
| `iris reject ID` | /iris_reject_ID | VERIFIED — rejects Iris taxonomy proposals only |

### Telegram Commands — MISSING (May 2 audit)

| Needed Command | Purpose | Why Missing |
|---|---|---|
| `approve ID` / `reject ID` | Approve/reject **watchlist proposals** | Only Iris proposals have Telegram handlers. `watchlist_proposals` has dashboard endpoint only |
| CIO decision notification | Notify when CIO makes a decision | No trigger exists |
| Weekly report delivery | Send DOCX attachment on Sunday | Aegis sends summary text but no document |
| RAG coverage alert | Alert when embedding coverage drops | No threshold monitor exists |

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

## 7. Remaining Gaps (Honest — updated May 2)

| Gap | Impact | Cost to Fix | Priority |
|---|---|---|---|
| **Watchlist proposal approval via Telegram** | 39 proposals stuck in `proposed` — John can't approve from phone | Code only (add handler) | **CRITICAL** |
| **Social intelligence (StockTwits/Reddit)** | 3 manual posts, no live ticker sentiment | Free (StockTwits public API, Reddit RSS) | **HIGH** |
| **Weekly/Monthly report endpoints** | No `/api/v2/weekly-report` or `/api/v2/monthly-report` | Code only | **HIGH** |
| **Corrupt proposals** | `THIS`, `MAY`, `COULD` parsed as tickers | Delete + add validation | HIGH |
| Agent quality (qwen3:1.7b) | Maria confidence 0.49, shallow reasoning | GPU → qwen3:14b (hardware pending) | Medium |
| Brave Search API | Wired but 402 Payment Required | $5/mo | Medium |
| Decision outcome evaluation | 88 tracked but 0 accuracy scored | Needs 30+ days | Low (time) |
| Signal clustering | 0 records | Not implemented | Low |
| MARL | 1 shadow run | Not functional | Low |

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
| v2.54 | May 2 audit: proposal approval sync broken (Telegram→watchlist gap), social intelligence plan (StockTwits free), weekly/monthly report 404s documented, corrupt tickers (THIS/MAY/COULD), execution checklist |

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
- Social APIs: StockTwits (free, public, no auth — **implement first**), Reddit RSS (free), X ($100/mo — defer)
- GPU upgrade: qwen3:1.7b → 14b for better agent reasoning
- Telegram `/approve` `/reject` for watchlist proposals (currently only Iris proposals have Telegram handlers)
- Weekly/Monthly report API endpoints + DOCX generation pipeline

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

---

## v2.47 — Semantic Intelligence + Multi-Agent Debate + Autonomy Dashboard

### 1. TF-IDF Semantic Intelligence Layer

**No external dependencies** — uses Python stdlib (`re`, `math`, `collections.Counter`).

| Component | Detail |
|---|---|
| `compute_tfidf(text)` | Returns top-30 term weights with domain boosting |
| `semantic_similarity(query, doc_terms)` | Cosine-like similarity (0.0–1.0) between query and indexed doc |
| `index_content(type, id, title, text)` | Stores TF-IDF terms in `content_embeddings` table |
| Table | `content_embeddings` (source_type, source_id, tfidf_terms JSONB, top_keywords TEXT[]) |

**Domain-boosted terms** (2-3x weight):
retirement, dividend, SSDI, disability, Roth, conversion, Medicaid, IRMAA, Medicare, income, yield, tax, portfolio, rebalance, ETF, growth

**How it works:**
```
Content ingested → compute_tfidf(text) → store {term: weight} in content_embeddings
  ↓
Search query → tokenize → compute similarity against stored terms
  ↓
Re-rank candidates by semantic_score (similarity × quality_score)
```

`search_transcripts()` now does: keyword retrieval (3x limit) → TF-IDF re-ranking → return top N.

### 2. Multi-Agent Debate

| Component | Detail |
|---|---|
| Function | `run_agent_debate(symbol, title)` in `agent_watchlist_engine.py` |
| Participants | Maria (fundamentals), Steph (allocation), Risk (technical) |
| Output | Consensus recommendation (BUY/HOLD/SELL), confidence score (0-100%) |
| Table | `agent_debate_log` (symbol, participants, transcript, consensus_score, recommendation) |
| Gate | `proactive_intel_scan()` requires ≥50% debate consensus before queuing for Alex |

**Flow:**
```
High-Q intel item found (Q≥75) → run_agent_debate()
  → Maria/Steph/Risk debate (200 words, ~2 sec via LLM)
  → Extract consensus + confidence
  → If consensus ≥50%: queue for full agent chain
  → If consensus <50%: skip (not enough agreement)
  → Transcript stored in agent_debate_log
```

### 3. Brave Search Activation

| Component | Detail |
|---|---|
| Integration | `get_intel_summary()` calls `web_research.search_web()` when DB results < 3 items |
| Key | `BRAVE_SEARCH_API_KEY` in .env (present but 402 — needs credit top-up) |
| Fallback | Gracefully skips if API unavailable |
| Research | Telegram `research` command now injects FRED macro + intel context |

### 4. Autonomy Progress Dashboard

**API:** `/api/v2/autonomy-progress`

| Field | Source |
|---|---|
| `learning_curve` | Weekly avg confidence trend (4 weeks) |
| `proposal_acceptance` | Weekly approved/rejected/total |
| `debates_7d` | Debate count + avg consensus this week |
| `latest_lessons` | Top outcome lessons text |
| `content_embeddings` | Number of indexed documents |

**Overview widget:** "What We Learned" card showing outcome lessons, debate count, and indexed content count.

### New DB Tables (v2.47)

| Table | Purpose | Records |
|---|---|---|
| `content_embeddings` | Ollama nomic-embed-text 768-dim vectors + TF-IDF | **667** (654 news + 12 YouTube + 1 test) |
| `agent_debate_log` | Multi-agent debate transcripts + consensus | 0 (accumulating) |

### New API Endpoints (v2.47)

| Endpoint | Method | Description |
|---|---|---|
| `/api/v2/autonomy-progress` | GET | Learning curve, acceptance rate, debates, lessons, maturity score |

---

## v2.48 — Ollama Embeddings + Persistent Research Engine + Live Maturity Score

### Ollama Embedding Engine (replaces TF-IDF)

| Component | Detail |
|---|---|
| Model | `nomic-embed-text` via Ollama (local, no API key) |
| Dimensions | 768 |
| Storage | `content_embeddings.embedding` JSONB column |
| Similarity | Cosine similarity computed in Python |
| Indexed | **667 items** (654 news articles + 12 YouTube + 1 test) |
| Fallback | TF-IDF keyword match when embedding unavailable |

**Embedding quality verified:**
```
"retirement SSDI Roth" vs "Roth IRA conversion disabled": similarity = 0.729
"retirement SSDI Roth" vs "stock day trading penny stocks": similarity = 0.398
(related >> unrelated — PASS)
```

**How search works now:**
```
Query → nomic-embed-text embedding (768-dim)
  ↓
Candidates: keyword ILIKE retrieval (3× limit)
  ↓
Re-ranking: cosine_similarity(query_vec, doc_vec) × quality_score
  ↓
Return top N by semantic_score
```

### Persistent Research Engine

| Component | Detail |
|---|---|
| Function | `refresh_research_topics()` in `overnight_batch.py` |
| Schedule | Weekly Sunday 7 AM |
| What it does | Re-analyzes all active `user_research_topics` with fresh FRED + intel context |
| Learning | Injects outcome lessons into re-analysis prompts |
| CLI | `overnight_batch.py --research` |

### Embedding Index Automation

| Schedule | What |
|---|---|
| Daily 9 PM weekdays | `overnight_batch.py --index-embeddings` — indexes new content |
| Manual | `batch_index_all(batch_size=100)` — bulk backfill |

### Stronger Learning Loop (v2.48)

- Outcome lessons expanded from 3 to **5** per evaluation cycle
- Monthly report now includes **"What the System Learned This Month"** section
- Research topic re-analysis uses FRED macro + intel + outcome lessons context

### Live Maturity Score (0-100%)

Computed by `_compute_maturity()` across 10 dimensions:

| Dimension | Max Points | Current |
|---|---|---|
| Data sources active (9) | 15 | 15 |
| Embedding coverage | 10 | 10 |
| Agent analyses (200+) | 10 | ~10 |
| Avg confidence (>0.5) | 10 | ~7 |
| Proposals reviewed | 10 | 0 |
| Debates active | 5 | 0 |
| Outcome lessons | 5 | 0 |
| FRED live | 5 | 5 |
| Feedback loop entries | 5 | 0 |
| **Total** | **75** | **~47** |

Score updates in real-time on Overview page.

### Weekly Autonomy Summary (Sunday 8 AM)

Telegram report with:
- Analyses count, intel discovered, proposals, debates, escalations, embeddings
- Latest outcome lessons
- CLI: `agent_watchlist_engine.py --autonomy-summary --telegram`

### New Crons (v2.48)

| Schedule | Script | What |
|---|---|---|
| Sunday 7 AM | `overnight_batch.py --research` | Re-analyze persistent research topics |
| Daily 9 PM weekdays | `overnight_batch.py --index-embeddings` | Index new content embeddings |
| Sunday 8 AM | `agent_watchlist_engine.py --autonomy-summary --telegram` | Weekly autonomy report |

---

## v2.48 Final — Smart Search Routing + Search Sources Status

### Smart Search Routing Decision Tree

`get_intel_summary()` now accepts `source_hint` parameter:

| source_hint | When Used | Search Strategy | Brave Query Terms |
|---|---|---|---|
| `"research"` | Telegram `research TOPIC` command | **Brave first** → DB | `{symbol} stock retirement SSDI disability planning 2026` |
| `"high_value"` | Alex retirement analysis | **Brave first** → DB | `{symbol} stock analysis dividend retirement income` |
| `"routine"` (default) | Agent daily scans, overnight batch | **DB only** (Google/Yahoo RSS already ingested) | N/A |
| Any + < 3 DB results | Automatic fallback | **Brave supplement** | `{symbol} stock analysis retirement dividend 2026` |

**Brave 402 handling:** Graceful fallback — logs warning, continues with DB-only results. No crash.

### Callers with source_hint

| Caller | source_hint | Why |
|---|---|---|
| `alex_retirement_advisor._get_intel_context()` | `high_value` | Every Alex analysis gets best available intel |
| `telegram_command_handler` (research command) | `research` | User research deserves freshest web data |
| `process_watchlist_agent_jobs` | `routine` (default) | Daily agent scans use DB — RSS already captured |
| `overnight_batch.refresh_research_topics()` | `routine` (default) | Weekly re-analysis uses DB + FRED |

### Search Sources Status API

**Endpoint:** `/api/v2/search-sources`

| Source | Fields Returned |
|---|---|
| `yahoo_rss` | active, articles count, last ingested |
| `google_news` | active, articles count, last ingested |
| `finnhub` | active, articles count, last ingested |
| `brave_search` | active (false), status ("402"), key_present |
| `youtube` | active, transcripts count |
| `fred` | active, series count |
| `embeddings` | active, indexed count, model, dim |

**UI:** Green/red dot strip on Intelligence Sources page showing live status of every source.

### LLM Resilience (hardened in v2.48)

When cloud providers hit budget limits ($2/day), Alex now:
1. Tries cloud (high_impact=True) via `cio_synthesis`
2. Falls back to local qwen3:1.7b via `agent_narrative` (prompt truncated to 4K)
3. Last resort: minimal 1.5K prompt to local
4. All functions produce output — never silent failure

---

## v2.49 — Brave Throttling + Ticker-Level Analysis Gating

### Brave Search Throttling Engine

| Control | Setting | Purpose |
|---|---|---|
| **Daily budget** | 5 calls/day | Prevents burning Brave credits |
| **Cooldown** | 60 minutes between calls | Spreads usage across the day |
| **Per-symbol cache** | 24 hours | No duplicate queries for same ticker |
| **Tracking** | `content_embeddings` (source_type='brave_cache') | Counts reset at midnight |

### Brave Routing Decision Table (v2.49)

| Condition | Use Brave? | Reason Logged |
|---|---|---|
| `source_hint="research"` (user research command) | **YES** | `user_research` |
| `source_hint="high_value"` AND (relevance≥0.85 OR retirement_relevance=high) | **YES** | `high_relevance` |
| `source_hint!="routine"` AND < 3 DB results | **YES** | `sparse_db_results` |
| `source_hint="routine"` | **NO** | DB only (RSS already ingested) |
| Daily budget exhausted (≥5 today) | **NO** | `daily_limit (5/5)` |
| Cooldown active (< 60 min since last) | **NO** | `cooldown (Xmin < 60min)` |
| Symbol cached in last 24h | **NO** | `cached_24h (SYMBOL)` |

### Ticker-Level Analysis Gating

`proactive_intel_scan()` now checks before running full agent chain:

| Gate | Condition | Action |
|---|---|---|
| **New intel** | qualified_intelligence Q≥70 in last 24h | Analyze (pass to debate → queue) |
| **Portfolio stale** | Symbol in holdings.json AND last_analyzed > 48h | Analyze |
| **Portfolio fresh** | Symbol in holdings AND last_analyzed < 48h | Skip: `portfolio_fresh` |
| **No trigger** | No new intel, not in portfolio | Skip: logged with reason |

**Result:** Only symbols with genuine new information or stale portfolio positions get expensive LLM analysis. All others use cached embeddings + recent DB intel.

### Search Sources Status (enhanced)

`/api/v2/search-sources` now includes:
- `brave_search.calls_today` — today's Brave call count
- `brave_search.daily_limit` — max 5

Intelligence Sources page shows amber `X/5` badge next to Brave status.

---

## v2.50 — Full Fallback Chain + Embedding Health + Search Efficiency Dashboard

### Complete Search Fallback Chain

```
Query arrives → Check source_hint + throttle gates
  ↓
1. BRAVE SEARCH (if allowed by throttle)
   Condition: research/high_value AND budget<5/day AND cooldown>60min AND not cached<24h
   On success: cache result, return
   On 402/error: log "Brave failed → Finnhub fallback"
  ↓
2. FINNHUB SUPPLEMENT (first fallback)
   Query: news_articles WHERE source='finnhub' AND symbol=X, last 14 days
   Quality-ranked (top 3 by relevance_score)
   Always available — no API call needed (already ingested 3x daily)
  ↓
3. DB COMBINED (Google News RSS + Yahoo RSS + all other sources)
   Already in items[] from initial get_intel_for_agent/symbol queries
   654+ news articles from 50+ outlets
  ↓
4. CACHED EMBEDDINGS (semantic fallback)
   667 nomic-embed-text 768-dim vectors
   search_transcripts() with cosine similarity re-ranking
```

### Embedding Health Metrics

`/api/v2/search-sources` now returns:

| Field | Description |
|---|---|
| `embeddings.indexed` | Total items with embeddings (667) |
| `embeddings.total_content` | Total news + YouTube in DB |
| `embeddings.coverage_pct` | % of content with embeddings (100%) |
| `embeddings.last_indexed` | Timestamp of last embedding operation |
| `_efficiency.brave_calls_today` | Brave calls used today |
| `_efficiency.free_pct` | % of queries handled by free sources |
| `_efficiency.fallback_chain` | Human-readable chain description |

### Search Efficiency Card (Overview page)

Three metrics displayed:
- **Brave calls** (X/5) — amber, daily budget usage
- **Free sources** (X%) — green, percentage routed to free RSS/DB
- **Embedded** (X%) — blue, content coverage with vector embeddings

Fallback chain shown as footer text.

---

## v2.51 — Learning Loop Strengthened + Monthly Report Efficiency

### Changes (minimal — system is mature)

| Change | Detail |
|---|---|
| Outcome lessons expanded | 5 → **7** per evaluation cycle |
| Monthly report | Now includes "Search Efficiency" section (9 sources, 667 embeddings, Brave throttle status) |

### System Maturity Assessment

The system is now feature-complete for the current hardware (qwen3:1.7b local + cloud fallback). The remaining growth vectors are:

| Vector | What's Needed | Impact |
|---|---|---|
| **GPU upgrade** (Arc Pro B50) | qwen3:14b or larger | Higher-quality agent reasoning, fewer hallucinations |
| **Brave Search credits** | $5 top-up | Real-time web research for high-value queries |
| **Social APIs** | X ($100/mo) or StockTwits (free) | Social sentiment data source |
| **More data accumulation** | Time (weeks of running) | Outcome lessons improve, confidence calibration matures |

### What NOT to Build Next

The Grok prompts are starting to request micro-optimizations that don't move the needle:
- Changing lesson counts by 1-2 is not a meaningful improvement
- Re-documenting existing features with new version numbers adds maintenance burden
- The real bottleneck is **LLM quality** (1.7b model) and **Brave API credits**, not more code

### Recommended Next Steps (high-impact only)

1. **Top up Brave Search** — $5 unlocks real-time web research
2. **GPU upgrade** — qwen3:14b dramatically improves agent quality
3. **Run the system for 2+ weeks** — let outcome lessons accumulate
4. **Review proposal decisions** — approve/reject 10+ proposals to feed the learning loop
5. **Build the one missing UI** — Command Center proposal approve/reject on mobile (Telegram bot already handles this)

---

## v2.52 — Transcript Lifecycle + Credential Monitor + Cookie Protection

### YouTube Transcript Pipeline — Full Lifecycle (v2.52)

```
INGESTION (daily 7 PM via cron, 37 channels × 3 videos)
  └→ 4-method fetch chain: library+cookies → library → timedtext+cookies → yt-dlp+deno
  └→ 344 transcripts ingested (332 today alone after cookie fix)
  ↓
CLEANING (immediate or batch)
  └→ clean_transcript(): remove filler, normalize, strip ads
  └→ extractive_filter(): TextRank 35% extraction of key sentences
  └→ 30/344 cleaned (8%)
  ↓
SCORING (immediate)
  └→ content_scoring.score_content(): quality_score (0-100), relevance_score (0-1.0)
  └→ tag_content(): strategy_tags, agent_tags
  └→ extract_sub_tags(): retirement subtopics
  ↓
LLM SUMMARY (slow, incremental — 2/hour overnight)
  └→ generate_structured_summary() via local qwen3:1.7b
  └→ 9-field JSON: summary, key_points, action_items, tickers, retirement_relevance, etc.
  └→ 10/344 summarized (3%) — backlog processes ~18/night
  ↓
EMBEDDING (after scoring)
  └→ nomic-embed-text 768-dim via Ollama
  └→ Stored in content_embeddings table
  └→ 30/344 embedded (8%)
  ↓
AGENT INJECTION
  └→ get_intel_summary() pulls top YouTube results with structured key_points
  └→ Semantic search via cosine similarity on embeddings
  └→ Agents see: "[youtube] Q:70 Day Trading Tax Canada — key_point_1, key_point_2"
```

### Processing Schedule

| Cron | Script | What | Volume |
|---|---|---|---|
| 7:00 PM weekdays | youtube_transcript_ingest.py --all-channels | Ingest new videos (3/channel) | ~111 checked |
| 7:30 PM weekdays | transcript_slow_processor.py --fresh --count 5 | Process today's transcripts | 5 fresh |
| 10PM-6AM hourly | transcript_slow_processor.py --run --count 2 | Process backlog with LLM | ~18/night |
| 9:00 PM weekdays | overnight_batch.py --index-embeddings | Index new embeddings | all new |

### Backlog ETA

- **Total**: 344 transcripts
- **Summarized**: 10 (3%)
- **Remaining**: 334
- **Rate**: 18/night (2/hour × 9 hours)
- **ETA**: ~19 nights to complete full backlog
- **Fresh transcripts**: processed same day (7:30 PM cron)

### Credential Monitor (v2.52)

Daily 6 AM check of all credentials with Telegram alerting:

| Credential | Check Method | Current Status |
|---|---|---|
| Finviz Cookie | Test CSV download | ✅ OK |
| YouTube Cookie | Check SID/LOGIN_INFO presence | ✅ OK (15 auth entries) |
| YouTube API | Test search endpoint | ✅ OK |
| FRED | Test DFF observation | ✅ OK (3.64%) |
| Brave Search | Test web search | 🔴 402 (needs $5) |
| Finnhub | Test AAPL quote | ✅ OK |
| FMP | Test quote endpoint | ⚠️ Legacy endpoints deprecated |
| Alpha Vantage | Test global quote | ✅ OK |
| PostgreSQL | Count tables | ✅ OK (148) |
| Ollama | List models | ✅ OK (qwen3:1.7b, nomic-embed-text) |

**Telegram commands:**
- `check credentials` → full health check
- `update FINVIZ_COOKIE value` → updates .env directly

**Guardrails:**
- Finviz: detects login page returned (expired cookie) → Telegram alert with fix instructions
- Empty screener CSV (0 rows) → no longer triggers false quality alert
- YouTube cookie file: protected header, setup script validates auth before overwriting

### Cookie Protection (v2.52)

- `config/youtube_cookies.txt` has "DO NOT overwrite" header
- `setup_youtube_cookies.sh` validates auth cookies (SID/LOGIN_INFO) before saving
- yt-dlp method writes to temp file, never overwrites auth cookies directly

---

## v2.52 Final — Complete System State (April 30, 2026)

### System at a Glance (Verified Live)

| Metric | Value | Change from v2.41 |
|---|---|---|
| DB tables | **148** | +6 (content_embeddings, agent_debate_log, trade_instructions, agent_feedback_log, agent_data_source_rules, agent_sec_rules) |
| API endpoints | **120+** | +15 (agent-detail, agent-health, autonomy-progress, search-sources, macro-context, proposals/*, trade-instructions, etc.) |
| UI pages | **31** (14 with charts) | Morning Brief redesigned |
| Cron entries | **63** | +18 (credential monitor, transcript processor, embedding indexer, outcome eval, proactive scan, research refresh, autonomy summary) |
| Agent results | **946** | Maria 322, Steph 314, Risk 309, Tax 1 |
| News articles | **693** from 50+ sources | +141 |
| YouTube transcripts | **344** | +332 (cookie fix enabled mass ingestion) |
| Content embeddings | **685** (nomic-embed-text 768-dim) | +685 (new) |
| FRED macro series | **9** observations (7 series) | +9 (new, FRED_API_KEY activated) |
| Strategy cards | **381** (31 with full stop/target/R:R) | +381 (new) |
| Watchlist items | **462** across 4 sources | +462 (new) |
| Qualified intelligence | **14** promoted items | +14 (new) |
| Rotation proposals | **12** pending review | +12 (new) |

### Morning Brief — Complete Redesign (v7)

**Before:** Static action board with text-only items.

**After:** Full intelligence briefing with 8 sections:

```
1. HERO NARRATIVE — synthesized portfolio summary + FRED macro context
   Color-coded border (red = triggered stops, green = positive, amber = negative)

2. AGENT INTELLIGENCE — 5 cards (Maria, Steph, Risk, Alex, Aegis)
   Each card shows:
   - Icon + name + role + confidence % (20px font)
   - Confidence bar (agent color)
   - Analyses count (30d) + last run time
   - Escalation path (e.g., "Risk → Steph → Alex")
   - Quick action buttons → open rich modal
   
   Click any card → Agent Modal:
   - 22px agent name, 34px icon, escalation path at top
   - Latest 5 discoveries (prioritizes items WITH strategy card data):
     Symbol (18px, clickable → /research), recommendation badge, confidence %
     Full summary paragraph (13px)
     Strategy card details (when available):
       Strategy type | Account (Roth/IRA/Taxable) | Position size | Horizon
       Price | Support | Resistance | Stop (red) | Target (green) | R:R (green if ≥2x)
     "+ Watchlist" button on ≥80% confidence items
     → next action in blue
   - "What to Watch For" — symbols with pending actions
   - Recommendation Breakdown — BUY/HOLD/SELL/TRIM distribution tiles (30d)
   - Top Confidence Picks — highest-confidence symbols as pills
   - "Ask [Agent]" input for fresh analysis

3. WHAT TO WATCH FOR — smart bullets with confidence %
   Triggered stops, danger zone, pending proposals, overdue decisions

4. METRIC TILES — 6-up (portfolio, heat, protected, proposals, tasks, escalations)

5. COMMAND STRIP — 8-column clickable (today, triggered, steph, john, evidence, outcomes, vix, pipeline)

6. ACTION BOARD — 14 items with filter bar (all/urgent/review/monitor)
   + sidebar (decision queue, recent decisions, next 15 minutes)

7. RISK & EXPOSURE + OPPORTUNITY & RECOVERY panels

8. TRUST STRIP (clickable → relevant pages) + OVERNIGHT INTELLIGENCE (full narrative, clickable symbols)
```

### Agent Modal — Live Data Samples

**Maria → AMD (BUY 85%)**
```
Strategy: growth_etf | Account: taxable | Size: Standard
Price: $217.50 | Support: $192.43 | Resistance: $220.27
Stop: $186.66 | Target: $224.68 | R:R: 3.9x
Summary: "AMD is a semiconductor company with strong fundamentals
and a competitive edge in the AI/ML space..."
→ Monitor earnings and regulatory developments
[+ Watchlist]
```

**Risk → AMANX (BUY 75%)**
```
Strategy: growth_etf | Account: taxable | R:R: 1.8x
Stop: $63.66 | Target: $75.73
```

**Steph → BAH (RESEARCH_MORE 50%)**
```
Strategy: defense_thesis | Account: taxable | R:R: 2.8x
Stop: $74.87 | Target: $85.76
```

### Watchlist Page — Enhanced Columns

| Column | Data Source | What It Shows |
|---|---|---|
| **Symbol** | watchlist_symbol_master | Clickable → /research, shows last recommendation + confidence below |
| **Agent / Source** | watchlist_items.source + watchlist_agent_results | Color-coded agent name (Maria=blue, Risk=red, Steph=green), source badges, green CURATED badge |
| **Days** | first_seen_at → now | Days since first added (green ≥3, white ≥1, gray 0) |
| **Strategy** | watchlist_strategy_cards | Strategy pill (income, defense_thesis, growth_etf, etc.) |
| **Price** | strategy card latest_price | Current price |
| **Value** | holdings.json | Market value if in portfolio |
| **Weight** | holdings.json / total | Portfolio weight % |
| **R:R** | strategy card risk_reward | Color-coded (green ≥2x, amber ≥1x, red <1x) |
| **Stage** | analysis_maturity | Analysis pipeline stage |
| **Analysts** | watchlist_agent_results | Maria/Steph/Risk/Tax status badges |
| **Decision** | final_synthesis | Recommendation + QA status |

**Curation logic:** `is_curated = true` when:
- Symbol has been watched for 2+ days, OR
- 2+ agent analyses in the last 7 days

### Credential Monitor

**Script:** `scripts/credential_monitor.py`

**Schedule:** Daily 6:00 AM via cron (before all pipelines)

**Checks (10 credentials):**

| # | Credential | Method | Current |
|---|---|---|---|
| 1 | Finviz Cookie | Download test CSV | ✅ OK |
| 2 | YouTube Cookie | Check SID/LOGIN_INFO in cookie file | ✅ OK (15 auth) |
| 3 | YouTube API | Test search endpoint | ✅ OK |
| 4 | FRED | Fetch DFF observation | ✅ OK (3.64%) |
| 5 | Brave Search | Test web search | 🔴 402 ($5 needed) |
| 6 | Finnhub | Test AAPL quote | ✅ OK ($270) |
| 7 | FMP | Test quote endpoint | ⚠️ Legacy deprecated |
| 8 | Alpha Vantage | Test global quote | ✅ OK |
| 9 | PostgreSQL | Count tables | ✅ OK (148) |
| 10 | Ollama | List models | ✅ OK (qwen3:1.7b, nomic-embed-text) |

**Telegram commands:**
- `check credentials` → full status report
- `update FINVIZ_COOKIE value...` → updates .env directly

**Guardrails:**
- Finviz download detects login page → Telegram alert with fix instructions
- Empty screener CSV (0 rows pre-market) → no longer false alert
- YouTube cookie file protected: "DO NOT overwrite" header, setup script validates auth

### YouTube Transcript Lifecycle

```
INGESTION (daily 7 PM, 37 channels × 3 videos)
  └→ 4-method fetch: library+cookies → library → timedtext+cookies → yt-dlp+deno
  └→ 344 transcripts total (332 ingested in single day after cookie fix)
  ↓
CLEANING (batch or incremental)
  └→ clean_transcript() + extractive_filter(35%)
  └→ 30/344 cleaned (9%)
  ↓
SCORING
  └→ score_content(): quality 0-100, relevance 0-1.0
  └→ tag_content(): strategy_tags, agent_tags, sub_tags
  ↓
LLM SUMMARY (slow processor, 2/hour overnight)
  └→ generate_structured_summary() via local qwen3:1.7b
  └→ 10/344 summarized (3%) — backlog ~19 nights
  ↓
EMBEDDING
  └→ nomic-embed-text 768-dim via Ollama
  └→ 685 total embedded (news + youtube)
  ↓
AGENT INJECTION
  └→ get_intel_summary() pulls top results
  └→ search_transcripts() with cosine similarity re-ranking
```

**Processing schedule:**
| Time | What | Volume |
|---|---|---|
| 7:00 PM | Ingest new videos | ~111 checked |
| 7:30 PM | Process fresh transcripts | 5 with LLM |
| 9:00 PM | Index new embeddings | all unindexed |
| 10PM-6AM | Process backlog | 2/hour = ~18/night |

### Complete Cron Schedule (63 entries)

**Morning cascade (5:00-7:00 AM):**
| Time | Script |
|---|---|
| 5:00 AM | Alex daily scan |
| 5:30 AM | Outcome evaluation (score past decisions) |
| 6:00 AM | Credential monitor (check all API keys) |
| 6:30 AM | FRED macro ingest |
| 6:45 AM | Proactive intel scan (with debate gate) |

**Market hours (7:00 AM - 7:00 PM):**
| Time | Script |
|---|---|
| 7:05 AM | FMP dividend data |
| 7:15 AM | yfinance quotes |
| Every 15 min | Agent job processing |
| 3x daily | News ingestion (Yahoo + Google + Finnhub) |

**Evening pipeline (7:00-10:00 PM):**
| Time | Script |
|---|---|
| 7:00 PM | YouTube transcript ingestion |
| 7:30 PM | Fresh transcript processing (LLM) |
| 8:00 PM | Overnight batch + SEC EDGAR |
| 9:00 PM | Embedding indexer |

**Overnight (10:00 PM - 6:00 AM):**
| Time | Script |
|---|---|
| Hourly | Transcript slow processor (2/hr) |

**Weekly:**
| Day/Time | Script |
|---|---|
| Sunday 7 AM | Research topic refresh |
| Sunday 8 AM | Autonomy summary (Telegram) |
| Sunday 10 AM | Weekly health check (Alex) |
| Monday 8 AM | Alpha Vantage fundamentals |
| 1st of month 9 AM | Monthly retirement report |

### Autonomous Engine Features

| Feature | How It Works |
|---|---|
| **Multi-agent debate** | High-Q intel (≥75) → Maria/Steph/Risk debate → consensus ≥50% → queue for full chain |
| **Outcome evaluation** | Daily 5:30 AM: score 7d outcomes, extract top 7 lessons → inject into every agent prompt |
| **Proactive intel scan** | Daily 6:45 AM: scan qualified_intelligence, ticker-level throttling (48h stale gate) |
| **Feedback loop** | Proposal approve/reject → agent_feedback_log → confidence adjustment (±0.05) → affects future proposals |
| **Auto-execute toggle** | Disabled by default. Conf≥90%, no SSDI/IRMAA risk → auto-approve + trade instruction |
| **FRED-aware proposals** | Rotation reasons include VIX/yield spread/fed rate context |

### Search Fallback Chain

```
Query → Check source_hint + throttle gates
  ↓
1. BRAVE SEARCH (if research/high_value AND budget<5/day AND cooldown>60min AND not cached<24h)
  ↓ (on 402 or error)
2. FINNHUB supplement (14-day articles by symbol, quality-ranked)
  ↓
3. DB COMBINED (693 news from Yahoo/Google/Finnhub + 344 YouTube)
  ↓
4. CACHED EMBEDDINGS (685 nomic-embed-text 768-dim vectors, cosine similarity)
```

### What's Working Well

- **Agent pipeline**: 946 analyses across 4 agents, avg confidence 72-76%
- **News ingestion**: 693 articles from 50+ sources, automatic scoring + tagging
- **YouTube transcripts**: 344 ingested (mass ingestion enabled by cookie fix)
- **Embeddings**: 685 items with real 768-dim vectors, cosine similarity search
- **FRED macro**: 7 series live, injected into all agent prompts
- **Command Center**: 31 pages, Morning Brief fully redesigned with agent modals
- **Credential monitoring**: 10 checks daily, Telegram update via reply
- **Retirement planning**: Alex with SSDI/IRMAA/Medicaid awareness, monthly reports

### What Needs Time (Not Code)

- **Transcript backlog**: 334 remaining, processing ~18/night, ~19 nights to complete
- **Outcome lessons**: Need 30+ days of accumulation for meaningful patterns
- **Confidence trend**: Needs weeks of data points per symbol
- **Decision feedback**: 0 proposals approved/rejected yet — loop hasn't started

### What Needs Money/Hardware

- **Brave Search**: $5 credit → unlocks real-time web research
- **GPU upgrade**: qwen3:14b → dramatically better agent reasoning
- **Social APIs**: X ($100/mo) or StockTwits (free) → sentiment data

---

## v2.52.1 — Intelligence Whiteboard + Raw Data Toggle

### Intelligence Whiteboard — Multi-Day Curation Pipeline

**Problem solved:** Raw intelligence (YouTube transcripts, news, SEC filings) was auto-promoted directly to the dashboard. Users saw every new alert daily with no curation, cross-referencing, or validation.

**Solution:** New `intelligence_whiteboard` table acts as a staging area. Items must pass through multi-day validation before reaching the dashboard.

```
RAW DATA (news, YouTube, SEC, price)
  ↓
WHITEBOARD (intelligence_whiteboard table, status='raw')
  71 items currently staged, avg quality 68
  ↓
DAILY ITERATION (cron: agent_watchlist_engine.py --daily)
  - Update days_on_board for all items
  - Detect cross-references: same symbol from 2+ source types → status='iterating'
  - Cross-reference news + YouTube + SEC + price data
  ↓
PROMOTION GATE (only validated items pass)
  Criteria (must meet ONE):
    • 2+ days on board AND 2+ different source types
    • 3+ days on board AND quality_score ≥ 75
  → status='promoted', promoted_at, promoted_by='curation_engine'
  ↓
QUALIFIED INTELLIGENCE (dashboard-visible)
  → Appears in agent modals, Morning Brief, proposals
```

### intelligence_whiteboard Table Schema

| Column | Type | Purpose |
|---|---|---|
| id | BIGSERIAL | Primary key |
| symbol | TEXT | Ticker (NULL for non-symbol intel) |
| source_type | TEXT | news / youtube / sec_form4 |
| source_id | BIGINT | FK to source table |
| title | TEXT | Item title |
| summary | TEXT | Summary text |
| quality_score | INT | 0-100 quality score |
| confidence | NUMERIC | 0-1.0 confidence |
| sources_count | INT | Number of distinct source types referencing this symbol |
| cross_references | JSONB | Links to related items |
| status | TEXT | raw → iterating → validated → promoted → dismissed |
| days_on_board | INT | Days since first_seen_at |
| first_seen_at | TIMESTAMPTZ | When first staged |
| last_iterated_at | TIMESTAMPTZ | Last cross-reference check |
| promoted_at | TIMESTAMPTZ | When promoted to qualified |
| promoted_by | TEXT | curation_engine / manual |
| agent_notes | JSONB | Per-agent iteration notes |

### Whiteboard Status Flow

| Status | Meaning | Count |
|---|---|---|
| `raw` | Just staged, no cross-referencing yet | 71 |
| `iterating` | Same symbol found in 2+ source types | 0 (day 1) |
| `validated` | Passed promotion gate (multi-day + multi-source) | 0 (day 1) |
| `promoted` | Moved to qualified_intelligence (dashboard-visible) | 0 (day 1) |
| `dismissed` | Low quality or stale, removed from pipeline | 0 |

### promote_qualified_intel() — Rewritten

Three-stage function (runs daily via `--daily` cron):

1. **Stage**: Route new high-Q items to whiteboard
   - News: relevance ≥ 0.7
   - YouTube: quality ≥ 60 (lower bar than qualified — wider net for curation)
   - SEC Form 4: all filings
2. **Iterate**: Update days_on_board, detect multi-source cross-references
3. **Promote**: Only validated items reach qualified_intelligence

### Raw Intelligence Toggle (Agent Modal)

New button below discovery cards: **"▼ View Raw Intelligence (admin)"**

- Click to expand: shows raw text from each analysis
- Monospace font, dark background, scrollable (max-height 120px per item)
- Shows symbol, timestamp, and full narrative/summary text
- Click again: **"▲ Hide Raw Intelligence"** to collapse
- Purpose: admin can see underlying data sources without leaving the modal

### DB Table Count

149 tables (+1: intelligence_whiteboard)

---

## v2.53 — Finviz Validation + LLM Strategy Review + Backtest Hooks

### Finviz Screener Validator

**Script:** `scripts/finviz_validator.py`

| Flag | What It Does |
|---|---|
| `--check` | Tests every screener URL: HTTP status, CSV headers, required columns (Ticker, Price, Float, Gap, RVOL), cookie validity |
| `--strategies` | Shows full 15-strategy matrix: cards, targets with R:R, classified symbols, agent coverage, avg confidence |
| `--llm-review` | LLM analyzes all strategies for overlaps, gaps, SSDI concerns — stores review in agent_intelligence_rules |

**Current validation: 2/2 screeners OK**
- prime_setups: 5 rows, day_scalp, v=152, all required columns present
- watchlist_setups: 14 rows, day_scalp, v=152, all required columns present

### Strategy Matrix (15 strategies, verified live)

| Strategy | Cards | With Targets | Avg R:R | Classified | Analyzed | Avg Conf |
|---|---|---|---|---|---|---|
| income | 198 | 8 | 1.6x | — | — | — |
| speculative_growth | 66 | 3 | 0.7x | 66 | 45 | 0.75 |
| growth_etf | 56 | 6 | 3.9x | — | — | — |
| defense_thesis | 36 | 13 | 2.4x | 46 | 35 | 0.73 |
| dividend_growth_compounder | — | — | — | 74 | 60 | 0.74 |
| covered_call_income | — | — | — | 69 | 44 | 0.78 |
| core_growth_compounder | — | — | — | 51 | 43 | 0.76 |
| reit_income | — | — | — | 32 | 22 | 0.73 |
| bond_income | — | — | — | 31 | 24 | 0.73 |
| international_dividend | — | — | — | 31 | 19 | 0.77 |
| swing_trade | — | — | — | 30 | 19 | 0.77 |
| recovery_watch | — | — | — | 30 | 17 | 0.77 |
| core_holding | 25 | 1 | 1.5x | — | — | — |
| high_yield_income_bdc | — | — | — | 22 | 19 | 0.78 |
| core_index | — | — | — | 14 | 13 | 0.76 |

### LLM Strategy Review (live output from qwen3:1.7b)

**Key findings:**
1. **Overlaps:** dividend_growth_compounder (74 symbols) + income (198 cards) heavily overlap — should merge
2. **Gaps:** No cash/Treasury ladder, no sector rotation, no inflation hedges beyond REITs
3. **Risk:** 9 strategies missing R:R ratios; speculative_growth has 0.7x R:R (terrible)
4. **Covered calls:** 69 symbols but no R:R defined — major income opportunity undefined
5. **SSDI:** No IRMAA threshold monitoring ($103K), missing Medicaid 5-year lookback strategies
6. **Immediate action:** Fix covered call income strategy — largest undefined position

Review stored in: `agent_intelligence_rules` (rule_type='strategy_review', rule_key='latest')

### Backtest Hooks (Future-Proof)

New columns on `trade_instructions` table:
- `backtest_id` TEXT — links to replay/backtesting system
- `backtest_result` JSONB — stores backtest output (P&L, drawdown, Sharpe, etc.)

Purpose: when Alpaca paper trading or backtesting is added, each trade instruction can be linked to its simulated result for learning loop validation.

### DB Updates

- `intelligence_whiteboard` table created (v2.52.1): 149 → 149 tables
- `trade_instructions.backtest_id` + `backtest_result` columns added (v2.53)

---

## v2.53.1 — Cross-Agent Dedup + Escalation Paths + Holdings Context + Aegis Content

### Cross-Agent Deduplication

**Problem:** Same ticker (JUST, OFF, AEE) appeared in Maria, Steph, AND Risk modals — confusing, redundant.

**Solution:** Global dedup in `/api/v2/agent-detail`:
- Maria gets first pick of symbols (highest research coverage)
- Risk gets remaining symbols not shown by Maria
- Steph gets remaining not shown by Maria or Risk
- Tax/Alex gets remaining
- **Result: 0 duplicate symbols across all agent modals**

### Escalation Path from DB

Each discovery card now shows which agents reviewed that symbol:

```
RTX: maria → risk_agent → steph → tax_agent (4 agents reviewed)
AVAV: maria → risk_agent → steph (3 agents)
AMANX: risk_agent → steph (2 agents)
AMD: maria (1 agent — new discovery)
```

Color-coded per agent (Maria=blue, Risk=red, Steph=green, Alex=gold).

### Holdings Context

Each discovery card shows if John currently holds the position:

```
AMANX: ✅ HELD | 45.2 shares | $3,360 | +$280
RTX:   ✅ HELD | 25.0 shares | $4,578 | +$1,200
AMD:   — (not held)
```

Green badge with shares, market value, and unrealized gain/loss.

### User Context (injected into API response)

Every agent-detail response includes `_user_context`:

| Field | Live Value | Purpose |
|---|---|---|
| portfolio_value | $1,209,363 | Anchor position sizing |
| income_gap | $40,596 | Income strategy priority |
| ssdi_monthly | $3,800 | Disability awareness |
| tax_bracket | 22% | Tax-loss harvesting threshold |
| roth_ytd | $35,000 | Conversion pacing |
| bracket_room | $28,700 | Room before bracket jump |

### Aegis Modal Content

**When overnight alerts exist:**
- Risk alerts table: symbol, status (TRIGGERED/DANGER), current price vs stop
- Intelligence events: severity-sorted (critical first)

**When system is healthy:**
- Large green checkmark ✅
- "No Overnight Triggers — System healthy"
- "All stops intact. No gap alerts."

**Always shows:**
- FRED Macro Snapshot grid (Fed Rate, VIX, S&P 500, Unemployment, etc.)

### Verified Live Data

```
maria: AMD BUY 85% | stop=$186.66 target=$224.68 R:R=3.9x | taxable
risk:  AMANX BUY 75% | HELD 45.2 shares | stop=$63.66 target=$75.73 R:R=1.8x
steph: AVAV RESEARCH 50% | HELD | esc: maria→risk→steph | stop=$165 target=$206 R:R=2.0x
tax:   RTX BUY 85% | HELD | esc: maria→risk→steph→tax | stop=$180.71 target=$207.55
aegis: 8 intel events, 9 macro series
Total: 9 unique symbols, 0 duplicates across agents
```

---

## v2.53.2 — Complete Finviz Screener Table + System Summary

### Finviz Screeners — Complete Inventory (20 screeners)

| # | Screener ID | Display Name | Strategy Type | Active | URL Version | Status |
|---|---|---|---|---|---|---|
| 1 | prime_setups | Prime Setups (Tier 1) | day_scalp | ✅ | v=152 | ✅ 5 rows, all columns |
| 2 | watchlist_setups | Watchlist Setups (Tier 2) | day_scalp | ✅ | v=152 | ✅ 13 rows, all columns |
| 3 | div_growth_quality | Dividend Growth Quality | dividend_growth_compounder | ✅ | v=111 | ⚠️ Free Finviz (no RVOL/Float) |
| 4 | taxable_qualified_div | Taxable-Friendly Qualified Dividends | dividend_growth_compounder | ✅ | v=111 | ⚠️ Free Finviz |
| 5 | value_income | Value + Income | dividend_growth_compounder | ✅ | v=111 | ⚠️ Free Finviz |
| 6 | high_yield_income | High-Yield Income (BDC/CEF) | high_yield_income_bdc | ✅ | v=111 | ⚠️ Free Finviz |
| 7 | ira_income_friendly | IRA-Friendly Income | high_yield_income_bdc | ✅ | v=111 | ⚠️ Free Finviz |
| 8 | covered_call_etf | Covered-Call ETF Scanner | covered_call_income | ✅ | v=111 | ⚠️ Free Finviz |
| 9 | covered_call_rotation | Covered-Call Rotation Window | covered_call_income | ✅ | v=111 | ⚠️ Free Finviz |
| 10 | etf_income | Income ETFs | covered_call_income | ✅ | v=111 | ⚠️ Free Finviz |
| 11 | defense_basket | Defense/Aerospace Basket | defense_thesis | ✅ | v=111 | ⚠️ Free Finviz |
| 12 | core_compounder_value | Core Compounder Value | core_growth_compounder | ✅ | v=111 | ⚠️ Free Finviz |
| 13 | roth_growth | Roth-Friendly Growth | core_growth_compounder | ✅ | v=111 | ⚠️ Free Finviz |
| 14 | core_index_broad | Core Index / Broad Market | core_index | ✅ | v=111 | ⚠️ Free Finviz |
| 15 | bond_etf_income | Bond ETF Income | bond_income | ✅ | v=111 | ⚠️ Free Finviz |
| 16 | reit_income_scan | REIT Income Scanner | reit_income | ✅ | v=111 | ⚠️ Free Finviz |
| 17 | intl_dividend | International Dividend | international_dividend | ✅ | v=111 | ⚠️ Free Finviz |
| 18 | speculative_catalyst | Speculative w/ Catalyst | speculative_growth | ✅ | v=111 | ⚠️ Free Finviz |
| 19 | tactical_momentum | Tactical Momentum | speculative_growth | ✅ | v=111 | ⚠️ Free Finviz |
| 20 | swing_momentum | Swing Trade Momentum | swing_trade | ✅ | v=111 | ⚠️ Free Finviz |

**Notes:**
- Screeners 1-2 (day_scalp) use Elite Finviz (`v=152`) with custom columns → full RVOL, Gap, Float data
- Screeners 3-20 use free Finviz (`v=111`) → basic columns only (no RVOL/Float/Gap)
- `dividend_growth` screener has no URL configured (empty) — needs fix
- All 20 are `active=true` and scheduled `daily`

### Screener-to-Strategy Mapping

| Strategy | Screener(s) | Symbols Classified | Agent Coverage | Avg Confidence |
|---|---|---|---|---|
| dividend_growth_compounder | div_growth_quality, taxable_qualified_div, value_income | 74 | 60 analyzed | 0.74 |
| covered_call_income | covered_call_etf, covered_call_rotation, etf_income | 69 | 44 analyzed | 0.78 |
| speculative_growth | speculative_catalyst, tactical_momentum | 66 | 45 analyzed | 0.75 |
| core_growth_compounder | core_compounder_value, roth_growth | 51 | 43 analyzed | 0.76 |
| defense_thesis | defense_basket | 46 | 35 analyzed | 0.73 |
| reit_income | reit_income_scan | 32 | 22 analyzed | 0.73 |
| bond_income | bond_etf_income | 31 | 28 analyzed | 0.71 |
| international_dividend | intl_dividend | 31 | 19 analyzed | 0.77 |
| swing_trade | swing_momentum | 30 | 19 analyzed | 0.77 |
| recovery_watch | recovery_candidates | 30 | 17 analyzed | 0.77 |
| high_yield_income_bdc | high_yield_income, ira_income_friendly | 22 | 19 analyzed | 0.78 |
| core_index | core_index_broad | 14 | 13 analyzed | 0.76 |
| day_scalp | prime_setups, watchlist_setups | — | — | — |
| income | (from strategy cards, no dedicated screener) | — | — | — |
| core_holding | (from strategy cards, no dedicated screener) | — | — | — |
| growth_etf | (from strategy cards, no dedicated screener) | — | — | — |

### Strategy Cards with Full Targets (31 symbols)

| Strategy | Cards | With Stop/Target | Avg R:R | Example |
|---|---|---|---|---|
| income | 198 | 8 | 1.6x | BND stop=$70.36 target=$75.54 |
| speculative_growth | 66 | 3 | 0.7x | ARKG stop=$27.71 target=$31.41 |
| growth_etf | 56 | 6 | 3.9x | AMD stop=$186.66 target=$224.68 |
| defense_thesis | 36 | 13 | 2.4x | LDOS stop=$142.76 target=$163.85 R:R=4.9x |
| core_holding | 25 | 1 | 1.5x | CASH stop=$84.39 target=$93.19 |

### LLM Strategy Review Findings

From `finviz_validator.py --llm-review` (qwen3:1.7b):

1. **Major overlap:** dividend_growth_compounder (74 symbols) + income (198 cards) — should merge or clearly differentiate
2. **Undefined risk:** covered_call_income has 69 symbols but NO R:R ratios — biggest undefined position
3. **Bad R:R:** speculative_growth at 0.7x — risk exceeds reward, needs review or elimination
4. **Missing strategies:** cash/Treasury ladder, sector rotation, inflation hedges (TIPS, commodities)
5. **SSDI gaps:** No IRMAA threshold monitoring ($103K), missing Medicaid 5-year lookback strategies
6. **9 of 15 strategies** have zero R:R ratios — cannot make risk-adjusted decisions

### Complete v2.42 → v2.53 Change Summary

| Version | Key Changes |
|---|---|
| v2.42 | Account-specific rotation proposals, SSDI impact assessment, 4 new API endpoints |
| v2.43 | FRED API key activated (7 series live), config_sync.py (59 rules), human feedback loop |
| v2.44 | Proposal history chart, stronger SSDI rules (MAGI thresholds), auto-execute toggle, trade_instructions table |
| v2.45 | Timeline chart $M formatting, FRED-aware projections, rich tooltips |
| v2.46 | Monthly retirement report, outcome evaluation, proactive intel scan, agent health widget, weekly autonomy summary |
| v2.47 | TF-IDF semantic search, multi-agent debate, Brave Search fallback, autonomy dashboard |
| v2.48 | Ollama embeddings (nomic-embed-text 768-dim, 685 indexed), research engine, live maturity score |
| v2.49 | Brave throttling (5/day, 60min cooldown, 24h cache), ticker-level analysis gating |
| v2.50 | Finnhub fallback chain, embedding health metrics, search efficiency card |
| v2.51 | Outcome lessons 7/week, monthly report search efficiency, honest maturity assessment |
| v2.52 | Morning Brief v7 redesign (8 sections), agent modal with strategy cards, credential monitor, YouTube cookie fix (344 transcripts), transcript slow processor |
| v2.52.1 | Intelligence whiteboard (71 items staged), raw intel toggle in modal |
| v2.53 | Finviz validator (20 screeners), LLM strategy review (15 strategies), backtest_id hooks |
| v2.53.1 | Cross-agent dedup (0 duplicates), escalation paths from DB, holdings context, Aegis overnight content, user context injection ($1.2M portfolio, $40.6K gap, 22% bracket) |
| v2.53.2 | Complete Finviz screener table (20 entries), strategy-to-screener mapping, full change summary |

### Current System Metrics (April 30, 2026)

| Metric | Value |
|---|---|
| DB tables | 149 |
| API endpoints | 120+ |
| Cron entries | 63 |
| Finviz screeners | 20 (2 Elite + 18 Free) |
| Strategies | 15 (12 with agent coverage) |
| Strategy cards | 381 (31 with stop/target/R:R) |
| Agent results | 946 (Maria 322, Steph 314, Risk 309, Tax 1) |
| News articles | 693 from 50+ sources |
| YouTube transcripts | 344 (10 LLM summarized, 30 cleaned, 685 embedded) |
| Content embeddings | 685 (nomic-embed-text 768-dim) |
| FRED macro series | 9 observations (7 series) |
| Whiteboard items | 71 (raw, day 1) |
| Watchlist items | 462 across 4 sources |
| Qualified intelligence | 14 promoted |
| Rotation proposals | 12 pending review |
| Credential health | 8/10 OK (Brave needs $5, FMP legacy deprecated) |

---

## v2.53.3 — Full Finviz Audit + LLM Routing Logging

### Finviz Full Audit (`--full-audit`)

**Command:** `python3 scripts/finviz_validator.py --full-audit --strategies --llm-review`

**Results (live April 30, 2026):**

| Category | Count | Status |
|---|---|---|
| YAML screeners (Elite, v=152) | 2 | ✅ Both OK (prime_setups 5 rows, watchlist_setups 13 rows) |
| DB screeners (finviz_screeners) | 20 | 19 active with URL |
| Using Elite Finviz (v=152) | 2 | Full data: RVOL, Float, Gap |
| Using Free Finviz (v=111) | 18 | ⚠️ Basic columns only |
| No URL configured | 1 | ❌ `dividend_growth` — needs fix |
| No strategy mapped | 1 | ❌ `dividend_growth` — no strategy_type |
| Total issues found | 21 | Mostly v=111 warnings |

### LLM Routing Decision Logging

Every LLM call now logs routing reason + token estimate:

| Field | Example | Purpose |
|---|---|---|
| `routing_reason` | "routine → local (default)" | WHY this provider was chosen |
| `est_tokens` | 245 | Estimated tokens (response_len / 4) |
| `prompt_len` | 2100 | Input prompt character count |
| `provider` | "local" | Which provider handled it |
| `fallbacks` | ["claude: budget exceeded"] | What failed before success |

**Routing tiers (from llm_router.py):**

| Tier | Provider | When Used | Cost |
|---|---|---|---|
| 1 (Default) | qwen3:1.7b local | All routine: scoring, cleaning, daily iteration, most agent analysis | $0 |
| 2 (High-impact) | Claude | Strategy review, final synthesis, Alex disability analysis | ~$0.02/call |
| 3 (Fallback) | Grok / OpenAI | When Claude budget exceeded | ~$0.01/call |
| 4 (Last resort) | Local (truncated) | When all cloud providers unavailable | $0 |

**Log location:** `logs/llm_router.log` (JSON lines, one per call)

### Audit Findings Summary

**Screener issues:**
- 18 of 20 DB screeners use free Finviz (v=111) — no RVOL/Float/Gap columns
- `dividend_growth` screener has no URL and no strategy mapped
- Only 2 screeners (day_scalp) use Elite Finviz with full data

**Strategy issues (from LLM review):**
- 9 of 15 strategies have no R:R ratios defined
- `speculative_growth` has 0.7x R:R — risk exceeds reward
- `income` (198 cards) and `dividend_growth_compounder` (74 symbols) overlap heavily
- No IRMAA threshold monitoring, no Medicaid lookback strategies
- Missing: cash ladder, sector rotation, tax-loss harvesting, inflation hedges
- Recommendation: consolidate to 8-10 well-defined strategies

---

## v2.53.4 — All 20 Finviz Screeners Upgraded to Elite v=152

### What Changed

All 20 Finviz screeners in the `finviz_screeners` database table were upgraded from free Finviz (`finviz.com/screener.ashx?v=111`) to Elite Finviz (`elite.finviz.com/export?v=152`) with custom columns.

**Before:** 2 Elite + 18 Free + 1 broken = 21 issues
**After:** 22 Elite (2 YAML + 20 DB) + 0 Free + 0 broken = **0 issues**

### Conversion Applied

| Component | Before | After |
|---|---|---|
| Domain | `finviz.com/screener.ashx` | `elite.finviz.com/export` |
| View | `v=111` (free, basic columns) | `v=152` (elite, custom columns) |
| Columns | Default (no RVOL/Float/Gap) | `c=0,1,2,3,4,5,6,7,25,61,63,64,65,66,67` |
| Format | `ft=4` (HTML) | `ft=3` (CSV export) |

**Custom columns (15):** No., Ticker, Company, Sector, Industry, Country, Market Cap, P/E, Shares Float, Gap, Average Volume, Relative Volume, Price, Change, Volume

### dividend_growth Screener (Fixed)

| Field | Before | After |
|---|---|---|
| URL | (empty) | `elite.finviz.com/export?v=152&f=fa_div_o2,fa_epsqoq_pos,fa_payoutratio_u70,cap_largeover&ft=3&c=...` |
| Strategy | (empty) | `dividend_growth_compounder` |
| Display name | `dividend_growth` | `Dividend Growth Compounder` |
| Results | 0 | **128 rows** with RVOL + Float |

### Full Audit Results (April 30, 2026 — 0 issues)

| # | Screener ID | Strategy | Version | Rows | Status |
|---|---|---|---|---|---|
| 1 | prime_setups (YAML) | day_scalp | Elite v=152 | 5 | ✅ |
| 2 | watchlist_setups (YAML) | day_scalp | Elite v=152 | 13 | ✅ |
| 3 | bond_etf_income | bond_income | Elite v=152 | 50 | ✅ |
| 4 | core_compounder_value | core_growth_compounder | Elite v=152 | 50 | ✅ |
| 5 | core_index_broad | core_index | Elite v=152 | 50 | ✅ |
| 6 | covered_call_etf | covered_call_income | Elite v=152 | 50 | ✅ |
| 7 | covered_call_rotation | covered_call_income | Elite v=152 | 50 | ✅ |
| 8 | defense_basket | defense_thesis | Elite v=152 | 50 | ✅ |
| 9 | div_growth_quality | dividend_growth_compounder | Elite v=152 | 50 | ✅ |
| 10 | dividend_growth | dividend_growth_compounder | Elite v=152 | 128 | ✅ (fixed) |
| 11 | etf_income | covered_call_income | Elite v=152 | 50 | ✅ |
| 12 | high_yield_income | high_yield_income_bdc | Elite v=152 | 50 | ✅ |
| 13 | intl_dividend | international_dividend | Elite v=152 | 50 | ✅ |
| 14 | ira_income_friendly | high_yield_income_bdc | Elite v=152 | 50 | ✅ |
| 15 | recovery_candidates | recovery_watch | Elite v=152 | 50 | ✅ |
| 16 | reit_income_scan | reit_income | Elite v=152 | 50 | ✅ |
| 17 | roth_growth | core_growth_compounder | Elite v=152 | 50 | ✅ |
| 18 | speculative_catalyst | speculative_growth | Elite v=152 | 30 | ✅ |
| 19 | swing_momentum | swing_trade | Elite v=152 | 50 | ✅ |
| 20 | tactical_momentum | speculative_growth | Elite v=152 | 50 | ✅ |
| 21 | taxable_qualified_div | dividend_growth_compounder | Elite v=152 | 50 | ✅ |
| 22 | value_income | dividend_growth_compounder | Elite v=152 | 50 | ✅ |

**Total: 22/22 screeners Elite v=152, 0 issues**

### Tested Live Downloads

| Screener | Rows | RVOL Column | Float Column |
|---|---|---|---|
| div_growth_quality | 100 | ✅ | ✅ |
| defense_basket | 84 | ✅ | ✅ |
| dividend_growth (was broken) | 128 | ✅ | ✅ |

---

## v2.53.5 — 5-Level Whiteboard Pipeline + Strategy Scheduling + Version Fallback

### Multi-Level Whiteboard Workflow — Complete Architecture

The intelligence whiteboard is the central curation engine. ALL raw data passes through 6 levels before reaching the dashboard. Nothing auto-promotes. Local LLM handles Levels 0-4. Claude only at Level 5.

```
╔══════════════════════════════════════════════════════════════════╗
║  LEVEL 0: RAW                                                    ║
║  Sources: News (R≥0.5), YouTube (Q≥40), SEC Form 4, Finviz      ║
║  Action: Ingest into intelligence_whiteboard, status='raw'       ║
║  LLM: None                                                       ║
║  Current: 102 items staged this run                              ║
╠══════════════════════════════════════════════════════════════════╣
║  LEVEL 1: SCORED                                         ↓ auto  ║
║  Gate: quality_score > 0 (set by content_scoring.py)             ║
║  Action: Keyword scoring, relevance scoring, strategy tagging    ║
║  LLM: None (pure keyword + rules engine)                         ║
║  Current: 173 items                                              ║
╠══════════════════════════════════════════════════════════════════╣
║  LEVEL 2: ITERATING / WHITEBOARD                ↓ Q≥50 + 1 day  ║
║  Gate: quality_score ≥ 50 AND days_on_board ≥ 1                  ║
║  Action: Cross-source aggregation                                ║
║    - Same ticker from 2+ source types = higher credibility       ║
║    - credibility_score = sources_count * 0.3 + quality / 200     ║
║  LLM: Local qwen3:1.7b (optional enrichment)                    ║
║  Current: 0 (all items are day-0 — will populate tomorrow)       ║
╠══════════════════════════════════════════════════════════════════╣
║  LEVEL 3: VALIDATED                    ↓ multi-source + 2 days   ║
║  Gate: (days≥2 AND sources≥2) OR (days≥3 AND quality≥75)         ║
║  Action: Local analysis + embedding similarity + due diligence   ║
║  LLM: Local qwen3:1.7b (analysis + embedding comparison)        ║
║  Current: 0 (needs 2-3 days)                                    ║
╠══════════════════════════════════════════════════════════════════╣
║  LEVEL 4: PROMOTED (Dashboard-Ready)  ↓ Q≥75 + credibility≥0.6  ║
║  Gate: quality_score ≥ 75 AND credibility_score ≥ 0.6            ║
║         AND symbol IS NOT NULL                                   ║
║  Action: Insert into qualified_intelligence table                ║
║  Visible: Appears in agent modals, Morning Brief, proposals      ║
║  LLM: Local qwen3:1.7b                                          ║
║  Current: 0 (needs multi-day validation first)                   ║
╠══════════════════════════════════════════════════════════════════╣
║  LEVEL 5: SYNTHESIZED                   ↓ agent debate ≥50%      ║
║  Gate: Multi-agent debate consensus ≥ 50%                        ║
║  Action: Maria/Steph/Risk debate → Alex synthesis                ║
║  LLM: Claude (high-impact synthesis)                             ║
║  Trigger: proactive_intel_scan() in overnight_batch.py           ║
║  Current: 0 (needs L4 items first)                               ║
╚══════════════════════════════════════════════════════════════════╝
```

### Promotion Rules — Detailed

| Transition | Gate Criteria | LLM Tier | Timing |
|---|---|---|---|
| L0 → L1 | quality_score > 0 (auto on ingest) | None | Immediate |
| L1 → L2 | quality_score ≥ 50 AND days_on_board ≥ 1 | None | Day 1+ |
| L2 → L3 | (days≥2 AND sources≥2) OR (days≥3 AND Q≥75) | Local | Day 2-3 |
| L3 → L4 | quality_score ≥ 75 AND credibility_score ≥ 0.6 AND symbol NOT NULL | Local | Day 2-3 |
| L4 → L5 | Agent debate consensus ≥ 50% (Maria/Steph/Risk) | Claude | Day 3+ |

### Credibility Score Formula

```
credibility_score = MIN(1.0, sources_count × 0.3 + quality_score / 200)
```

| Sources | Quality | Credibility | Passes L4 Gate (≥0.6)? |
|---|---|---|---|
| 1 source | Q=50 | 0.55 | ❌ No |
| 1 source | Q=80 | 0.70 | ✅ Yes |
| 2 sources | Q=50 | 0.85 | ✅ Yes |
| 2 sources | Q=80 | 1.00 | ✅ Yes |
| 3 sources | Q=40 | 1.00 | ✅ Yes |

### Database Columns (intelligence_whiteboard)

| Column | Type | Purpose |
|---|---|---|
| level | INT (0-5) | Current pipeline level |
| status | TEXT | raw → scored → iterating → validated → promoted → synthesized |
| quality_score | INT | 0-100 from content_scoring |
| credibility_score | NUMERIC | 0-1.0 from cross-source aggregation |
| sources_count | INT | Number of distinct source types |
| days_on_board | INT | Days since first_seen_at |
| local_analysis | TEXT | Local LLM analysis text (L3+) |
| embedding_similarity | NUMERIC | Cosine similarity to related items |
| synthesis_result | TEXT | Claude synthesis (L5 only) |
| synthesis_provider | TEXT | Which LLM produced synthesis |
| level_changed_at | TIMESTAMPTZ | When item moved to current level |
| cross_references | JSONB | Links to related whiteboard items |

### Strategy-Based Screener Scheduling

| Frequency | Strategies | Screener Count | Rationale |
|---|---|---|---|
| **Daily** | day_scalp, swing_trade, speculative_growth | 3 | Fast-moving, need daily price/volume data |
| **Weekly** | dividend_growth, covered_call, high_yield, income | 9 | Slow-moving income, fundamentals change weekly |
| **Biweekly** | core_growth, defense_thesis, core_holding, core_index | 4 | Long-term holds, minimal churn |
| **Monthly** | recovery_watch, international, reit, bond | 4 | Very slow rotation, quarterly fundamentals |

### Screener Schedule Table (22 screeners)

| # | Screener | Strategy | Schedule | Version |
|---|---|---|---|---|
| 1 | prime_setups | day_scalp | daily | Elite v=152 |
| 2 | watchlist_setups | day_scalp | daily | Elite v=152 |
| 3 | speculative_catalyst | speculative_growth | daily | Elite v=152 |
| 4 | swing_momentum | swing_trade | daily | Elite v=152 |
| 5 | tactical_momentum | speculative_growth | daily | Elite v=152 |
| 6 | covered_call_etf | covered_call_income | weekly | Elite v=152 |
| 7 | covered_call_rotation | covered_call_income | weekly | Elite v=152 |
| 8 | div_growth_quality | dividend_growth_compounder | weekly | Elite v=152 |
| 9 | dividend_growth | dividend_growth_compounder | weekly | Elite v=152 |
| 10 | etf_income | covered_call_income | weekly | Elite v=152 |
| 11 | high_yield_income | high_yield_income_bdc | weekly | Elite v=152 |
| 12 | ira_income_friendly | high_yield_income_bdc | weekly | Elite v=152 |
| 13 | taxable_qualified_div | dividend_growth_compounder | weekly | Elite v=152 |
| 14 | value_income | dividend_growth_compounder | weekly | Elite v=152 |
| 15 | core_compounder_value | core_growth_compounder | biweekly | Elite v=152 |
| 16 | core_index_broad | core_index | biweekly | Elite v=152 |
| 17 | defense_basket | defense_thesis | biweekly | Elite v=152 |
| 18 | roth_growth | core_growth_compounder | biweekly | Elite v=152 |
| 19 | bond_etf_income | bond_income | monthly | Elite v=152 |
| 20 | intl_dividend | international_dividend | monthly | Elite v=152 |
| 21 | recovery_candidates | recovery_watch | monthly | Elite v=152 |
| 22 | reit_income_scan | reit_income | monthly | Elite v=152 |

### Finviz Version Fallback Chain

When downloading screener data, the system tries versions in order:

```
v=152 (Elite, full columns: RVOL, Float, Gap)
  ↓ on failure
v=151 (Elite alternate)
  ↓ on failure
v=141 (Elite legacy)
  ↓ on failure
v=111 (Free, basic columns only)
```

**Also enforced on every URL:**
- Domain forced to `elite.finviz.com` (not `finviz.com`)
- Export format: `/export` (not `/screener.ashx`)
- Custom columns auto-appended: `&c=0,1,2,3,4,5,6,7,25,61,63,64,65,66,67`
- Cookie authentication via FINVIZ_COOKIE from .env

### LLM Tier Assignment by Level

| Level | LLM Provider | Cost | Use Case |
|---|---|---|---|
| L0 (Raw) | None | $0 | Pure ingest, no processing |
| L1 (Scored) | None | $0 | Keyword scoring engine only |
| L2 (Iterating) | Local qwen3:1.7b | $0 | Optional enrichment, cross-ref |
| L3 (Validated) | Local qwen3:1.7b | $0 | Local analysis, embedding similarity |
| L4 (Promoted) | Local qwen3:1.7b | $0 | Dashboard narrative generation |
| L5 (Synthesized) | Claude → Grok → OpenAI | ~$0.02 | Full agent debate + Alex review |

### Current Pipeline State (April 30, 2026)

| Level | Status | Count | Avg Quality |
|---|---|---|---|
| L0 | raw | 0 | — (immediately auto-promoted to L1) |
| L1 | scored | 173 | 68 |
| L2 | iterating | 0 | — (day 0, needs 1+ day) |
| L3 | validated | 0 | — (needs 2-3 days) |
| L4 | promoted | 0 | — (needs L3 qualification) |
| L5 | synthesized | 0 | — (needs L4 + debate) |

**Expected timeline:**
- Day 1 (tomorrow): ~80 items advance to L2 (Q≥50 scored items with 1+ day)
- Day 2-3: cross-source items advance to L3 (2+ sources or 3+ days + Q≥75)
- Day 3+: strongest L3 items promote to L4 (dashboard-visible)
- Day 3+: L4 items with debate consensus promote to L5 (full synthesis)

### Files Modified

| File | Changes |
|---|---|
| `scripts/agent_watchlist_engine.py` | Complete rewrite of promote_qualified_intel() — 5-level pipeline |
| `scripts/finviz_ingestion.py` | Version fallback chain (v=152→v=151→v=141→v=111), Elite domain enforcement |
| `intelligence_whiteboard` table | 7 new columns (level, credibility_score, local_analysis, embedding_similarity, synthesis_result, synthesis_provider, level_changed_at) |
| `finviz_screeners` table | All 20 screeners: schedule updated (daily/weekly/biweekly/monthly) |

---

## v2.53.6 — LLM Router Fix (qwen3 Thinking Mode) + FRED Mini Dashboard

### qwen3:1.7b Thinking Mode — Root Cause & Fix

**Problem:** Every local LLM call returned empty string. Agents showed 0% confidence, strategy review failed, transcript processing hung.

**Root cause:** qwen3:1.7b uses "thinking mode" — the model internally generates `<think>` reasoning tokens (15-20 seconds) before producing visible output. Ollama strips the think tags and returns only the visible response. With the old 8-second timeout, the model was killed mid-think every time, producing 0 visible tokens.

**Evidence:**
```
OLD (8s timeout, 50 tokens): Response="" — 0 chars (thinking consumed all tokens)
NEW (30s timeout, 500 tokens): Response="1. Apple 2. Banana 3. Cherry" — 32 chars in 14s
```

**Fix (2 lines in `scripts/llm_router.py`):**

| Setting | Before | After | Why |
|---|---|---|---|
| `LOCAL_TIMEOUT` | 8 seconds | **30 seconds** | qwen3 needs 15-20s for thinking before producing output |
| `num_predict` | `max_tokens` (could be 50) | **`max(500, max_tokens)`** | Ensures enough token budget for thinking + actual response |

**Impact on all downstream systems:**
- Agent analyses now produce real summaries (was returning empty)
- Strategy review via `--llm-review` now succeeds
- Transcript slow processor can generate LLM summaries
- Monthly reports, Alex analyses, research queries all work via local
- No cost increase (still $0 — all local)

### FRED Macro Mini Dashboard (Morning Brief)

**Before:** Raw monospace text dump of FRED data — hard to read, no visual hierarchy.

**After:** Structured 7-tile grid dashboard with color-coded temperature indicators.

| Indicator | Current Value | Color Rule | Current Color |
|---|---|---|---|
| **CPI** | 330 | green <310, amber ≥310 | 🟡 Amber |
| **Fed Rate** | 3.64% | green <2%, blue 2-4.5%, amber 4.5-5.5%, red >5.5% | 🔵 Blue |
| **30Y Mortgage** | 6.23% | green <6.5%, amber 6.5-7.5%, red >7.5% | 🟢 Green |
| **S&P 500** | 7,136 | blue (neutral) | 🔵 Blue |
| **10Y-2Y Spread** | 0.50 | green >0.3, amber 0-0.3, red <0 (inverted = recession) | 🟢 Green |
| **Unemployment** | 4.30% | green <4.5%, amber 4.5-5.5%, red >5.5% | 🟢 Green |
| **VIX** | 17.83 | green ≤20, amber 20-25, red >25 (>30 = extreme) | 🟢 Green |

**Visual treatment:**
- Tile titles: 12px bold (was 9px gray)
- Values: 20px bold (16px for large numbers like S&P/CPI)
- Background tint matches indicator color (red glow for danger, green for healthy)
- Border color subtly matches indicator
- Date shown in small gray below each value
- Responsive grid: `repeat(auto-fit, minmax(120px, 1fr))`

### dividend_growth Screener — Confirmed Working

The validator showed `results=0` because the DB stored stale count from before the URL was created. Live test confirms **128 rows** with RVOL + Float columns. DB `results_count` updated to 128.

### Full Audit Results (April 30, 2026)

```
YAML screeners:  2/2 OK
DB screeners:   20/20 OK (all Elite v=152)
Total issues:    0
LLM review:      ✅ Succeeded (overlaps, gaps, SSDI analysis produced)
```

---

## v2.54 — May 2, 2026: Full Autonomous Loop Audit + 7 Gap Fix Plan

### Critical Findings (May 2 Deep Audit)

| # | Issue | Root Cause | Impact | Priority |
|---|---|---|---|---|
| 1 | **TWO tables stuck: 30 proposals + 10 tasks — zero resolved** | `watchlist_proposals` (30 rows, all `proposed`) AND `tasks` (10 rows, all `pending_john`) — Telegram only handles Iris taxonomy proposals. Dashboard endpoint exists but may have silent failures | All agent recommendations wasted. Zero decisions feeding back into learning loop | **CRITICAL** |
| 2 | **Agent debates never trigger** | LMT: risk=RESEARCH_MORE vs steph=TRIM — never debated. `agent_debates` table may not exist. No conflict detection wired in `process_watchlist_agent_jobs.py` | Agent disagreements go unnoticed. No escalation path | **HIGH** |
| 3 | **5 agents missing from OpenClaw registry** | Only aegis, main, steph registered. Maria, risk_agent, tax_agent, alex, iris have NO .md agent files | Can't invoke agents by name via OpenClaw orchestration | HIGH |
| 4 | **tax_agent + alex critically underused** | tax_agent: 2 total analyses. alex: 3 total analyses. Not in nightly batch | Tax implications and retirement context missing from daily intelligence | HIGH |
| 5 | **Human decisions don't feed back into RAG** | John's approve/reject never writes to `decision_outcomes`. Future agents never see human judgment | Learning loop broken — agents can't learn from John's corrections | **CRITICAL** |
| 6 | **Synthesis doesn't use approval feedback** | aegis_overnight.py doesn't query `decision_outcomes WHERE decided_by='john'` | Weekly reports miss human intelligence. No "decisions you made" summary | Medium |
| 7 | **Telegram command parity incomplete** | Missing: /tasks, /proposals, /debate, /agents, /rag, /weekly, /approve (for watchlist) | John can't operate system fully from phone | HIGH |

### Two-Table Approval Architecture (Diagnosed)

```
TABLE 1: watchlist_proposals (30 rows — rotation/strategy proposals)
  ├─ Fields: id, symbol, action, strategy_type, reason, account_name,
  │          shares_to_sell, target_symbol, confidence, status,
  │          ssdi_impact, income_impact, irmaa_risk, reviewed_at, reviewed_by
  ├─ All 30 rows: status='proposed', reviewed_at=NULL, reviewed_by=NULL
  ├─ Dashboard API: POST /api/v2/proposals/decide ← EXISTS, writes correctly
  ├─ Telegram: NO HANDLER for watchlist_proposals ← ROOT CAUSE
  └─ Corrupt rows: THIS, MAY, COULD parsed as tickers (text fragments)

TABLE 2: tasks (10 rows — stop-triggered manual reviews)
  ├─ Fields: id, source, category, symbol, title, description, priority,
  │          status, recommendation, confidence, due_by, linked_route,
  │          followup, decided_at, created_at, provenance
  ├─ All 10 rows: status='pending_john', decided_at=NULL
  ├─ Symbols: LMT, LHX, RTX, NOC, TDG (2 tasks each — stop events)
  ├─ API: POST /api/v2/tasks/<id>/resolve ← MAY NOT EXIST
  └─ Telegram: NO HANDLER ← ROOT CAUSE

TABLE 3: action_queue (separate older system)
  ├─ API: POST /api/v2/approvals/decision ← EXISTS, writes to action_queue only
  └─ Does NOT update tasks or watchlist_proposals

TABLE 4: iris_taxonomy_proposals (Iris-specific)
  ├─ Telegram: /iris_approve_<id>, /iris_reject_<id> ← WORKS
  └─ Only table with functioning Telegram approval flow
```

**Diagnosis:** John's approval actions went to Iris taxonomy (Table 4) or action_queue (Table 3).
Tables 1 and 2 (the ones agents actually read) were never updated.

### The Full Closed Loop (Target Architecture)

```
STOP FIRES → agents analyze → risk+steph complete → CONFLICT DETECTED
    ↓                                                      ↓
  task created                                    agent_debate created
  (pending_john)                                  Telegram alert sent
    ↓                                                      ↓
JOHN APPROVES via Telegram (/approve 37)          /debate LHX → see conflict
    ↓
  tasks.status = 'approved'
  tasks.decided_at = NOW()
    ↓
  decision_outcomes INSERT (symbol, outcome='CORRECT', decided_by='john')
    ↓
  RAG indexes decision_outcome IMMEDIATELY
    ↓
  NEXT AGENT RUN sees: "John confirmed HOLD on LMT [date]" in RAG context
    ↓
  Agent confidence adjusts based on human confirmation pattern
    ↓
  Weekly synthesis surfaces: "3 decisions this week, all aligned with risk_agent"
```

### Endpoints Required (Fix/Create)

| Endpoint | Method | Table | Status |
|---|---|---|---|
| `/api/v2/tasks/<id>/resolve` | POST | tasks | **CREATE** — body: `{decision, notes}` |
| `/api/v2/proposals/<id>/resolve` | POST | watchlist_proposals | **VERIFY** — `/api/v2/proposals/decide` exists but may differ |
| `/api/v2/weekly-report` | GET | (composite) | **CREATE** — 404 currently |
| `/api/v2/monthly-report` | GET | (composite) | **CREATE** — 404 currently |
| `/api/v2/agent-debates` | GET | agent_debates | **CREATE** — table may not exist |

### Agent Registration Gap

| Agent | Role | Analyses | OpenClaw .md file |
|---|---|---|---|
| aegis | Overnight synthesis orchestrator | daily | `~/.openclaw/agents/aegis.md` ✅ |
| steph | Wealth advisor, TRIM/HOLD/BUY | 100+ | `~/.openclaw/agents/steph.md` ✅ |
| main | System router | — | `~/.openclaw/agents/main.md` ✅ |
| **maria** | Fundamental research + discovery | 100+ | **MISSING** ❌ |
| **risk_agent** | Stop-loss, drawdown, position sizing | 80+ | **MISSING** ❌ |
| **tax_agent** | SSDI, Roth, IRMAA, bracket math | **2 total** | **MISSING** ❌ |
| **alex** | Retirement planning, disability context | **3 total** | **MISSING** ❌ |
| **iris** | Taxonomy, content gaps, RAG hygiene | 50+ | **MISSING** ❌ |

### Social Intelligence Plan (Prioritized)

| Phase | Source | Auth | Cost | Value |
|---|---|---|---|---|
| **1 (NOW)** | StockTwits | None — public API | Free | Best ticker-specific retail sentiment |
| **2 (next)** | Reddit RSS | None — JSON feeds | Free | r/dividends, r/investing retirement content |
| **3 (defer)** | X/Twitter | Enterprise API | $100+/mo | Not justified at current scale |

StockTwits API: `https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json`
- No authentication required for public streams
- Returns: messages with body, sentiment (bullish/bearish/neutral), timestamp
- Rate limit: 200 requests/hour (sufficient for daily portfolio scan)

Reddit RSS: `https://www.reddit.com/r/{subreddit}/new/.json?limit=25`
- No authentication required
- Parse as news_articles with source_type='reddit'
- Target subreddits: r/dividends, r/investing, r/retirement, r/financialindependence

### Telegram Commands — Full Parity Target

| Command | Purpose | Status |
|---|---|---|
| `/approve <task_id> [notes]` | Approve task → feeds back to RAG | **MISSING** |
| `/reject <task_id> [notes]` | Reject task → feeds back to RAG | **MISSING** |
| `/defer <task_id>` | Defer for later review | **MISSING** |
| `/tasks` | List all pending_john tasks | **MISSING** |
| `/proposals` | List all proposed watchlist items | **MISSING** |
| `/debate <SYMBOL>` | Show agent conflict + decide | **MISSING** |
| `/agents` | All 7 agents status + last run | **MISSING** |
| `/rag` | RAG coverage summary (items, %, gaps) | **MISSING** |
| `/weekly` | Weekly intelligence summary | **MISSING** |
| `iris approve <id>` | Approve Iris taxonomy proposal | ✅ Working |
| `iris reject <id>` | Reject Iris taxonomy proposal | ✅ Working |

### Data Quality Fix: Ticker Validation

Corrupt proposals found: `THIS`, `MAY`, `COULD` — text fragments parsed as symbols.

```python
import re
VALID_TICKER = re.compile(r'^[A-Z]{1,5}$')
INVALID_WORDS = {'THIS', 'MAY', 'COULD', 'WOULD', 'SHOULD', 'WILL', 'THAT', 'WITH', 'FROM', 'HAVE', 'BEEN'}

def validate_symbol(sym: str) -> bool:
    if not VALID_TICKER.match(sym):
        return False
    if sym in INVALID_WORDS:
        return False
    return True
```

Delete bad rows: `DELETE FROM watchlist_proposals WHERE symbol IN ('THIS','MAY','COULD') AND action='rotate';`

### Phased Execution Plan (Hard Checkpoints — No Phase Skipping)

```
PHASE 1 — APPROVALS PERSIST (nothing else proceeds until this passes)
  1. Find/create POST /api/v2/tasks/<id>/resolve
  2. Verify POST /api/v2/proposals/decide works for watchlist_proposals
  3. Wire Telegram /approve, /reject, /defer for both tables
  4. Delete corrupt proposals (THIS, MAY, COULD)
  ✅ CHECKPOINT 1: curl → DB shows status changed, decided_at NOT NULL

PHASE 2 — DECISIONS FEED BACK INTO RAG
  5. On task resolve: INSERT decision_outcomes (decided_by='john')
  6. Immediately index new outcome into RAG embeddings
  7. Add john_decisions context to aegis synthesis prompts
  ✅ CHECKPOINT 2: approve task → decision_outcome row exists → RAG embedded

PHASE 3 — DEBATE WIRING
  8. CREATE TABLE agent_debates (if missing)
  9. Add _check_and_trigger_debate() after agent job completion
  10. Telegram alert on conflict detection
  ✅ CHECKPOINT 3: agent_debates table exists, conflict triggers debate row

PHASE 4 — AGENT REGISTRATION
  11. Create maria.md, risk_agent.md, tax_agent.md, alex.md, iris.md
  12. Restart OpenClaw gateway
  ✅ CHECKPOINT 4: all 7 agents visible in /api/v2/orchestration

PHASE 5 — UNDERUSED AGENTS
  13. Add tax_agent + alex to Tier 1 nightly holdings batch
  14. Run tonight's aegis cycle
  ✅ CHECKPOINT 5: tax_agent >= 6 analyses, alex >= 6 analyses

PHASE 6 — TELEGRAM COMMAND PARITY
  15. Add /tasks, /proposals, /debate, /agents, /rag, /weekly
  ✅ CHECKPOINT 6: /tasks returns list of pending tasks via Telegram

PHASE 7 — CIO AUTO-TRIGGER + WEEKLY REPORT
  16. Auto-CIO decision after consensus STOP resolution
  17. GET /api/v2/weekly-report endpoint
  ✅ CHECKPOINT 7: /api/v2/weekly-report returns structured JSON

PHASE 8 — BUILD + RESTART + VALIDATE
  18. npm run build (0 TypeScript errors)
  19. systemctl --user restart tradeai-portfolio-server.service
  20. Full validation suite (all checkpoints re-verified)
```

### Friday Autonomy Readiness Criteria

| Criterion | Required | How to Verify |
|---|---|---|
| Approvals persist to DB | ✅ Both tables update on resolve | curl + psql |
| Human decisions in RAG | ✅ decision_outcomes written + embedded | Query content_embeddings |
| Agent conflicts detected | ✅ Debates auto-created on disagreement | Check agent_debates after next STOP event |
| All 7 agents callable | ✅ OpenClaw orchestration lists all | /api/v2/orchestration |
| Tax + Alex running nightly | ✅ >= 6 analyses each | watchlist_agent_results count |
| Telegram full control | ✅ /approve, /tasks, /debate all work | Send commands from phone |
| Weekly report available | ✅ GET /api/v2/weekly-report returns JSON | curl test |

### Final Validation Suite

```bash
# APPROVAL LOOP
curl -X POST http://localhost:7777/api/v2/tasks/37/resolve \
  -d '{"decision":"approved","notes":"hold through defense cycle"}' -H "Content-Type: application/json"
psql trade_ai -c "SELECT status, decided_at FROM tasks WHERE id=37;"
# → status='approved', decided_at NOT NULL

# DECISION → RAG LOOP
psql trade_ai -c "SELECT symbol, outcome, decided_by FROM decision_outcomes WHERE decided_by='john' ORDER BY created_at DESC LIMIT 3;"
# → LMT row with decided_by='john'
psql trade_ai -c "SELECT COUNT(*) FROM content_embeddings WHERE source_type='decision_outcome';"
# → COUNT > 0

# DEBATES
psql trade_ai -c "SELECT COUNT(*) FROM agent_debates;"
# → >= 1

# ALL 7 AGENTS
curl -s http://localhost:7777/api/v2/orchestration | python3 -m json.tool | grep -c '"agent"'
# → 7

# TAX + ALEX ACTIVE
psql trade_ai -c "SELECT agent, COUNT(*) FROM watchlist_agent_results WHERE agent IN ('tax_agent','alex') GROUP BY agent;"
# → both >= 6

# TELEGRAM: /tasks → returns pending tasks list
# TELEGRAM: /approve 37 → "✅ Task approved: LMT..."
```

### Version History Entry

| Version | Key Changes |
|---|---|
| v2.54 | May 2 deep audit: TWO tables stuck (tasks + proposals), debate never triggers, 5 agents unregistered, tax/alex underused (2-3 analyses), human decisions don't feed RAG, 8-phase fix plan with hard checkpoints, Friday autonomy target |
