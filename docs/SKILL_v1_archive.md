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

# Trade AI v12 + Portfolio Intelligence v1.2 — SKILL v3.0
## Last updated: April 10, 2026 | Command Center v48 | Architecture v49

Two integrated systems on LENOVO_AURA (Windows):
- **Trade AI v12** — daily pre-market scalp trading pipeline (23 stages)
- **Portfolio Intelligence v1.2** — 4-account portfolio analytics, import system, AI analyst

Project root: `C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\`
Dashboard: `http://localhost:7777/reports/command_center.html`

---

## ⛔ IRON RULES — NEVER VIOLATE THESE

These rules exist because violating them caused real data loss during the April 10 session.

### Rule 1: holdings.json is the single source of truth
- **NEVER** zero it by removing YAML file references without a tested replacement path
- **NEVER** run `run_portfolio.bat` if holdings.json was manually edited to $0
- **NEVER** overwrite it with data that represents fewer than 50% of previous total value
- The sanity check in `portfolio_loader.py` aborts automatically if new total < 50% of previous

### Rule 2: YAML has zero file references
`portfolio_accounts.yaml` contains account config, targets, and fund lists ONLY.
No `positions_file`, `transactions_file`, or `input_file` keys.
Share counts come from holdings.json (written by Import modal). Pipeline reprices from Yahoo cache.

### Rule 3: The server owns port 7777
- **NEVER** `taskkill /f /im python.exe` — kills all Python including Trade AI
- To restart server: run `restart_server.bat` (finds PID, kills safely, restarts)
- If restart_server.bat fails → open Admin PowerShell → `taskkill /F /PID <pid>`

### Rule 4: Read every file before touching it
- `ast.parse(src)` on every Python file after any change
- Check JS brace balance (`{` count == `}` count) after any HTML change
- Verify in browser against live dashboard before declaring done
- Never change a working file to "improve" it during a focused session

### Rule 5: Multi-line Python never works in CMD
All Python fix commands in CMD must be single-line with semicolons:
```cmd
venv\Scripts\python.exe -c "f='file.py';s=open(f).read();print(s[:100])"
```
Never attempt multi-line Python blocks in a CMD window.

### Rule 6: Always sandbox-validate before production
- PDF parsers: test against actual uploaded file before writing production code
- CSV parsers: test with real Schwab CSV format including quoted comma values
- Never declare a fix done until it passes a real data test

---


---

## 📋 FORENSIC FILE PROTOCOL — CHECK BEFORE TOUCHING ANYTHING

`forensic_files.md` lives in the project root. It documents every file's status, purpose, and size. It is the pre-flight checklist for every session.

### At the start of every session
```
1. Fetch the file: fetch('/scripts/portfolio_loader.py') or check forensic_files.md
2. Confirm the file status is ACTIVE — not LEGACY, ARCHIVE, or DELETE
3. Check the last-modified date — is this the version you expect?
```

### Before modifying any file
Search `forensic_files.md` for the filename. Read:
- **Status** — is it ACTIVE? If LEGACY or DELETE, do not modify — discuss first
- **Purpose** — do you understand what it does?
- **Note** — any warnings or constraints

### After modifying any file
Update `forensic_files.md`:
- Change the size field if the file grew or shrunk significantly
- Add an entry to the Change Log at the bottom with: date, what changed, who

### Where new files go
| Type | Destination |
|---|---|
| Claude-delivered zip | `sandbox\deploy_zips\` first — extract, verify, then delete zip |
| One-time fix scripts | `sandbox\` — run, then delete |
| Documentation | `docs\` — never in project root |
| Superseded CC versions | `sandbox\old_cc\` — delete after 60 days |
| **Never** | Zip files in project root |

### Project directory structure (as of April 10, 2026)
```
trade-ai-v12-rebuild├── forensic_files.md         ← Read this first
├── docs\                     ← All documentation
├── sandbox\                  ← Temporary work area (disposable)
│   ├── old_cc\               ← Archived Command Center versions
│   └── deploy_zips\          ← Claude zips land here
├── assets\                   ← portfolio_accounts.yaml (clean, no file refs)
├── data\portfolios\state\    ← Live state (holdings.json = sacred)
├── reports\                  ← Served at localhost:7777/reports/
├── scripts\                  ← All Python (handle with care)
├── launchers\                ← Task Scheduler entry points
└── logs\                     ← Auto-generated, archive weekly
```

## ⚠️ BASELINE PROTECTION

**Confirmed working as of April 10, 2026:**

| Component | State | Do Not Change |
|---|---|---|
| `portfolio_loader.py` | v3 — reprices from holdings.json, sanity check active | The 50% abort gate |
| `portfolio_server.py` | v2 — /api/import active, /api/clear-pending active | Port 7777 |
| `command_center.html` | v48 — Import modal, Fidelity PDF parser, pending banner | The FUND_MAP keys |
| `run_portfolio.bat` | Calls /api/clear-pending after pipeline | The clear-pending line |
| `portfolio_accounts.yaml` | Clean — zero file references | No file refs allowed |
| `holdings.json` | $1,179,224 · 4 accounts · 50 holdings | The sanity check protects it |
| `continuous_runner.py` | Starts 04:00, FULL on startup | 04:00 start + startup FULL |
| Task Scheduler path | Hardcoded absolute path | Never use %ROOT% |

---

## PORTFOLIO INTELLIGENCE v1.2

### Architecture (v49, April 10, 2026)

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

INTRADAY (market hours, every 60 min):
  portfolio_live_monitor.py
  → Reprices from Yahoo
  → Telegram alerts if thresholds hit
  → Does NOT touch share counts

MONTHLY (1st of month):
  run_portfolio_monthly.bat
  → Full pipeline + AI analysis + YAML Config Advisor (Opus)
─────────────────────────────────────────────────────────────
```

### Running the pipeline
```cmd
run_portfolio.bat                    :: Daily (also via Task Scheduler 7AM)
run_portfolio_monthly.bat            :: Monthly AI refresh + YAML review
run_price_cache.bat                  :: Sunday 7PM — refresh Yahoo price cache
del data\portfolios\state\ai_analysis_cache.json  :: Force AI re-analysis
```

### Task Scheduler
| Task | Schedule | Bat File |
|---|---|---|
| Portfolio Daily | Mon–Fri 7:00 AM | `run_portfolio.bat` |
| Portfolio Monthly | 1st of month 7:05 AM | `run_portfolio_monthly.bat` |
| PortfolioWeekly | Sunday 8:00 PM | `run_portfolio_weekly.bat` |
| PortfolioPriceCache | Sunday 7:00 PM | `run_price_cache.bat` |

### Key files
| File | Purpose |
|---|---|
| `data/portfolios/state/holdings.json` | **Single source of truth** — all account holdings, totals |
| `assets/portfolio_accounts.yaml` | Account config, targets, ETF sectors (no file refs) |
| `.env` | All API keys |
| `data/portfolios/state/price_cache.json` | Yahoo price history (75 symbols, Jan 2020→today) |
| `data/portfolios/state/ai_analysis_cache.json` | Monthly AI analysis cache |
| `data/portfolios/state/technical_snapshot.json` | Finviz technical data |
| `scripts/portfolio_loader.py` | v3 — reads holdings.json, reprices, sanity check |
| `scripts/portfolio_server.py` | v2 — serves dashboard, handles /api/import |
| `reports/command_center.html` | v48 — unified dashboard with Import modal |

---

## IMPORT DATA MODAL (Command Center v48)

### How to access
Click **📥 IMPORT DATA** in the Alerts & Actions zone (right side of Command Center).

### Tab 1: Schwab Positions
- **Source:** Schwab → Accounts → select account → Positions → Export
- **Select account:** dropdown in modal (Rollover IRA, Roth IRA, Taxable)
- **What it does:** Replaces all holdings for that account in holdings.json
- **Referential integrity:** Refuses import if CSV date is older than current data
- **After import:** Yellow banner appears — run pipeline to recompute analytics

### Tab 2: Schwab Transactions
- **Source:** Schwab → History → select account → Export
- **Deduplication:** date + action + symbol + quantity — only new transactions added
- **After import:** Trade journal updated, no pipeline run needed

### Tab 3: Fidelity PDF
- **Source:** NetBenefits → Summary → Statements → Download or Print This Statement (PDF)
- **Parser:** Identifies 10 funds by `before|after` context lines around the data row
- **Critical key:** SS-SMMD uses key `SS RSL|II` (not `SS RSL|Smmdcp Idx II`) because PDF.js merges `Smmdcp Idx` into the numbers line
- **Fallback:** BEFORE_MAP matches on the line before numbers alone — robust against PDF.js rendering variations
- **After import:** Yellow banner appears — run pipeline to recompute analytics

### Pending banner
After any import, the dashboard shows:
> ⚠ Holdings imported (account) — pipeline not yet run · prices & analysis may be stale · **Run Now**

"Run Now" triggers `run_portfolio.bat` via `/api/run-portfolio`. Banner clears automatically when pipeline completes.

---

## PORTFOLIO SERVER

### Starting and stopping
```cmd
:: Start (normal)
venv\Scripts\python.exe scripts\portfolio_server.py

:: Safe restart (handles port 7777 PID)
restart_server.bat

:: Verify running
:: Open http://localhost:7777/api/health
:: Should return: {"ok": true, "version": "2.0", ...}
```

### Endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Server health check + version |
| `/api/import` | POST | Write position data to holdings.json |
| `/api/import-transactions` | POST | Append transactions to trade_journal.json |
| `/api/clear-pending` | POST | Clear pending_pipeline_run flag |
| `/api/run-portfolio` | POST | Trigger run_portfolio.bat |
| `/api/run-trade-ai` | POST | Trigger run_1000.bat |

### If server fails to start (WinError 10013 — port in use)
```cmd
:: Option 1: Admin PowerShell (fastest)
taskkill /F /PID <pid from netstat>

:: Option 2: restart_server.bat (auto-finds PID)
restart_server.bat

:: Option 3: Find the CMD window running portfolio_server.py → close with X
```

---

## HOLDINGS.JSON PROTECTION

### The sanity check (portfolio_loader.py)
Every pipeline run checks: if new total < 50% of previous total → abort, keep old state, print warning.
This prevents the most destructive failure mode: empty CSV + missing YAML file refs → $0 portfolio.

### Recovery procedure (if holdings.json is corrupted)
**Step 1:** Check what's in it:
```cmd
venv\Scripts\python.exe -c "import json;c=json.load(open('data/portfolios/state/holdings.json'));print('Total: $'+str(round(c['portfolio_totals']['total_value'])));[print(k+':',round(v.get('total_value',0))) for k,v in c['account_summaries'].items()]"
```

**Step 2:** If total < $1,100,000 — DO NOT run pipeline yet. Import fresh data first.

**Step 3:** Import via Command Center → Import Data modal:
- Schwab Positions tab → drop latest CSV for each Schwab account
- Fidelity PDF tab → drop latest NetBenefits statement

**Step 4:** After all 4 accounts imported → run_portfolio.bat

### Manually writing Fidelity data (emergency fallback)
If server is down and you can't use the Import modal:
```cmd
venv\Scripts\python.exe -c "import json,pathlib;p=pathlib.Path('data/portfolios/state/holdings.json');c=json.loads(p.read_text());c['holdings']=[h for h in c.get('holdings',[]) if h.get('account')!='fidelity_401k']+[HOLDINGS_LIST];c['account_summaries']['fidelity_401k']['total_value']=519361.68;t=sum(a.get('total_value',0) for a in c['account_summaries'].values());c['portfolio_totals']['total_value']=t;p.write_text(json.dumps(c,indent=2));print('OK $'+str(round(t)))"
```
See Day 2 Addendum v22 Section D for the full HOLDINGS_LIST.

---

## FIDELITY 401K DATA

### Current holdings (as of April 8, 2026 statement)
| Symbol | Name | Shares | Price | Value |
|---|---|---|---|---|
| FID-CONTRA-F | FID Contra Pool CL F | 2,806.849 | $55.38 | $155,443 |
| SS-SMMD | SS RSL Smmdcp Idx II | 2,451.548 | $21.40 | $52,468 |
| TRP-LVAL | TRP LargeCap Val I | 2,148.588 | $24.33 | $52,275 |
| SP500-D | SP 500 Index PL CL D | 161.277 | $323.06 | $52,102 |
| JPM-LGCG | JPM Lg CP Grth CF-A | 429.081 | $120.68 | $51,782 |
| VANG-FTSE-SOC | Vang Ftse SOC Idx IS | 1,137.475 | $45.45 | $51,698 |
| WM-BLAIR | WM Blair Smmidcp GR | 604.337 | $43.71 | $26,416 |
| FID-DIVINTL | FID Div Intl PL CL C | 1,014.710 | $25.54 | $25,916 |
| SS-GACEQ | SS Gaceq Exus Idx II | 1,291.581 | $19.91 | $25,717 |
| AB-DISC-Z | AB Disc Value Z | 1,199.288 | $21.30 | $25,545 |
| **TOTAL** | | | | **$519,362** |

### Update procedure
1. Download from NetBenefits → Summary → Statements → Print/Download This Statement (PDF)
2. Open Command Center → Import Data → Fidelity PDF tab → drop PDF
3. Verify: 10 funds, correct total → click Import
4. Run pipeline

### Price warning
Yahoo Finance prices for Fidelity institutional funds are WRONG for NAV calculations.
Always use prices from the Fidelity statement. The daily pipeline uses Yahoo only for
Schwab positions — Fidelity fund prices in holdings.json come from the last PDF import.

---

## COMMON FAILURE MODES AND EXACT FIXES

### "Pipeline shows $0 or missing accounts"
**Cause:** holdings.json was zeroed, or sanity check aborted a bad run
**Diagnosis:**
```cmd
venv\Scripts\python.exe -c "import json;c=json.load(open('data/portfolios/state/holdings.json'));print(c['portfolio_totals'])"
```
**Fix:** Import fresh data via Import modal → then run_portfolio.bat

### "PermissionError: [WinError 10013] port 7777"
**Cause:** Old server process still holds port 7777
**Fix:** `restart_server.bat` — or Admin PowerShell: `taskkill /F /PID <pid>`

### "PDF parse error: No fund holdings found"
**Cause:** Browser cached old parser version
**Fix:** Close browser tab completely → open fresh → retry

### "Pending banner not clearing after pipeline"
**Cause:** Server was down when run_portfolio.bat ran — the clear-pending call silently failed
**Fix:** Banner clears on next page refresh once pipeline completes. Or manually: `POST http://localhost:7777/api/clear-pending`

### "Dashboard shows stale data after import"
**Cause:** Import only writes raw share counts — pipeline must run to reprice and recompute analytics
**Fix:** Click "Run Now" in the pending banner, or run `run_portfolio.bat`

### "Fidelity shows wrong total (too low)"
**Cause:** Yahoo cache prices used instead of Fidelity NAV prices (portfolio_loader reprices Fidelity funds via Yahoo)
**Diagnosis:** Check `holdings.json` — if Fidelity prices show ~$50 for FID-CONTRA-F instead of ~$55, that's Yahoo contamination
**Fix:** Re-import the Fidelity PDF via Import modal → Fidelity PDF tab

### "run_portfolio.bat fails with division by zero"
**Cause:** portfolio total is $0 — holdings.json is empty
**Fix:** Import data first, then run pipeline. Do NOT run pipeline on empty holdings.

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
09:00–10:00: LIVE every 10 min
10:00–11:00: LIVE every 15 min
Startup: FULL run fires immediately on launch (catches missed 4AM)
```

### Task Scheduler
```
TradeAIContinuous — Mon-Fri 4:00 AM
cmd.exe /c "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\launchers\run_continuous.bat"
```
Diagnose: `schtasks /query /tn "TradeAIContinuous" /fo LIST /v | findstr "Task To Run\|Last Result\|Next Run"`

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
2. Dashboard total within $50K of $1,179,224
3. Fidelity 401k shows ~$519,362
4. No console errors (F12 → Console)

### After run_portfolio.bat
1. Output shows all 4 accounts with holdings counts
2. Total between $1,100,000 and $1,300,000
3. No "division by zero" or "SAFETY ABORT" in output
4. Pending banner gone from dashboard

---

## FILE DELIVERY RULES

```python
# BAT/PS1 files: always write with Python wb mode, verify CRLF
with open('file.bat', 'wb') as f:
    f.write(content.encode('utf-8'))  # content must use \r\n line endings
assert b'\r\n' in open('file.bat','rb').read(), "CRLF missing"

# Always deliver as zip, list all files, verify before sharing
import zipfile
with zipfile.ZipFile('deploy.zip','w') as zf:
    zf.write('file.bat')
# Spot-check key strings inside zip before presenting
```

---

## ROTH CONVERSION STRATEGY — AI ANALYST PARAMETERS

All parameters live in `assets/portfolio_accounts.yaml` under `roth_conversion_strategy` and `tax_intelligence`. The AI analyst reads these every monthly run.

### Annual update checklist (each January)
- `ytd_conversions_2026` → reset to 0, update year key
- `current_age` → increment
- Tax bracket thresholds → update from IRS announcement
- `mortgage_interest_annual` → update from Form 1098 box 1
- `property_tax_annual` → update from Schedule A actuals

### Update after every conversion
```yaml
roth_conversion_strategy:
  conversion:
    ytd_conversions_2026: 40000   # ← update this number
```

### Key numbers to never forget
| Parameter | Value | Why it matters |
|---|---|---|
| IRMAA safe MAGI ceiling | $101,000 | Never exceed — $7,128/yr penalty |
| Base MAGI (typical loss year) | ~$25,090 | SSDI + Sched C loss + dividends |
| Conversion capacity (loss year) | ~$75,910 | $101K - $25K base |
| Phase 2 recommended annual | $40,000 | Conservative under IRMAA ceiling |
| Phase 3 (Golden Window) annual | $60,000 | 12% bracket, disability ended |
| YTD converted 2026 | $40,000 | Already done — ~$2K remaining this year |

### DRIP policy (in YAML — do not change without reason)
- **Schwab Taxable ...469:** OFF — dividends taxable regardless, take as cash for control
- **Schwab Roth ...415:** ON — dividends compound tax-free forever, never turn off
- **Rollover IRA + Fidelity:** ON — tax-deferred, DRIP fine

### Monthly report requirements (from tax_intelligence section)
The AI analyst must include in every monthly brief:
1. YTD realized gains/losses by ticker (taxable account only)
2. YTD dividend income from taxable account
3. Running 2026 investment income total
4. How gains/losses affect remaining IRMAA conversion capacity
5. CDEX pending flag — show every month until cost basis confirmed
6. Current harvest candidates with updated prices

### CDEX action item (persistent until resolved)
CDEX is in Schwab taxable ...469. SEC revoked 05/18/2018.
Cost basis unknown. Every monthly report must flag:
`"⚠️ CDEX cost basis unknown — call Schwab ...469 for original purchase price to calculate harvestable loss"`

## KNOWN ISSUES (April 10, 2026)

| Item | Status | Priority |
|---|---|---|
| portfolio_options.json 404 | Non-blocking — generated by monthly pipeline | LOW |
| CDEX cost basis unknown | Call Schwab ...469 — needed for tax loss harvest | MEDIUM |
| DRIP on in taxable account | Turn DRIP OFF in Schwab ...469 — call Schwab | MEDIUM |
| NY $20K IRA exemption | Confirm with CPA if applies to Roth conversions | MEDIUM |
| Polygon API 404 | Degraded — Finviz News + Yahoo fallback | LOW |
| FMP API 403 | Degraded — endpoint discontinued | LOW |
| Finnhub 422 | Degraded — date param issue | LOW |
| OpenClaw Mini PC | Pending hardware replacement | MEDIUM |
| Omnicom 401k → Rollover IRA | Planned 2027 | LOW |

---

## CURRENT PORTFOLIO BASELINE (April 10, 2026)

| Account | Total | Holdings | Source |
|---|---|---|---|
| Fidelity 401k | $519,362 | 10 funds | PDF Import |
| Schwab Rollover IRA | $545,353 | 14 | CSV Import |
| Schwab Roth IRA | $41,415 | 3 | CSV Import |
| Schwab Taxable | $73,095 | 23 | CSV Import |
| **Total** | **$1,179,224** | **50** | |
