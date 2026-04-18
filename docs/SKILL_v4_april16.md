---
name: trade-ai-v12
description: >
  Local Python trade intelligence pipeline for daily scalp trading AND portfolio
  management. Use this skill when the user wants to: run the Trade AI pipeline,
  check recent run results, interpret scores or catalysts for specific tickers,
  understand why a ticker is GO or WAIT, read the dashboard, configure screeners
  or weights, troubleshoot errors, schedule runs, view portfolio analytics, check
  performance history, retirement planning, risk management, tax analysis,
  rebalancing orders, Fidelity 401k fund exchanges, weekly/monthly reports,
  OpenClaw agents (Maria/Steph), or any aspect of Trade AI v12 or Portfolio
  Intelligence v1.2. Also triggers on: "run trade ai", "check my screeners",
  "what's moving", "check my portfolio", "run monthly analysis",
  "what did Maria say", "show reports hub", or any variation.
---

# Trade AI v12 + Portfolio Intelligence — Master Skill v4
## Updated: April 16, 2026 (Full Day — End of Day)

**BOTH SYSTEMS RUN ON MS-01 (Ubuntu 24.04). LENOVO_AURA IS DORMANT.**

---

## SYSTEM TOPOLOGY

| Machine | Role | Address |
|---|---|---|
| MS-01 (`ms01-openclaw`) | Primary runtime | 192.168.50.16 |
| LENOVO_AURA | Dormant (Windows) | local |

**MS-01 Project Root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`
(double-nested — intentional)

**URLs:**
- Command Center: `http://192.168.50.16:7777/reports/command_center.html`
- Portfolio: `http://192.168.50.16:7777/reports/portfolio_live.html`
- Trade AI: `http://192.168.50.16:7777/reports/dashboard_live.html`
- Reports Hub: `http://192.168.50.16:7777/reports/reports_hub.html`

**Server restart:**
```bash
fuser -k 7777/tcp && sleep 2 && systemctl --user restart portfolio-server.service
```

---

## IRON RULES — NEVER VIOLATE

1. **Before ANY deploy:** `python3 -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'],len(d.get('holdings',[])))"` — abort if total=0 or count<40
2. **holdings.json = single source of truth.** Import modal = ONLY entry point. Never bypass `/api/import`.
3. **Dedup key:** `date|action|symbol|abs(qty)|account` (account on BOTH client and server)
4. **Fidelity symbols:** hyphen + len>5 → never reprice from Yahoo, never send to RSI/SMA
5. **Python 3.13 on MS-01** — always `ast.parse()` validate before deploying
6. **OLLAMA QUEUE LAW:** ALL calls via `_ollama_serialized()` (threading.Lock). Never call directly in loops. `num_predict=500` min for JSON.
7. **Forensic:** Read `docs/forensic_files_v4.md` before touching any file

---

## SCHEDULED JOBS (MS-01 Systemd)

| Timer | Schedule | Script | What it runs |
|---|---|---|---|
| tradeai-continuous | Mon-Fri 3AM | run_continuous.sh | 23-stage Trade AI pipeline all day |
| portfolio-daily | Mon-Fri 7AM | run_portfolio.sh | Full portfolio pipeline |
| portfolio-price-cache | Sunday 7PM | run_price_cache.sh | Yahoo price history refresh |
| **portfolio-weekly** | **Sunday 8PM** | run_portfolio_weekly.sh | Full pipeline + backfill + **Ollama weekly report** + reports hub |
| **portfolio-monthly** | **1st of month** | run_portfolio_monthly.sh | Full pipeline + AI analyst + **Ollama weekly** + **Sonnet monthly** + reports hub |
| portfolio-lookthrough | 1st Sunday 6AM | run_lookthrough.sh | Fund lookthrough refresh |

### Weekly launcher (Sunday 8PM) — full chain:
1. `portfolio_orchestrator.py` (full pipeline)
2. `backfill_acct_periods_v3.py` (per-account period returns)
3. **`portfolio_weekly_report.py`** — Ollama qwen3:14b, HTML + JSON + Telegram
4. `generate_reports_hub.py` — updates reports index

### Monthly launcher (1st of month) — full chain:
1. `portfolio_orchestrator.py` (monthly run)
2. `portfolio_ai_analyst.py` (Sonnet AI analysis sections)
3. **`portfolio_weekly_report.py`** — Ollama generates this month's weekly report first
4. **`portfolio_monthly_synthesis.py`** — Sonnet reads last 4 weekly JSONs → monthly HTML + Telegram
5. `generate_reports_hub.py` — updates reports index

### Continuous runner (3AM–11AM Mon-Fri):
- 3:00–4:00 AM: 30-min cycles (deep pre-market, Ollama catalyst prep)
- 4:00–6:00 AM: 30-min full cycles
- 6:00–9:00 AM: 15-min cycles
- 9:00–10:00 AM: 10-min cycles
- 10:00–11:00 AM: 15-min wind-down
- **6:55 AM:** Pre-market digest (Telegram, Ollama qwen3:14b)
- **9:25 AM:** Pre-open brief (Telegram, Ollama qwen3:14b)

---

## 4-TIER LLM CHAIN (EVERYWHERE — April 16)

| Tier | Model | Cost | Speed | Use case |
|---|---|---|---|---|
| 1 | qwen3:1.7b | $0 | 2-14s | Catalyst JSON, GO alerts, short tasks |
| 2 | qwen3:14b | $0 | 22-57s | Narratives, pre-plans, digests, **weekly reports** |
| 3 | openai/gpt-5.4-mini | ~$0 | ~2s | Cloud fallback |
| 4 | anthropic/claude-sonnet-4-6 | $3/1M | ~3s | Final fallback, **monthly synthesis**, Roth section |

**local_llm.py:**
```python
generate(prompt, fast=True)   # qwen3:1.7b first → falls back up chain
generate(prompt, fast=False)  # qwen3:14b first → falls back up chain
model_used                     # global: which tier responded last
```

---

## FINVIZ ENRICHMENT (NEW — April 16)

**Module:** `scripts/finviz_enrichment.py`
**Cache:** `data/state/ticker_enrichment_cache.json` (6h TTL)
**Doc:** `docs/FINVIZ_ENRICHMENT.md`

| View | Key Fields |
|---|---|
| v=131 | **Float (M)**, Short Float%, Inst Own%, Avg Volume |
| v=141 | **RVOL**, Perf Week/Month/YTD/Year, Volatility |
| v=161 | PE, ROE, Dividend Yield, Margins |
| v=171 | **RSI(14)**, **SMA20/50/200%**, ATR, Beta, Gap% — NO COOKIE NEEDED |

**Wired into:**
- Trade AI Stage 2.5 → injects `float_m` + `rvol` into tickers before scoring
- `portfolio_technical.py` Step 3.5 → replaces broken cookie scrape for RSI/SMA
- CC DataProvider `S.enrichment` → Portfolio Events RSI alerts + earnings dates

**Result:** GO=4/WAIT=4 today (was GO=0 before float/RVOL were 0)

---

## BRAVE SEARCH (NEW — April 16)

**Module:** `scripts/brave_search.py`
**Key:** `BRAVE_SEARCH_API_KEY` in `.env` + ENV Keys modal
**Free tier:** 2,000 queries/month (~1,082 used for Stage 6)

**Used in Stage 6 catalyst_intelligence.py only** — injects live web news context
into Ollama prompt for better catalyst classification.
NOT used in live cycles, repricing, or technical analysis.

---

## REPORTING SYSTEM (LIVE — April 16)

### Weekly Detailed Report (Ollama — Sunday 8PM + 1st of month):
- **Script:** `scripts/portfolio_weekly_report.py`
- **Engine:** Ollama qwen3:14b (~2 min, $0)
- **Output:** `data/portfolios/reports/weekly/weekly_YYYY-MM-DD.{html,json}`
- **Sections:** Performance, Technical health, Cash utilization, Trade journal, Action
- **Telegram:** 5-line summary + link
- **Retention:** Last 8 kept

### Monthly Synthesis (Sonnet — 1st of month):
- **Script:** `scripts/portfolio_monthly_synthesis.py`
- **Engine:** Claude Sonnet (reads last 4 weekly JSONs)
- **Output:** `data/portfolios/reports/monthly/monthly_YYYY-MM-DD.{html,json}`
- **Sections:** Monthly synthesis, Rebalancing, **Roth conversion guidance**, Tax optimization
- **Telegram:** Summary + Roth guidance + link
- **Retention:** Last 6 kept

### Reports Hub:
- **Script:** `scripts/generate_reports_hub.py`
- **Output:** `reports/reports_hub.html`
- **Shows:** Last 8 weekly, last 6 monthly, last 14 daily DOCX
- **Linked from:** CC pipeline control section

---

## TRADE AI PIPELINE — STAGES

| Stage | Name | Notes |
|---|---|---|
| 1 | Weekly hygiene | |
| 2 | Finviz ingestion | 2 screeners |
| **2.5** | **Finviz enrichment** | float_m, rvol, RSI, SMA — NEW Apr 16 |
| 3 | Market context | SPY/VIX/sectors |
| 4 | Economic calendar | |
| 5 | Pre-score filter | min_pre_score=8 |
| 6 | Catalyst enrichment | 7 sources |
| **6b** | **Catalyst intelligence** | qwen3:1.7b + Brave Search — NEW Apr 16 |
| 7 | Options flow | |
| 8 | Short interest | |
| 9 | Sector momentum | |
| 10 | Trend engine | |
| 11 | **Scoring** | float_m from enrichment, rvol from enrichment |
| 12 | Squeeze bonus | |
| 13 | Halt detection | |
| 14 | Social sentiment | |
| 15 | Delta tracking | |
| 16 | Trade plans | Sonnet ≥48, qwen3:14b 25-47 |
| 17-20 | HTML/PDF/DOCX/TOS | |
| 21 | Persistent dashboard | shutil.copy2 |
| **22** | **Alerts** | Telegram + qwen3:1.7b GO one-liner — NEW Apr 16 |
| 23 | Portfolio reprice | |

### Scoring (5 pillars, max 55pts):
| Pillar | Max | Source |
|---|---|---|
| Catalyst Quality | 15 | Ollama Stage 6b |
| RVOL | 12 | finviz_enrichment v=141 |
| Price Action | 10 | Finviz |
| Float | 8 | finviz_enrichment v=131 |
| Price Range | 5 | Finviz |
| Sector Momentum | 5 | market_context |

**GO ≥40 | WAIT 30-39 | AVOID <30 | A+ ≥48**

---

## COMMAND CENTER v48

**Portfolio filter (account pills):** All Accounts / Fidelity 401k / Rollover IRA / Roth IRA / Taxable
- Period returns filter by selected account ✅ (fixed Apr 16)
- Cash card filters by selected account ✅
- Holdings filter by selected account ✅

**TOS Export:** Copy GO / Copy WAIT (NEW Apr 16) / Copy All

**GO/WAIT counts:** Calculated from TICKERS array (not stale run_summary.json — fixed Apr 16)

**DataProvider:** holdings, health, retirement, journal, watchlist, dividends,
risk, perf_history, behavioral, options_data, attribution, correlation, **enrichment** (NEW)

---

## OPENCLAW (MS-01)

**Bot:** @bigjohn_openclaw_bot
**Restart:** `openclaw gateway restart`
**Model chain:** qwen3:1.7b → qwen3:14b → gpt-5.4-mini → claude-sonnet-4-6

**Agents:**
- **Maria** (main): personal assistant, email/calendar via Google OAuth
- **Steph**: portfolio advisor with full SOUL.md context

**Known issue:** Sessions sometimes start on gpt-5.4-mini despite qwen3:1.7b primary.
Both `openclaw.json` AND `models.json` now have qwen3:1.7b in allowed lists.
Workaround: `/new` then "switch to qwen3:1.7b"

**Google OAuth:** john@jwwhiting.com (Calendar/Gmail/Drive)

⚠️ **ROTATE BOTH API KEYS** (Anthropic + OpenAI) — exposed April 16

---

## PORTFOLIO STATE (April 16, 2026 EOD)

| Metric | Value |
|---|---|
| Total | ~$1,201,407 |
| Cash | ~$36,388 (3.0%) |
| Dividends/yr | ~$10,298 |
| Beta | 0.381 |
| 1W | +3.55% / +$41,209 |
| YTD | -13.43% / -$186,400 |
| 1Y | +6.09% / +$68,974 |

---

## KEY FILE LOCATIONS

| File | Purpose |
|---|---|
| scripts/finviz_enrichment.py | 5-view enrichment, 45 fields, shared cache |
| scripts/brave_search.py | Brave Search API wrapper |
| scripts/local_llm.py | 4-tier LLM fallback chain |
| scripts/catalyst_intelligence.py | Stage 6b — Ollama + Brave |
| scripts/ticker_memory.py | 14-day ticker observation store |
| scripts/morning_digest.py | 6:55AM + 9:25AM Telegram |
| scripts/portfolio_weekly_report.py | Weekly HTML + Telegram (Ollama) |
| scripts/portfolio_monthly_synthesis.py | Monthly Sonnet synthesis |
| scripts/generate_reports_hub.py | Reports hub generator |
| data/state/ticker_enrichment_cache.json | Finviz 45-field cache (6h TTL) |
| data/state/ticker_memory.json | 14-day Ollama observations |
| data/portfolios/reports/weekly/ | Weekly reports |
| data/portfolios/reports/monthly/ | Monthly reports |
| reports/reports_hub.html | Central reports index |
| docs/forensic_files_v4.md | File status (ACTIVE/LEGACY/DELETE) |
| docs/LOCAL_LLM_IMPLEMENTATION.md | LLM architecture SOP |
| docs/FINVIZ_ENRICHMENT.md | Finviz enrichment SOP |
| linux_launchers/run_portfolio_weekly.sh | Weekly launcher |
| linux_launchers/run_portfolio_monthly.sh | Monthly launcher |

---

## PENDING (Next Session)

| Item | Priority |
|---|---|
| Rotate API keys (Anthropic + OpenAI — EXPOSED) | CRITICAL |
| OpenClaw starts on GPT not Ollama | MEDIUM |
| Fidelity 401k per-account periods null | By design until 2027 |
| Omnicom 401k → Rollover IRA | 2027 |
