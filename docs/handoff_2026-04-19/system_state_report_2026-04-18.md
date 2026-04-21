# Trade AI v12 — System State Report
**As of: 2026-04-19 | Baseline: 762d4ed (Apr 18 morning) | Current HEAD: 087fd08**
**35 commits since baseline**

---

## SECTION A: What's been added since 762d4ed

### Strategy Center / AI Analyst (12 commits)
- `0e3a1b7` — Complete rebuild of Command Center as React SPA (Strategy Center) with React 18 + Tailwind via CDN, 10 sections, SVG charts, live JSON fetching
- `2fd7398` — Restored original CC, made Strategy Center a separate file (`strategy_center.html`) linked via CC's AI Analyst tab (iframe)
- `83fe5b2` — AI Analyst tab in CC loads Strategy Center via iframe instead of old renderAIDeep()
- `283cf24` — Replaced CC's plain-text AI rendering (`esc(cleanMd(text))`) with full `renderMd()` that produces styled cards, checklists, recommendation highlights
- `9472456` — Redesigned AI Analyst sections as actionable dashboard cards with collapsible panels
- `7171742` — Added auto-detected visual charts (tax impact bars, allocation bars, deduction tables) from AI markdown patterns
- `d676c8e` — Added KPI hero bar (6 tiles) + sector pie chart (CSS conic-gradient) to AI Analyst page
- `8fcc78a` — Fixed Roth Deep Dive empty section (was looking for key `roth_conversion_detail`, correct key is `roth_conversion`)
- `d4ec980` — Fixed CC crash: null RSI guard in renderPortfolioEvents (`null <= 28` is true in JS)
- `934f3c1` — Labeled every AI section with exact model name (claude-sonnet-4-20250514, gpt-4o)
- `debaf7c` — Expanded .env modal from 6 keys to 26 (all API keys, toggles, config)
- `087fd08` — Added Position Intelligence cockpit: 6 KPIs, filter chips, sort modes, position cards grid, expandable detail drawers, composite PI Score (Technical 25% + Momentum 25% + Analyst 20% + Risk 15% + Catalyst 15%)

### DOCX Report (8 commits)
- `c904038` — Complete rebuild as 14-page wealth strategy document with embedded PNG charts via node-canvas (donut, bar, column, gauge, timeline, progress)
- `dca93dc` — v2: Fixed all 12 issues from professional review (dividends $0→$10,415, gain% corrected, stops populated, source labels, data integrity page)
- `ecf65f0` — Fixed stops loading (from stops.json directly), gain% reading (from source gain_pct field), dividend fallback chain
- `a566326` — v3: 5 surgical fixes (SPY claim softened, dividend reconciliation footnote, SRNE removed from action plan, appendix reconciliation note, top-5 concentration stat)
- `b2fcae6` — v4: Moved 5 detailed AI blocks from main body to appendix, stripped raw HTML from AI text, fixed perf_history not being passed to DOCX generator
- `93f3c94` — Wired weekly→monthly data flow: weekly DOCX now passes all params; monthly AI now loads previous weekly JSONs for trend context
- `06fd8ff` — Added canvas npm dependency for chart generation
- `1c39603` — Added package-lock.json + .env.example for disaster recovery

### Portfolio News System (4 commits)
- `28541a6` — New module `portfolio_news.py`: scans 30 portfolio tickers via 7 API sources (Finnhub, NewsAPI, Polygon, FMP, Finviz News, Yahoo, Brave), LLM scoring via Ollama qwen3:1.7b, 90-day rolling history, weekly/monthly synthesis
- `fc55b16` — Major redesign: added relevance classification (company_specific, sector_spillover, peer_related, macro, misattributed), executive strip JSON, filter chips, expandable detail drawers, separated company vs sector news in DOCX
- `148da10` — Made news headlines clickable + added urgency tooltips with hover explanations
- `239a8f6` — Added news feed to CC Portfolio zone + expanded stops from 6 to 29 positions (100% coverage)

### Stops / Position Intelligence (2 commits)
- `ca152c8` — New module `stop_decision_brief.py`: auto-generates decision briefs when stop alerts fire, synthesizes holdings + news + technicals + sector peers + signals, LLM-scored recommendation (HOLD/WATCH/TRIM/HONOR_STOP/DELAY), sent via Telegram
- `239a8f6` — Auto-generated stops for all 23 uncovered positions (ETFs 10%, bonds 5%, funds 12%, stocks ATR-based 8-20%)

### Dual-AI Advisory (2 commits)
- `a449236` — New module `monthly_advisory.py`: monthly-only dual-perspective advisory from Claude Opus (conservative/fiduciary) + GPT-4o (opportunity-focused). Side-by-side comparison in Strategy Center
- `0bfed23` — Replaced Sonnet with GPT-4o for second perspective. Added OpenAI API integration

### Fixes / Infrastructure (7 commits)
- `acbf21a` — Fixed portfolio YTD from -13.08% to +3.47% by moving account-aggregation outside Fidelity conditional
- `461b3f7` — Fixed missing `timedelta` import exposed by YTD fix
- `2483dc6` — Added per-account period returns to `compute_period_returns()` (Schwab accounts were missing)
- `d83431c` — Added dashboard rebuild after account-aggregation so live report reflects correct YTD
- `1419975` — Fixed Sonnet model ID (`claude-sonnet-4-5-20251015` → `claude-sonnet-4-20250514`) and .env had wrong `CLAUDE_ESCALATION_MODEL`
- `6aff411` — Added supplemental Finviz enrichment for small positions (<$1K) — cache grew from 50 to 67 tickers including SPY
- `75a8fa0` — Fixed weekly report: real movers data from enrichment (was 0.00%), added SPY benchmark comparison table
- `a840de0` — Fixed Strategy Center blank page (OLLAMA_MODEL undefined in browser JS)

---

## SECTION B: Current System Architecture

**95 Python scripts** in `scripts/`. 3 new since baseline:
- `scripts/monthly_advisory.py` — Dual-AI advisory (Opus + GPT-4o)
- `scripts/portfolio_news.py` — Portfolio news collection, LLM scoring, synthesis
- `scripts/stop_decision_brief.py` — Automated stop alert decision briefs

**Reports directory:**
- `command_center.html` (569KB) — Original CC, largely unchanged, AI Analyst tab loads Strategy Center via iframe
- `strategy_center.html` (114KB) — NEW: React 18 SPA with 28 components, Tailwind + Babel CDN, fetches live JSON data. Contains: HeaderHero, PrioritiesPanel, PositionIntelligence, RothStrategy, IncomeArchitecture, BondStrategy, ConcentrationRisk, IraOpportunities, TacticalSleeve, ActionCenter, PortfolioNews, DualAdvisory, AiDeepSections
- `portfolio_live.html` (435KB) — Portfolio Intelligence dashboard (18-tab, Python-generated)
- `dashboard_live.html` (68KB) — Trade AI dashboard

**Strategy Center is a SEPARATE file** (`strategy_center.html`), loaded inside the CC's AI Analyst tab via `<iframe>`. The original CC is preserved with all its other tabs.

---

## SECTION C: Current Data State

**43 JSON state files** in `data/portfolios/state/`, totaling **20MB**.

Largest files:
- `tax_lots.json` — 4.4MB
- `price_cache.json` — 2.6MB
- `trade_journal.json` — 196KB
- `holdings.json` — 187KB (47 holdings, 4 accounts)

Key structures:
- `holdings.json`: 47 holdings with keys: symbol, name, shares, price, market_value, account, sector_type, asset_type, is_cash, is_fund, reinvest_div, day_change, day_change_pct, account_id, portfolio_pct. Top-level: as_of, owner, holdings, transactions, account_summaries, portfolio_totals, config, last_repriced, reprice_source, pending_pipeline_run
- `action_signals.json`: dict with keys generated_at, coverage, golden_window_note, signals. Contains 40 signals, each with symbol/signal/rule/note/thesis_groups
- `ai_analysis_cache.json`: 7 AI text sections (executive_summary, deep_holdings, dividend_strategy, bond_strategy, ira_opportunities, v_strategy, defense_analysis) + generated_at + run_type. Generated 2026-04-19, run_type: daily
- `portfolio_news.json`: 20 scored catalysts with llm_score, llm_category, llm_urgency, relevance_type, brave_context
- `monthly_advisory.json`: dual advisory (opus + gpt4o) with model names
- `stops.json`: dict of 29 entries (6 manual + 23 auto-generated), each with stop, trail_pct, notes, set_date, account

Additional state files: ticker_enrichment_cache (67 tickers from Finviz), technical_snapshot, risk_management, correlation, retirement_roadmap, tax_projection, stress_test, dividend_calendar, earnings_dates, watchlist_intelligence, performance_history (with per-account periods), fund_lookthrough, behavioral_analytics, performance_attribution, snapshot_index

History directories:
- `snapshots/` — 16 daily portfolio snapshots (224KB)
- `portfolio_news_history/` — 1 day so far (32KB)
- `stop_briefs/` — 1 brief (12KB)

---

## SECTION D: Current AI Architecture

| Model | Where Used | Purpose |
|---|---|---|
| `claude-sonnet-4-20250514` | `portfolio_ai_analyst.py` | Monthly AI analysis (8 sections) |
| `claude-haiku-4-5-20251001` | `portfolio_ai_analyst.py` | Daily executive summary (cheap) |
| `claude-opus-4-20250514` | `monthly_advisory.py` | Conservative fiduciary advisory (monthly) |
| `gpt-4o` (OpenAI) | `monthly_advisory.py` | Opportunity-focused advisory (monthly) |
| `qwen3:1.7b` (Ollama local) | `portfolio_news.py`, `stop_decision_brief.py`, weekly report | News scoring, catalyst classification, stop decisions, weekly narratives |
| `qwen3:14b` (Ollama local) | `catalyst_intelligence.py` | Trade AI catalyst analysis (heavier model) |

**Yes, OpenAI GPT-4o is integrated** in `monthly_advisory.py` via direct API call. The .env has `OPENAI_API_KEY` set.

**Yes, dual-AI advisory exists** in `monthly_advisory.py` + displayed in `strategy_center.html` DualAdvisory component. Monthly-only. Side-by-side Opus vs GPT-4o with tab toggle.

---

## SECTION E: PostgreSQL Readiness

**PostgreSQL IS installed and running** (active since Apr 13, systemd enabled).

**Existing DB infrastructure:**
- `scripts/db_adapter.py` — Drop-in storage adapter that auto-detects platform. If Linux + DB creds → PostgreSQL, else → JSON files. Already uses `psycopg2`. Currently covers 5 "Category-1" tables only.
- `linux_port_v2/linux/db_setup.sql` — Schema for 5 tables: holdings (JSONB, one row per day), price_cache (symbol + date + close_price), portfolio_snapshots (date + total_value + accounts JSONB), trade_ai_state, run_summary
- `requirements.txt` includes `psycopg2-binary==2.9.10`

**Current DB adapter only migrates 5 "Category-1" files.** The remaining 38 "Category-2" files are explicitly left as JSON with the comment: "computed fresh every run and owned by their single module."

**Migration scope:**
- 43 JSON files to potentially migrate
- 20MB total data
- 3 history directories (snapshots, news_history, stop_briefs)
- `db_adapter.py` already exists as the abstraction layer but only covers 5 tables
- No `.env` DB credentials currently set (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)

---

## SECTION F: Known Issues / Open Threads

- **No TODO/FIXME/XXX** in the 3 new scripts
- **Working tree is clean** (only `portfolio_live.html` modified — auto-regenerated by pipeline)
- 3 `.bak` files from pre-rebuild backups (not tracked, not needed)
- **Analyst downgrade KPI** in Position Intelligence shows 22 — this counts all "Strong Sell" Finviz ratings, not actual recent downgrades. Should be refined.
- **Relevance classification** tends conservative — Visa company-specific news sometimes classified as `sector_spillover`. Improves with prompt tuning.
- **Social sentiment module** (`social_sentiment.py`) exists but is NOT wired into the portfolio news pipeline yet
- **Only 1 day of news history** — week-over-week and month-over-month comparisons will strengthen as daily snapshots accumulate
- **V technical snapshot** is empty (0 fields) despite enrichment data being available — may be a threshold or mapping issue in `portfolio_technical.py`

---

## SECTION G: What the user wants to do with Postgres

*[To be filled in by user]*
