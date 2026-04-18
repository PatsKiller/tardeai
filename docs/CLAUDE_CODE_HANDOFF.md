# CLAUDE CODE HANDOFF — Portfolio Intelligence v1.2
## Date: April 18, 2026 | Prepared by: Claude Sonnet (claude.ai session)

---

## SYSTEM OVERVIEW

John W. Whiting's local AI trading + portfolio intelligence platform running on MS-01 (Ubuntu).
- **Project root**: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`
- **Venv**: `.venv` (activate: `source .venv/bin/activate`)
- **Server**: `python3 scripts/portfolio_server.py` on port 7777
- **Dashboard**: `http://192.168.50.16:7777/reports/command_center.html`
- **Weekly report**: `http://192.168.50.16:7777/reports/weekly/weekly_YYYY-MM-DD.html`

---

## WHAT WAS BUILT (DO NOT REDO)

### Phase 1 — Data Foundation ✅
1. **Cost basis from transactions**: `scripts/portfolio_orchestrator.py` now computes cost basis from `trade_journal[]` (619 transactions) after `load_all_portfolios()`. 32/47 holdings get cost basis. Result: `total_gain` and `gain_loss_pct` per holding now accurate.
2. **Snapshots fixed**: `scripts/portfolio_performance_history.py` now saves per-account values in each daily snapshot (`data/portfolios/state/snapshots/YYYY-MM-DD.json`). CASH-only snapshots filtered out (>50% non-cash required).
3. **Server routes**: `scripts/portfolio_server.py` now serves `/data/portfolios/reports/` path — weekly HTML accessible.
4. **Weekly served**: `scripts/portfolio_weekly_report.py` copies HTML+DOCX to `reports/weekly/` after generation.
5. **Telegram both IDs**: Weekly report sends to both `TELEGRAM_CHAT_ID` values (comma-separated).

### Phase 2 — Weekly Intelligence ✅
1. **6-section AI narrative**: `_generate_narrative()` in `portfolio_weekly_report.py` now uses full data injection — RSI, SMA200, earnings dates, dividend gap, institutional flow, risk/stops.
2. **Iterative context**: Reads last 3 weekly JSONs (`data/portfolios/reports/weekly/weekly_*.json`) and shows delta vs prior weeks in Performance prompt.
3. **Analyst ratings**: `scripts/finviz_enrichment.py` now parses `recom` field (was stored as % string like "1.97%") into `recom_score` (float 1-5) and `analyst_rating` (Strong Buy/Buy/Hold/Sell/Strong Sell). View 121 (Valuation/EPS) added.
4. **Analyst intelligence functions**: `_build_analyst_intelligence()` and `_build_rebalance_rationale()` added to weekly report — each rebalancing order now explains WHY (drift %, analyst rating, RSI, institutional flow). Source cited as "Finviz Elite consensus".
5. **Brave search**: `_get_brave_analyst_commentary()` added — pulls recent analyst commentary from Reuters, Bloomberg, MarketWatch etc for top 5 holdings (optional, uses `BRAVE_API_KEY` env var).
6. **DOCX attached to Telegram**: `_send_telegram_doc()` uses `requests` multipart upload to send `weekly_YYYY-MM-DD.docx` as attachment.
7. **CC AI tab redesign**: `reports/command_center.html` `renderAIDeep()` replaced with 18-section sidebar nav layout. Sidebar has 15 portfolio sections + AI Analysis group.

### AI Analyst ✅
- `scripts/portfolio_ai_analyst.py`: uses `qwen3:1.7b` with `think:False` — 8 sections, ~2 min, zero API cost.
- `_AI_RULES` constant prepended to every section prompt — prevents $0 values, repeated context blocks, generic statements.
- Weekly run triggered by `run_type="weekly"` — all 8 sections via Ollama.

### Live Cycle Score Fix ✅
- `scripts/trade_ai_orchestrator.py` saves `data/live_run_state.json` after each full run with GO decisions.
- `scripts/continuous_runner.py` reads it and restores GO when live rescore drops to 0.

---

## WHAT STILL NEEDS BUILDING (PHASE 3)

### 3A — Monthly Report (HIGHEST PRIORITY)
**File to create**: `scripts/portfolio_monthly_report.py`
**What it should do**:
- Run on 1st of month via `linux_launchers/run_portfolio_monthly.sh`
- Read last 4 weekly JSONs from `data/portfolios/reports/weekly/weekly_*.json`
- Load all current state files (holdings, technical, risk, dividends, performance history)
- Use **Claude Sonnet** (via Anthropic API — key in `.env` as `ANTHROPIC_API_KEY`) for deep analysis
- Produce a comprehensive DOCX report (use `node scripts/portfolio_brief_v2.js` as base)
- Sections: Executive summary with trend analysis across 4 weeks, per-account performance vs benchmarks, what changed month-over-month, top analyst calls, rebalancing priority, Roth conversion progress, Golden Window countdown, action plan
- Send DOCX to Telegram both IDs
- Save monthly JSON to `data/portfolios/reports/monthly/`

**Key pattern for Sonnet calls**:
```python
import anthropic
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
msg = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4000,
    messages=[{"role": "user", "content": prompt}]
)
text = msg.content[0].text
```

### 3B — CC Visual Rebuild (SECOND PRIORITY)
**File**: `reports/command_center.html`
**What needs improvement**:
- Add Chart.js interactive charts to key tabs:
  - Holdings tab: portfolio allocation donut chart + account bar chart
  - Returns tab: period performance bar chart (1D/1W/1M/3M/6M/YTD/1Y)
  - Risk tab: risk heat map, stop loss proximity chart
  - Dividends tab: income projection chart, yield by position
  - AI Analyst tab: already has 18-section sidebar nav (Phase 2) — needs richer section content
- All-Time Gain showing $0 is a **data issue** (cost basis not in older holdings) — display "N/A" not $0 when cost_basis=0
- Beta showing 0.000 — pull from `risk_management.json` not `portfolio_totals`

**Chart.js CDN already available**: `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js`

### 3C — Watchlist Catalyst Modal
**File**: `reports/command_center.html`
**What it should do**:
- Each watchlist item (currently 12 tickers with thesis + intent) gets an edit pencil icon
- Click opens modal with: ticker, thesis (editable), catalyst notes (editable text area), "AI Suggest" button
- "AI Suggest" calls `POST /api/ai-suggest-catalyst` with ticker + thesis + recent Finviz enrichment
- Server endpoint runs qwen3:1.7b with recent news from enrichment cache + Brave search
- On save: writes back to `data/portfolios/state/watchlist.json`

### 3D — DOCX Visual Enhancement
**File**: `scripts/portfolio_brief_v2.js`
**Current state**: Generates 18-section DOCX with tables and text. 24KB output — basic.
**What's needed**: Embed chart images (from `data/portfolios/charts/*.png`) into the DOCX. The pipeline already generates 17 chart PNGs. The DOCX skill shows how to embed images using `ImageRun`.

---

## KEY FILES AND THEIR ROLES

```
scripts/
  portfolio_orchestrator.py      # Main daily pipeline (10 stages)
  portfolio_weekly_report.py     # Weekly report (6 AI sections, DOCX, Telegram)
  portfolio_ai_analyst.py        # AI analysis (8 sections, qwen3:1.7b weekly)
  portfolio_server.py            # HTTP server port 7777
  finviz_enrichment.py           # Finviz Elite scraper (5 views, 45+ fields)
  portfolio_loader.py            # Loads holdings.json, computes cost basis
  portfolio_performance_history.py # Period returns + daily snapshots
  portfolio_brief_v2.js          # 18-section DOCX generator (Node.js)
  continuous_runner.py           # Trade AI continuous loop (live cycles)
  trade_ai_orchestrator.py       # Trade AI full run (23 stages)

data/portfolios/state/           # ALL STATE FILES (never delete)
  holdings.json                  # Single source of truth — 47 holdings, 4 accounts
  ai_analysis_cache.json         # 8 AI sections (weekly qwen3 run)
  performance_history.json       # 7 periods: 1D,1W,1M,3M,6M,YTD,1Y
  risk_management.json           # Stops, beta, rebalancing orders
  dividend_calendar.json         # 15 payers, $10,351/yr
  ticker_enrichment_cache.json   # 50 tickers, Finviz data (recom_score, analyst_rating)
  retirement_roadmap.json        # Golden Window, Roth ladder
  technical_snapshot.json        # RSI, SMA200 for 14 positions
  snapshots/YYYY-MM-DD.json      # Daily portfolio snapshots

data/portfolios/reports/
  weekly/                        # weekly_YYYY-MM-DD.html + .docx + .json
  charts/                        # 17 PNG charts generated by pipeline

reports/
  command_center.html            # Main dashboard (CC)
  weekly/                        # Served weekly HTML (symlink to above)
  dashboard_live.html            # Latest Trade AI run

linux_launchers/
  run_portfolio.sh               # Daily pipeline
  run_portfolio_weekly.sh        # Weekly (Sunday 8PM systemd timer)
  run_portfolio_monthly.sh       # Monthly (1st of month systemd timer)
```

---

## KNOWN ISSUES / GOTCHAS

1. **Fidelity 401k 0/7 periods** — BY DESIGN. Proprietary fund symbols have no Yahoo price history. Will fix when Omnicom 401k rolls to Schwab in 2027. Do not attempt to fix.

2. **Taxable 1D showing +868%** — Bad CASH-only snapshot from early 2026. The `non_cash_val > 50%` filter in `portfolio_performance_history.py` prevents new bad snapshots. Old ones still exist in `data/portfolios/state/snapshots/`. Can delete snapshots with `total_value < 50000` to fix historical 1D returns.

3. **All-Time Gain = $0 in CC** — `total_gain` in `portfolio_totals` defaults to `total_value` when cost_basis=0. Cost basis only computed for positions with transaction history (Schwab accounts). Fidelity 401k has no transaction history → 0 cost basis for those 10 funds. Display as "N/A" not $0.

4. **Ollama must be idle** — Never run `portfolio_ai_analyst.py` while Trade AI pipeline is running (both call Ollama, 100% CPU, queue deadlock). Weekly Ollama run scheduled Sunday 8PM when Trade AI has stopped.

5. **`think:False` required for qwen3:1.7b** — Without this, model uses all `num_predict` tokens for thinking before any visible output → empty response. Always pass `"think": False` in the JSON payload.

6. **Telegram CHAT_ID is comma-separated** — `TELEGRAM_CHAT_ID=6993102664,8797974247`. Always split on comma and send to each. Both IDs confirmed working.

7. **Server restart required** after editing `portfolio_server.py` or `command_center.html`:
   `fuser -k 7777/tcp && sleep 2 && systemctl --user restart portfolio-server.service`

8. **SCP from Windows**: `scp C:\Users\john\Downloads\FILE.py johnclaw@192.168.50.16:/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`

9. **Weekly report `_load_state` must be at module level** — was accidentally placed inside `run_weekly_report()` twice. Currently correct at module level. Do not move it.

10. **Finviz `recom` field** — stored as percentage string like "1.97%" in raw Finviz data. After Phase 2 fix: `recom_score` (float 1.0-5.0) and `analyst_rating` (text) are computed in `finviz_enrichment.py`. Use these fields, not raw `recom`.

11. **REINVEST transactions for cost basis** — `portfolio_orchestrator.py` now treats `BUY`, `REINVEST`, `REINVEST SHARES`, `REINVEST DIVIDEND` as cost basis additions. This is correct — dividend reinvestments increase cost basis.

---

## JOHN'S FINANCIAL CONTEXT (for AI prompts)

- Age 58 (turns 59 Aug 2026) | DOB 8/21/1967
- Income: SSDI $45,600/yr only | MFS lived-apart filing
- Private disability insurance continues to age 68.5
- **Golden Roth Window: ages 68.5-73 (Feb 2036 – Aug 2040)** — disability ends, before RMDs — lowest bracket for conversions
- Roth conversion 2026: $35K done | Sweet spot $25K/yr (~$3,547 tax) or $50K/yr (~$15,027 tax)
- Target: Zero Traditional IRA by RMD age 73
- SSDI converts to SS retirement at FRA age 67
- Omnicom 401k → Rollover IRA planned 2027
- Conservative risk profile (target beta <0.5) | V position ~12.5% (threshold 15%)
- Annual dividends: $10,351/yr (target $28,000-$34,000/yr = 2.5-3.0%)
- "AI WWIII defense portfolio" thesis for taxable account — respect this in all analysis

---

## CLAUDE CODE HANDOFF PROMPT

Use this prompt when starting Claude Code on MS-01:

```
You are continuing the Portfolio Intelligence v1.2 build for John W. Whiting.
Project root: /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
Read the handoff doc first: cat docs/CLAUDE_CODE_HANDOFF.md

WHAT'S DONE: Phase 1 (data foundation) and Phase 2 (weekly intelligence) are complete and working.
Weekly report runs Sunday 8PM, sends Telegram summary + DOCX attachment with 6 AI sections.

YOUR TASKS (Phase 3):
1. BUILD scripts/portfolio_monthly_report.py — reads last 4 weekly JSONs + all state files, 
   uses Claude Sonnet for deep analysis, outputs DOCX + Telegram. Template in HANDOFF.md.
2. ADD Chart.js interactive charts to command_center.html key tabs (holdings donut, 
   returns bar chart, risk heat map). Chart PNGs already at data/portfolios/charts/*.png.
3. ADD watchlist catalyst modal — edit pencil per ticker, AI Suggest button using 
   qwen3:1.7b + Brave search, saves to data/portfolios/state/watchlist.json.

CRITICAL RULES:
- Always source .venv before running Python
- Never edit holdings.json directly
- After CC changes: fuser -k 7777/tcp && systemctl --user restart portfolio-server.service
- think:False required for ALL qwen3:1.7b Ollama calls
- Test: python3 -c "import ast; ast.parse(open('scripts/FILE.py').read()); print('OK')"
- Check memory notes for full financial context and system state
```

---

## VALIDATION COMMANDS

```bash
# State check (run before any deployment)
python3 -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'],len(d.get('holdings',[])))"
# Expected: ~1204000 47

# Weekly report test
python3 scripts/portfolio_weekly_report.py --project-root . 2>&1 | head -20

# Full weekly pipeline
bash linux_launchers/run_portfolio_weekly.sh 2>&1 | tail -20

# Server health
curl http://192.168.50.16:7777/api/health

# Ollama test
python3 -c "import requests; r=requests.post('http://127.0.0.1:11434/api/generate', json={'model':'qwen3:1.7b','stream':False,'prompt':'test','think':False,'options':{'num_predict':20}},timeout=30); print(r.json().get('response','EMPTY'))"
```
