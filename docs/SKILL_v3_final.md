---
name: trade-ai-v12
description: >
  Local Python trade intelligence pipeline for daily scalp trading AND portfolio
  management. Use this skill when the user wants to: run the Trade AI pipeline,
  check recent run results, interpret scores or catalysts for specific tickers,
  understand why a ticker is GO or WAIT, read the dashboard, configure screeners
  or weights, troubleshoot errors, schedule runs, view portfolio analytics, check
  performance history, retirement planning, risk management, tax analysis,
  rebalancing orders, Fidelity 401k fund exchanges, import account data, or get
  help with any aspect of the Trade AI v12 or Portfolio Intelligence v1.2 system.
  Also use when the user says "run trade ai", "check my screeners",
  "what's moving this morning", "show me the results", "check my portfolio",
  "run the monthly analysis", "import my schwab csv", "update fidelity", or any variation.
---

# Trade AI v12 + Portfolio Intelligence v1.2 — SKILL v3.1
## Last updated: April 11, 2026 | Command Center v47+patch | Architecture v49

Two integrated systems on LENOVO_AURA (Windows):
- **Trade AI v12** — daily pre-market scalp trading pipeline (23 stages)
- **Portfolio Intelligence v1.2** — 4-account portfolio analytics, import system, AI analyst

Project root: `C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\`
Dashboard: `http://localhost:7777/reports/command_center.html`

---

## ⛔ IRON RULES — NEVER VIOLATE THESE

### Rule 1: holdings.json is the single source of truth
- **NEVER** zero it, overwrite it with fewer than 50% of previous total value, or manually edit it
- **NEVER** run `run_portfolio.bat` if holdings.json total is $0
- The sanity check in `portfolio_loader.py` aborts if new total < 50% of previous

### Rule 2: YAML has zero file references
`portfolio_accounts.yaml` contains account config, targets, and fund lists ONLY.
No `positions_file`, `transactions_file`, or `input_file` keys.

### Rule 3: The server owns port 7777
- **NEVER** `taskkill /f /im python.exe` — kills all Python including Trade AI
- Restart: `restart_server.bat`

### Rule 4: Read every file before touching it
- `ast.parse(src)` on every Python file after any change
- Check JS brace balance after any HTML change
- Never change a working file to "improve" it during a focused session

### Rule 5: Multi-line Python never works in CMD
All Python fix commands in CMD must be single-line with semicolons.

### Rule 6: Always sandbox-validate before production
Test parsers against real uploaded files. Never declare done until it passes a real data test.

### Rule 7: Read forensic_files.md FIRST — every session
No exceptions. It documents every file's status. If a file is LEGACY, do not modify it.

### Rule 8: Import modal is the ONLY data entry point
`data/portfolios/input/` is **LEGACY**. The pipeline does NOT read from it.
Holdings are written ONLY by the Import modal → /api/import → portfolio_server.py.
- **Never** write Python scripts that write directly to holdings.json — wrong schema
- **Never** POST test payloads to /api/import during debugging — overwrites live data

### Rule 9: Schwab dropdown must match the CSV
The Import modal dropdown stays on the last-used account. Change it BEFORE dropping each file.
Dropping under the wrong account silently overwrites the wrong account's holdings.

---

## 📋 FORENSIC FILE PROTOCOL — CHECK BEFORE TOUCHING ANYTHING

`forensic_files.md` lives in the project root. Read it before every session.

### Where new files go
| Type | Destination |
|---|---|
| Claude-delivered zip | `sandbox\deploy_zips\` first — extract, verify, delete zip |
| One-time fix scripts | `sandbox\` — run, then delete |
| Documentation | `docs\` — never in project root |
| Superseded CC versions | `sandbox\old_cc\` — delete after 60 days |
| **Never** | Zip files or scripts in project root |

---

## ⚠️ BASELINE PROTECTION

**Confirmed working as of April 11, 2026:**

| Component | State | Do Not Change |
|---|---|---|
| `portfolio_loader.py` | v3 — reprices from holdings.json, sanity check active | The 50% abort gate |
| `portfolio_server.py` | v2 — /api/import active, /api/clear-pending active | Port 7777 |
| `command_center.html` | v47 + Fidelity CSV patch — Import modal, PDF+CSV parsers | The FUND_MAP keys |
| `run_portfolio.bat` | Calls /api/clear-pending after pipeline | The clear-pending line |
| `portfolio_accounts.yaml` | Clean — zero file references | No file refs allowed |
| `holdings.json` | $1,181,350 · 4 accounts · 47 holdings | The sanity check protects it |
| `continuous_runner.py` | Starts 04:00, FULL on startup | 04:00 start + startup FULL |
| Task Scheduler path | Hardcoded absolute path | Never use %ROOT% |

---

## PORTFOLIO INTELLIGENCE v1.2

### Architecture (v49, April 2026)

```
DATA FLOW
─────────────────────────────────────────────────────────────
IMPORT (user-triggered via Command Center):
  Browser → Drop CSV or PDF → JS parses in browser
  → POST /api/import → portfolio_server.py
  → Writes to holdings.json
  → Sets pending_pipeline_run = true
  → Pending banner appears in dashboard

DAILY PIPELINE (Task Scheduler 7AM or manual):
  run_portfolio.bat
  → portfolio_orchestrator.py
  → portfolio_loader.py reads holdings.json (shares from last import)
  → Reprices all non-Fidelity positions from Yahoo price cache
  → Updates market values and totals
  → Sanity check: if new total < 50% of previous → ABORT, keep old state
  → Saves updated holdings.json
  → Generates dashboard, charts, AI analysis
  → Calls POST /api/clear-pending → banner disappears
─────────────────────────────────────────────────────────────
```

### Running the pipeline
```cmd
run_portfolio.bat                    :: Daily (also via Task Scheduler 7AM)
run_portfolio_monthly.bat            :: Monthly AI refresh + YAML review
run_price_cache.bat                  :: Sunday 7PM — refresh Yahoo price cache
del data\portfolios\state\ai_analysis_cache.json  :: Force AI re-analysis
```

### Key files
| File | Purpose |
|---|---|
| `data/portfolios/state/holdings.json` | **Single source of truth** — all account holdings, totals |
| `assets/portfolio_accounts.yaml` | Account config, targets, ETF sectors (no file refs) |
| `.env` | All API keys |
| `data/portfolios/state/price_cache.json` | Yahoo price history (75 symbols, Jan 2020→today) |
| `scripts/portfolio_loader.py` | v3 — reads holdings.json, reprices, sanity check |
| `scripts/portfolio_server.py` | v2 — serves dashboard, handles /api/import |
| `reports/command_center.html` | v47+patch — unified dashboard with Import modal |

---

## IMPORT DATA MODAL (Command Center — April 11, 2026)

### How to access
Click **📥 IMPORT DATA** in the Alerts & Actions zone (right side of Command Center).

### Tab 1: Schwab Positions
- **Source:** Schwab → Accounts → select account → Positions → Export
- **⚠️ CRITICAL:** Change the dropdown to the correct account BEFORE dropping the file. It stays on the last-used account.
- **What it does:** Replaces all holdings for that account in holdings.json
- **After import:** Yellow banner appears — run pipeline to recompute analytics

### Tab 2: Schwab Transactions
- **Source:** Schwab → History → select account → Export
- **After import:** Trade journal updated, no pipeline run needed

### Tab 3: Fidelity CSV *(preferred — added April 11, 2026)*
- **Source:** `digital.fidelity.com/ftgw/digital/portfolio/positions` → gear icon ⚙ (top-right of table) → Download
- **File name:** `Portfolio_Positions_MMM-DD-YYYY.csv`
- **CUSIP map:** 7 institutional funds resolved via hardcoded map in parseFidelityCSV(). 3 real tickers (ABSZX, TILCX, VFTNX) are Yahoo-priceable. Other 7 use CSV price as-is.
- **Price warning:** Institutional funds have different NAVs than any Yahoo ticker (FID-CONTRA-F = $55.99 Fidelity vs ~$21 Yahoo). NEVER reprice these from Yahoo.
- **After import:** Yellow banner appears — run pipeline

### Tab 4: Fidelity PDF *(still works — use if CSV unavailable)*
- **Source:** NetBenefits → Summary → Statements → Download or Print This Statement (PDF)
- **Parser:** Identifies 10 funds by `before|after` context lines. SS-SMMD key = `SS RSL|II`
- **After import:** Yellow banner appears — run pipeline

### Complete 4-account import workflow
```
1. Import Data → Fidelity CSV tab → drop Portfolio_Positions_*.csv → Import
2. Schwab Positions tab → dropdown = Rollover IRA → drop file → Import
3. Schwab Positions tab → dropdown = Roth IRA → drop file → Import
4. Schwab Positions tab → dropdown = Individual → drop file → Import
5. run_portfolio.bat
6. Verify total ~$1,177,000+ across all 4 accounts
```

### Pending banner
After any import:
> ⚠ Holdings imported (account) — pipeline not yet run · **Run Now**

---

## HOLDINGS.JSON PROTECTION

### Recovery procedure (if holdings.json is corrupted)
**Step 1:** Check current state:
```cmd
venv\Scripts\python.exe -c "import json;c=json.load(open('data/portfolios/state/holdings.json'));print('Total: $'+str(round(c['portfolio_totals']['total_value'])));[print(k+':',round(v.get('total_value',0))) for k,v in c['account_summaries'].items()]"
```

**Step 2:** If total < $1,100,000 — DO NOT run pipeline. Import fresh data first.

**Step 3:** Import via Command Center → Import Data modal (all 4 accounts per workflow above)

**Step 4:** After all 4 accounts imported → run_portfolio.bat

---

## FIDELITY 401K DATA

### Current holdings (as of April 11, 2026)
| Symbol | Name | Shares | Price | Value |
|---|---|---|---|---|
| FID-CONTRA-F | FID Contra Pool CL F | 2,806.849 | $55.99 | $157,155 |
| SP500-D | SP 500 Index PL CL D | 161.277 | $324.74 | $52,373 |
| SS-SMMD | SS RSL Smmdcp Idx II | 2,451.548 | $21.32 | $52,269 |
| JPM-LGCG | JPM Lg CP Grth CF-A | 429.081 | $121.49 | $52,129 |
| TILCX | TRP LargeCap Val I | 2,148.588 | $24.30 | $52,211 |
| VANG-FTSE-SOC | Vang Ftse SOC Idx IS | 1,137.475 | $45.74 | $52,028 |
| WM-BLAIR | WM Blair Smmidcp GR | 604.337 | $43.13 | $26,067 |
| FID-DIVINTL | FID Div Intl PL CL C | 1,014.710 | $25.58 | $25,956 |
| SS-GACEQ | SS Gaceq Exus Idx II | 1,291.581 | $19.97 | $25,795 |
| AB-DISC-Z | AB Disc Value Z | 1,199.288 | $21.23 | $25,461 |
| **TOTAL** | | | | **$521,445** |

### Yahoo repricing rules
- ABSZX, TILCX, VFTNX: real tickers — Yahoo reprices correctly on every pipeline run
- All other 7 funds: institutional share classes — Yahoo price is WRONG. CSV price used as-is.

---

## COMMON FAILURE MODES AND EXACT FIXES

### "Pipeline shows $0 or missing accounts"
**Cause:** holdings.json was zeroed, or sanity check aborted
**Fix:** Import fresh data via Import modal → then run_portfolio.bat

### "Roth/Taxable shows $0 after import"
**Cause:** Schwab dropdown was not changed before dropping the file. All imports went to Rollover IRA.
**Fix:** Re-import each account individually. Change dropdown to correct account FIRST, then drop.

### "PermissionError: [WinError 10013] port 7777"
**Fix:** `restart_server.bat`

### "Fidelity CSV parse error: No funds found"
**Cause:** Wrong file dropped, or account number is not 74608 in CSV
**Fix:** Verify file is `Portfolio_Positions_*.csv` from gear icon download. Check account 74608 is present.

### "Fidelity shows wrong total (too low)"
**Cause:** Yahoo cache prices contaminated Fidelity institutional fund values
**Fix:** Re-import via Fidelity CSV tab or Fidelity PDF tab

### "Pending banner not clearing after pipeline"
**Fix:** Manually POST to http://localhost:7777/api/clear-pending

### "run_portfolio.bat fails with division by zero"
**Cause:** holdings.json is empty
**Fix:** Import data first, then run pipeline.

---

## PORTFOLIO SERVER

### Endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Server health check + version |
| `/api/import` | POST | Write position data to holdings.json |
| `/api/import-transactions` | POST | Append transactions |
| `/api/clear-pending` | POST | Clear pending banner flag |
| `/api/run-portfolio` | POST | Trigger run_portfolio.bat |

---

## TRADE AI v12

### Running
```cmd
:: Test run (any time, no alerts, no cost)
venv\Scripts\python.exe scripts\trade_ai_orchestrator.py --run-label 0900 --skip-market-check --no-alerts --no-llm

:: Standard run
venv\Scripts\python.exe scripts\trade_ai_orchestrator.py --run-label 0700

:: Continuous runner
launchers\run_continuous.bat
```

### Schedule (baseline April 2026)
```
04:00–06:00: FULL run every 30 min
06:00–09:00: LIVE every 15 min
Startup: FULL run fires immediately on launch
```

### Task Scheduler
```
TradeAIContinuous — Mon-Fri 4:00 AM
cmd.exe /c "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\launchers\run_continuous.bat"
```

---

## SCORING MODEL (v12, max 55 pts)

| Pillar | Max | Trigger |
|---|---|---|
| Catalyst | 15 | FDA, earnings beat, M&A, material 8-K |
| RVOL | 12 | ≥8x = max; ≥5x = near max |
| Price Action | 10 | Gap% + change% + RVOL alignment |
| Float | 8 | Under 5M = max; over 100M = 0 |
| Price Range | 5 | $2–$10 sweet spot |
| Sector Momentum | 5 | Sector ETF in top 3 leaders |

GO ≥40 · WAIT 30–39 · AVOID <30 · A+ ≥48 → Sonnet trade plan

---

## VALIDATION CHECKLIST — RUN AFTER EVERY CHANGE

### Python file changed
```python
import ast; ast.parse(open('scripts/portfolio_loader.py').read()); print('OK')
```

### HTML/JS changed
```python
import re; src=open('reports/command_center.html').read()
scripts=re.findall(r'<script[^>]*>(.*?)</script>',src,re.DOTALL)
js='\n'.join(scripts); print('Brace balance:',js.count('{')-js.count('}'))
```

### After any portfolio change
1. `http://localhost:7777/api/health` → `{"version": "2.0"}`
2. All 4 accounts present and >$40K each
3. Total between $1,100,000 and $1,300,000
4. No console errors (F12 → Console)

### After run_portfolio.bat
1. Output shows all 4 accounts with holdings counts
2. Total between $1,100,000 and $1,300,000
3. No "division by zero" or "SAFETY ABORT" in output
4. Pending banner gone from dashboard

---

## ROTH CONVERSION STRATEGY — AI ANALYST PARAMETERS

| Parameter | Value | Why it matters |
|---|---|---|
| IRMAA safe MAGI ceiling | $101,000 | Never exceed — $7,128/yr penalty |
| Base MAGI (typical loss year) | ~$25,090 | SSDI + Sched C loss + dividends |
| Conversion capacity (loss year) | ~$75,910 | $101K - $25K base |
| Phase 3 (Golden Window) annual | $60,000 | 12% bracket, disability ended |
| YTD converted 2026 | $35,000 | Update after each conversion |

### DRIP policy
- **Schwab Taxable ...469:** OFF — dividends taxable, take as cash
- **Schwab Roth ...415:** ON — compounds tax-free forever
- **Rollover IRA + Fidelity:** ON — tax-deferred, DRIP fine

---

## KNOWN ISSUES (April 11, 2026)

| Item | Status | Priority |
|---|---|---|
| portfolio_options.json 404 | Non-blocking — generated by monthly pipeline | LOW |
| CDEX cost basis unknown | Call Schwab ...469 for original purchase price | MEDIUM |
| NY $20K IRA exemption | Confirm with CPA if applies to Roth conversions | MEDIUM |
| Polygon API 404 | Degraded — Finviz News + Yahoo fallback active | LOW |
| FMP API 403 | Degraded — endpoint discontinued | LOW |
| Finnhub 422 | Degraded — date param issue | LOW |
| MS-01 Mini PC | Purchased April 2026 — OpenClaw setup pending | MEDIUM |
| Omnicom 401k → Rollover IRA | Planned 2027 | LOW |

---

## CURRENT PORTFOLIO BASELINE (April 11, 2026)

| Account | Total | Holdings | Source |
|---|---|---|---|
| Fidelity 401k | $521,445 | 10 funds | Fidelity CSV import |
| Schwab Rollover IRA | $541,877 | 12 | Schwab CSV import |
| Schwab Roth IRA | $40,907 | 3 | Schwab CSV import |
| Schwab Taxable | $73,096 | 22 | Schwab CSV import |
| **Total (post-reprice)** | **$1,181,350** | **47** | Pipeline run April 11 |
