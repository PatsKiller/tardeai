# forensic_files.md
## Trade AI v12 + Portfolio Intelligence v1.2 — Complete File Registry
## Project root: `C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\`
## Last updated: April 10, 2026

This file documents every file and directory in the project. It is the reference document before touching anything. Update it whenever files are added, moved, or deleted.

---

## How to use this file

1. **Before any session:** Search this file for the component you're working on. Read the description and status before opening the file.
2. **Before deleting anything:** Verify it's marked DELETE or ARCHIVE here first.
3. **After adding a file:** Add an entry here immediately.
4. **Status codes:**
   - `ACTIVE` — live, in use, do not change without careful thought
   - `KEEP` — important, preserve
   - `ARCHIVE` — move to `sandbox/` before eventual deletion
   - `DELETE` — safe to delete, confirmed not needed
   - `LEGACY` — superseded by new architecture, can archive
   - `PROPOSED` — directory or file that should be created

---

## Directory Structure

```
trade-ai-v12-rebuild/
├── .env                          ← SECRETS — never commit
├── _env                          ← Template (no secrets) — safe to commit
├── run_portfolio.bat             ← Daily pipeline launcher
├── run_portfolio_monthly.bat     ← Monthly full analysis
├── run_portfolio_weekly.bat      ← Weekly pipeline
├── run_price_cache.bat           ← Sunday price cache refresh
├── restart_server.bat            ← Safe port 7777 restart
├── env_manager.html              ← Browser-based .env editor
├── forensic_files.md             ← THIS FILE
├── docs/                         ← Documentation (proposed)
├── sandbox/                      ← Temp work area (proposed)
├── assets/
│   └── portfolio_accounts.yaml   ← Account config (no file refs)
├── data/
│   └── portfolios/
│       ├── input/                ← Legacy CSVs (not used by pipeline)
│       ├── state/                ← Live state files (sacred)
│       ├── reports/              ← Generated HTML reports
│       ├── charts/               ← Generated chart images
│       └── yaml_backups/         ← YAML change backups
├── launchers/
│   ├── run_continuous.bat        ← Task Scheduler entry point (CRITICAL)
│   └── run_1000.bat              ← 10AM Trade AI run
├── logs/                         ← Runtime logs
├── reports/                      ← Served at localhost:7777/reports/
│   ├── command_center.html       ← ACTIVE v48 dashboard
│   ├── portfolio_live.html       ← Generated portfolio dashboard
│   └── dashboard_live.html       ← Trade AI live view
└── scripts/                      ← All Python scripts
    ├── portfolio_*.py            ← Portfolio Intelligence scripts
    ├── trade_ai_orchestrator.py  ← Trade AI pipeline
    ├── continuous_runner.py      ← Trade AI continuous runner
    └── ...
```

---

## ROOT DIRECTORY FILES

### `.env`
- **Status:** ACTIVE — NEVER COMMIT TO GIT
- **Size:** ~2KB
- **Purpose:** Live API keys and configuration. Single source of truth for all secrets.
- **Contains:** ANTHROPIC_API_KEY, FINVIZ_TOKEN, FINVIZ_COOKIE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDs, NEWSAPI_KEY, ENABLE_TELEGRAM
- **Note:** `env_manager.html` is the safe way to edit this file. Never edit with a text editor that might auto-save to cloud.

### `_env`
- **Status:** KEEP — template only
- **Size:** 7KB
- **Purpose:** Documents all required environment variables without actual values. Safe reference. Can be committed to git.

### `run_portfolio.bat`
- **Status:** ACTIVE
- **Size:** 525B
- **Purpose:** Daily portfolio pipeline launcher. Activates venv, runs portfolio_orchestrator.py with `--run-label morning --run-type daily`, copies portfolio_live.html to reports/, calls `POST /api/clear-pending` to clear the pending banner.
- **Called by:** Task Scheduler (Portfolio Daily, Mon–Fri 7AM) and manually.
- **Note:** The clear-pending line was added April 10, 2026. Do not remove it.

### `run_portfolio_monthly.bat`
- **Status:** ACTIVE
- **Size:** ~1KB
- **Purpose:** Monthly full pipeline. Runs orchestrator + AI analysis refresh + YAML Config Advisor (Opus ~$0.15) + dashboard copy. Auto-triggered by Task Scheduler on 1st of month.

### `run_portfolio_weekly.bat`
- **Status:** ACTIVE
- **Purpose:** Weekly portfolio run. Less expensive than monthly. Called Sunday 8PM by Task Scheduler.

### `run_price_cache.bat`
- **Status:** ACTIVE
- **Purpose:** Refreshes the Yahoo price history cache for 75 symbols from 2020 to today. Called Sunday 7PM by Task Scheduler. Must run before Sunday 8PM weekly pipeline.

### `restart_server.bat`
- **Status:** ACTIVE
- **Size:** 496B
- **Purpose:** Safe portfolio server restart. Uses `netstat -aon | findstr :7777` to find the PID, kills it, waits 2 seconds, starts new server in its own CMD window.
- **Use when:** Server needs restart after deploying new portfolio_server.py, or after port gets stuck.
- **Note:** If it fails with "Access Denied", use Admin PowerShell: `taskkill /F /PID <pid>`

### `env_manager.html`
- **Status:** KEEP
- **Size:** 25KB
- **Purpose:** Browser-based editor for the `.env` file. Open in Chrome, make changes, click Save. Writes directly to root `.env`. Prevents accidental cloud sync issues from text editors.

### `forensic_files.md`
- **Status:** ACTIVE — this file
- **Purpose:** Complete file registry and documentation. The reference document before any work session.

---

## PROPOSED: `docs/` directory

Create this directory to hold documentation files currently cluttering the root:

```cmd
mkdir docs
```

### `docs/SKILL_v3.md`
- **Status:** PROPOSED — upload to project knowledge
- **Purpose:** Current skill reference for Claude. Version 3.0, April 10, 2026. Contains Iron Rules, import workflow, failure modes, validation checklists.

### `docs/day2_addendum_v22.md`
- **Status:** PROPOSED — move from root or create
- **Purpose:** Complete architecture documentation. Supersedes v21. Documents v49 architecture, PDF.js FUND_MAP keys, CSV parser fix, session startup checklist.

### `docs/root_cause_analysis_apr10.md`
- **Status:** MOVE FROM ROOT
- **Source:** `root_cause_analysis.md` in root directory
- **Purpose:** Post-incident analysis of the April 10 portfolio zeroing incident. Five failure modes documented with exact fixes.

### `docs/command_center_architecture.md`
- **Status:** MOVE FROM ROOT
- **Source:** `command_center_architecture.md` in root
- **Purpose:** Architecture notes for Command Center v36–v48 development. Historical reference.

### `docs/command_center_docs.md`
- **Status:** MOVE FROM ROOT
- **Source:** `command_center_docs.md` in root
- **Purpose:** Feature documentation for Command Center versions. Historical reference.

---

## PROPOSED: `sandbox/` directory

Create this directory as the ONLY place temporary files land:

```cmd
mkdir sandbox
mkdir sandbox\old_cc
mkdir sandbox\deploy_zips
```

**Rule:** Every file Claude delivers as a zip goes to `sandbox\deploy_zips\`. After extracting and verifying, delete the zip. Temporary fix scripts go here, not the root.

### `sandbox/old_cc/`
- **Purpose:** Archive for superseded Command Center versions. Not deleted immediately — kept as fallback in case v48 has issues.
- **Contains (proposed):** command_center_v40.html through v46.html

### `sandbox/deploy_zips/`
- **Purpose:** Where deployment zips land temporarily. Extract → verify → delete zip.

---

## `reports/` DIRECTORY

Served by portfolio_server.py at `http://localhost:7777/reports/`

### `reports/command_center.html`
- **Status:** ACTIVE — DO NOT DELETE OR OVERWRITE CARELESSLY
- **Size:** 480KB
- **Version:** v48 (April 10, 2026)
- **Purpose:** The live Command Center dashboard. Unified Trade AI + Portfolio Intelligence view. Import Data modal, pending banner, PDF/CSV parsers, all tabs.
- **Deploy:** `copy /Y reports\command_center_v48.html reports\command_center.html`

### `reports/portfolio_live.html`
- **Status:** ACTIVE — auto-generated
- **Size:** 632KB
- **Purpose:** Portfolio analytics dashboard with all 18 tabs. Generated by portfolio_dashboard.py after every pipeline run. Served at localhost:7777/reports/portfolio_live.html.
- **Do not edit manually** — regenerated on every run.

### `reports/dashboard_live.html`
- **Status:** ACTIVE — auto-generated
- **Size:** 49KB
- **Purpose:** Trade AI live dashboard. Updated by continuous_runner.py after every FULL and LIVE cycle. Always shows current day's scan results.
- **Do not edit manually** — regenerated continuously.

### `reports/command_center_reset_baseline_fix34.html`
- **Status:** DELETE
- **Size:** 253KB
- **Reason:** Debug artifact from early April session. Name appearing in browser console error logs — this is the file causing cached errors. No longer referenced by anything.
- **Delete command:** `del reports\command_center_reset_baseline_fix34.html`

### `reports/command_center_v40.html` through `v46.html`
- **Status:** ARCHIVE → `sandbox\old_cc\`
- **Sizes:** 354KB–445KB each (~1.6MB total)
- **Reason:** Superseded by v48. Kept as fallback reference only.
- **Archive commands:**
```cmd
mkdir sandbox\old_cc
move reports\command_center_v40.html sandbox\old_cc\
move reports\command_center_v44.html sandbox\old_cc\
move reports\command_center_v45.html sandbox\old_cc\
move reports\command_center_v46.html sandbox\old_cc\
```

---

## `scripts/` DIRECTORY

All Python scripts. Handle with extreme care. Always `ast.parse()` before and after changes.

### `scripts/portfolio_loader.py`
- **Status:** ACTIVE — v3.0
- **Size:** 18KB
- **Purpose:** CRITICAL. Portfolio data loader. Reads holdings.json as single source of truth, reprices non-Fidelity positions from Yahoo price cache, computes totals, enforces 50% sanity check. No CSV scanning.
- **Key functions:** `load_all_portfolios(str)`, `save_state(dict, str)`, `reprice_holdings()`, `parse_fidelity_pdf_text()`
- **Changed:** April 10, 2026 — complete rewrite to v3 architecture

### `scripts/portfolio_server.py`
- **Status:** ACTIVE — v2.0
- **Size:** 15KB
- **Purpose:** CRITICAL. HTTP server on port 7777. Serves static files (HTML, JSON, YAML, Python). Handles /api/import (write positions), /api/clear-pending (clear pending banner), /api/run-portfolio (trigger pipeline), /api/run-trade-ai, /api/health.
- **Start:** `venv\Scripts\python.exe scripts\portfolio_server.py`
- **Restart:** Use `restart_server.bat`

### `scripts/portfolio_orchestrator.py`
- **Status:** ACTIVE
- **Size:** 20KB
- **Purpose:** 10-step pipeline coordinator. Imports and calls all other portfolio scripts in sequence. Passes `str(root)` to load_all_portfolios and save_state (fixed April 10).
- **Steps:** Load → Analyze → Tax → Rebalance → Risk → Charts → Performance → AI → Dashboard → Report

### `scripts/portfolio_analyzer.py`
- **Status:** ACTIVE
- **Size:** 19KB
- **Purpose:** Portfolio analytics engine. Concentration analysis, sector exposure with ETF look-through, dividend income, portfolio vitals (beta, yield, PE), performance attribution, critical flags generation.

### `scripts/portfolio_rebalancer.py`
- **Status:** ACTIVE
- **Size:** 21KB
- **Purpose:** Rebalancing engine. Drift analysis vs targets, rebalance order generation, share count calculations, V→SCHD scenario analysis, 401k in-plan fund suggestions (no ETF purchases allowed in 401k).

### `scripts/portfolio_tax.py`
- **Status:** ACTIVE
- **Size:** 13KB
- **Purpose:** Tax analysis. Tax lot reconstruction, unrealized gains/losses, harvest candidates, wash sale detection, realized gains, bracket estimation.

### `scripts/portfolio_dashboard.py`
- **Status:** ACTIVE
- **Size:** 160KB
- **Purpose:** Generates portfolio_live.html with all 18 tabs. Largest file in the project. Contains all HTML/CSS/JS for the portfolio dashboard.
- **Note:** Uses Node.js docx library for Word report generation.

### `scripts/portfolio_ai_analyst.py`
- **Status:** ACTIVE
- **Size:** 35KB
- **Purpose:** 7-section AI analysis. Sections 1–6 use Claude Sonnet, Roth conversion section uses Claude Opus with extended thinking. Results cached in ai_analysis_cache.json.

### `scripts/portfolio_live_monitor.py`
- **Status:** ACTIVE
- **Size:** 24KB
- **Purpose:** Intraday price monitor. Runs 9AM–4:31PM ET every 60 minutes. Sends Telegram on: PRICE_UP_3PCT, PRICE_DOWN_3PCT, CONCENTRATION, SMA50_CROSS, SMA200_CROSS, RSI_OVERBOUGHT, RSI_OVERSOLD, WEEK52_HIGH, WEEK52_LOW, STOP_HIT. Fidelity proprietary symbols exempt from SMA/RSI triggers.

### `scripts/portfolio_technical.py`
- **Status:** ACTIVE — v2.0
- **Size:** 50KB
- **Purpose:** Finviz technical data engine. 3-tier: API token (price/analyst), cookie quote.ashx (RSI/SMA/ATR), stale fallback. MUTUAL_FUND_TICKERS frozenset skips cookie requests for Fidelity funds. 28 cookie requests/day (was 91).

### `scripts/portfolio_yaml_advisor.py`
- **Status:** ACTIVE
- **Size:** 22KB
- **Purpose:** Monthly YAML config review. Reads portfolio_accounts.yaml and holdings.json, builds prompt, calls Claude Opus. Generates suggestions for allocation target updates, position notes, rebalance guidance. 90-day DO_NOT_TOUCH protection on recently traded symbols.

### `scripts/portfolio_yaml_writer.py`
- **Status:** ACTIVE
- **Size:** ~8KB
- **Purpose:** Safe YAML write-back. Creates timestamped backups in data/portfolios/yaml_backups/ before any change. Applies suggestions from yaml_advisor_output.json. Logs all changes to yaml_change_history.json.

### `scripts/portfolio_performance_history.py`
- **Status:** ACTIVE
- **Size:** 19KB
- **Purpose:** Period returns calculation. Reprices current holdings at historical dates using price_cache.json. Produces 1D/1W/1M/3M/6M/YTD/1Y returns. Does NOT reconstruct transactions (scalp trades corrupt backward reconstruction).

### `scripts/portfolio_risk.py`
- **Status:** ACTIVE
- **Size:** 16KB
- **Purpose:** Risk analysis. Beta vs SPY, benchmark comparison, individual position scoring, stop-loss monitoring, correlation matrix, stress testing.

### `scripts/portfolio_trade_watcher.py`
- **Status:** ACTIVE
- **Size:** ~6KB
- **Purpose:** File system watcher. Monitors Downloads/Documents/data/imports for new Schwab CSVs. Auto-fires run_portfolio_monthly.bat with 5-minute debounce when new file detected.

### `scripts/trade_ai_orchestrator.py`
- **Status:** ACTIVE
- **Size:** 22KB
- **Purpose:** 23-stage Trade AI pipeline coordinator. Valid run labels: 0400, 0700, 0900, 1000. Flags: --skip-market-check, --no-alerts, --no-llm for testing.

### `scripts/continuous_runner.py`
- **Status:** ACTIVE — CRITICAL
- **Size:** 23KB
- **Purpose:** Trade AI continuous runner. 4AM–11AM Mon–Fri. FULL runs at hourly anchors (±7 min window), LIVE cycles every 10–30 min. FULL run fires immediately on startup (catches missed 4AM runs). LIVE cycles copy result to dashboard_live.html.
- **Do not modify schedule** without checking: 04:00 start, startup FULL, HOURLY_FULL_ANCHORS set.

### `scripts/trade_ai_health.py`
- **Status:** ACTIVE
- **Size:** ~8KB
- **Purpose:** Generates trade_ai_health.json. Reports API statuses (Finviz, Polygon, FMP, Finnhub, Anthropic, Telegram), last run times, score distributions, pipeline health score.

### `scripts/finviz_ingestion.py`
- **Status:** ACTIVE
- **Size:** 12KB
- **Purpose:** Finviz Elite screener ingestion. 2 screeners: prime_setups (RVOL>5x, gap>10%, $2–$20, float<50M) and watchlist_setups (RVOL>3x, gap>5%, $1–$30, float<100M). Primary data source for Trade AI.

### `scripts/catalyst_enrichment.py`
- **Status:** ACTIVE
- **Size:** 24KB
- **Purpose:** 7-source catalyst enrichment. Identifies: FDA calendar, earnings beats, M&A, material 8-K filings, news headlines. Assigns catalyst scores (max 15 points) to tickers.

---

## `assets/` DIRECTORY

### `assets/portfolio_accounts.yaml`
- **Status:** ACTIVE — CLEAN v1.2
- **Size:** 22.5KB (expanded April 10 with Roth strategy + tax intelligence sections)
- **Purpose:** Complete portfolio configuration. Contains: account definitions, target allocations, Fidelity 14 in-plan funds, ETF sector mappings, revoked securities, Roth conversion strategy (3 phases, IRMAA, projections, disability scenarios), tax intelligence (DRIP policy, harvest candidates, monthly report requirements).
- **What it does NOT contain:** positions_file, transactions_file, input_file — permanently removed.
- **Key sections:** `roth_conversion_strategy` (update `ytd_conversions_2026` each conversion), `tax_intelligence` (CDEX pending flag until basis confirmed), `fidelity_available_funds` (14 funds).
- **Annual updates required:** ytd_conversions, current_age, tax bracket thresholds (January), deductions actuals (after TurboTax).
- **Edit via:** YAML Config Advisor (Command Center → YAML Review) or direct edit. Always `yaml.safe_load()` after changes.

---

## `data/portfolios/state/` DIRECTORY

**These files are the system's memory. Treat as sacred.**

### `holdings.json`
- **Status:** ACTIVE — SINGLE SOURCE OF TRUTH
- **Purpose:** Complete portfolio state. All account holdings (symbol, shares, price, market_value, account), account summaries (totals, as_of dates), portfolio totals, pending_pipeline_run flag.
- **Written by:** `/api/import` (Import modal) — the only way share counts change.
- **Read by:** portfolio_loader.py (reprices), portfolio_server.py (serves), all analytics scripts.
- **Protection:** 50% sanity check in portfolio_loader.py prevents zeroing.

### `price_cache.json`
- **Status:** ACTIVE
- **Size:** 2.5MB
- **Purpose:** Yahoo Finance price history for 75 symbols from January 2020 to today. Used by portfolio_loader.py for repricing Schwab positions and by portfolio_performance_history.py for period returns.
- **Rebuild:** `run_price_cache.bat` (Sunday 7PM Task Scheduler)

### `ai_analysis_cache.json`
- **Status:** ACTIVE — cache file
- **Purpose:** Monthly AI analysis results. Prevents re-running expensive Opus calls on every daily pipeline run.
- **Delete to refresh:** `del data\portfolios\state\ai_analysis_cache.json` then `run_portfolio_monthly.bat`

### `technical_snapshot.json`
- **Status:** ACTIVE — cache file
- **Purpose:** Finviz RSI/SMA/ATR data for all positions. Regenerated daily. Staleness gate: SMA/RSI triggers suppressed if snapshot is >26 hours old.

### `performance_history.json`
- **Status:** ACTIVE — accumulating
- **Purpose:** Portfolio value snapshots over time. Used by portfolio_performance_history.py to calculate 1D/1W/1M/3M/6M/YTD/1Y returns. Grows over time — do not delete.

### `trade_ai_health.json`
- **Status:** ACTIVE
- **Purpose:** Trade AI pipeline health state. API statuses, last run times, score distributions. Read by Command Center Trade AI health display.

### `yaml_advisor_output.json`
- **Status:** ACTIVE
- **Purpose:** Latest YAML Config Advisor suggestions. Read by Command Center YAML Review modal. Shows health score, observations, suggestions to apply.

### `yaml_change_history.json`
- **Status:** ACTIVE — audit trail
- **Purpose:** Logs every YAML change applied via portfolio_yaml_writer.py. Timestamp, suggestion ID, what changed, backed-up filename.

### `performance_attribution.json`
- **Status:** ACTIVE — cache file
- **Purpose:** Performance attribution analysis (portfolio vs SPY/ITA/AGG benchmarks). Cached for speed.
- **Delete to refresh:** `del data\portfolios\state\performance_attribution.json` then `run_portfolio.bat`

### `portfolio_options.json`
- **Status:** NOT YET GENERATED
- **Purpose:** Options opportunities data. Generated by monthly pipeline. The 404 error in browser console is harmless — will be created on next monthly run.

---

## `data/portfolios/input/` DIRECTORY

**Status: LEGACY.** Pipeline v3 no longer reads from this directory. These files are kept for transaction history reference only.

### Positions CSVs (LEGACY — no longer used)
- `Rollover IRA-Positions-2026-04-08-155234.csv`
- `Roth Contributory IRA-Positions-2026-04-08-155249.csv`
- `Individual-Positions-2026-04-08-155217.csv`
- `Portfolio_Positions_Apr-08-2026.csv` (Fidelity — never used)

**Disposition:** These can be archived to `sandbox/old_inputs/` or deleted. The Import modal is the replacement.

### Transaction CSVs (KEEP — used by trade journal)
- `Rollover_IRA_XXX258_Transactions_20260408-094116.csv`
- `Roth_Contributory_IRA_XXX415_Transactions_20260408-094104.csv`
- `Individual_XXX469_Transactions_20260408-093959.csv`

These are still used by the trade journal. When you download new transaction history, add to this folder AND import via modal's Schwab Transactions tab.

---

## `launchers/` DIRECTORY

### `launchers/run_continuous.bat`
- **Status:** ACTIVE — CRITICAL — DO NOT RENAME OR MOVE
- **Purpose:** Task Scheduler entry point for TradeAIContinuous. Hardcoded in Windows Task Scheduler as absolute path. Any rename or move breaks the 4AM daily automation.

### `launchers/run_1000.bat`
- **Status:** ACTIVE
- **Purpose:** 10AM Trade AI run launcher. Called by `/api/run-trade-ai` server endpoint when "Run Trade AI Scan" is clicked in Command Center.

---

## `logs/` DIRECTORY

Auto-generated. Reviewed but not edited.

### `logs/scheduler_starts.log`
- **Status:** KEEP
- **Purpose:** Task Scheduler fire confirmation. Shows timestamp of every TradeAIContinuous task launch. **Check this first** when Trade AI seems not running.

### `logs/continuous_YYYYMMDD.log`
- **Status:** ARCHIVE WEEKLY (keep last 7 days)
- **Purpose:** Daily Trade AI pipeline logs. One file per day. Shows full pipeline execution including scores, alerts, errors.

### `logs/portfolio_*.log`
- **Status:** ARCHIVE WEEKLY (keep last 7 days)
- **Purpose:** Portfolio pipeline run logs.

---

## `data/portfolios/yaml_backups/` DIRECTORY

### `portfolio_accounts_YYYYMMDD_HHMMSS.yaml.bak`
- **Status:** KEEP 30 DAYS, then delete
- **Purpose:** Timestamped backups created automatically by portfolio_yaml_writer.py before every YAML change. Recovery point if a YAML advisor suggestion causes problems.

---

## `data/portfolios/charts/` DIRECTORY

- **Status:** AUTO-GENERATED — can delete anytime
- **Purpose:** PNG chart images generated by pipeline (sector donut, account bars, holdings, gain/loss, ETF look-through, rebalancing, technical charts). Regenerated on every run. Safe to delete entire directory — will be recreated.

---

## FILES TO DELETE NOW

```cmd
:: Single confirmed-safe deletion
del reports\command_center_reset_baseline_fix34.html
```
**Reason:** Debug artifact from early April. Causing console errors (browser cache references it). 253KB saved.

---

## FILES TO MOVE (after creating directories)

```cmd
:: Create directories first
mkdir docs
mkdir sandbox
mkdir sandbox\old_cc
mkdir sandbox\deploy_zips

:: Move old Command Center versions out of reports/
move reports\command_center_v40.html sandbox\old_cc\
move reports\command_center_v44.html sandbox\old_cc\
move reports\command_center_v45.html sandbox\old_cc\
move reports\command_center_v46.html sandbox\old_cc\

:: Move documentation to docs/
move root_cause_analysis.md docs\root_cause_analysis_apr10.md
move command_center_architecture.md docs\
move command_center_docs.md docs\
move deploy_SKILL.md docs\
```

---

## GOING-FORWARD RULES

### 1. Sandbox rule
Any file Claude delivers (zip, fix script, test file) goes to `sandbox\` first.
```cmd
:: Example deploy workflow:
copy deploy_v50.zip sandbox\deploy_zips\
cd sandbox\deploy_zips
tar -xf deploy_v50.zip
:: Review contents
:: Copy specific files to their destinations
:: Delete zip
del deploy_v50.zip
```

### 2. Fix script rule
Any one-time fix script (like `fix_orchestrator.py`) goes to `sandbox\` and is deleted after running:
```cmd
move fix_orchestrator.py sandbox\
cd sandbox
venv\..\venv\Scripts\python.exe fix_orchestrator.py
del fix_orchestrator.py
```

### 3. No deployment zips in project root
Never leave `.zip` files in the project root. They accumulate and confuse directory scans.

### 4. forensic_files.md is updated every session
When a file is added, moved, or deleted — update this document. Include: status, size, purpose, date changed.

### 5. Version archives go to sandbox/old_cc/
When Command Center is updated to a new version, move the old HTML to `sandbox\old_cc\`. Keep the last 2 versions as fallback. Delete anything older than 60 days.

### 6. docs/ for all documentation
SKILL.md, Day 2 Addenda, root cause analyses, architecture documents — all go in `docs/`. Nothing except operational files belongs in the root directory.

---

## CHANGE LOG

| Date | Change | Who |
|---|---|---|
| April 10, 2026 | Initial forensic_files.md created | Claude |
| April 10, 2026 | Identified: command_center_reset_baseline_fix34.html for deletion | Claude |
| April 10, 2026 | Identified: v40/v44/v45/v46 for archival to sandbox/old_cc/ | Claude |
| April 10, 2026 | Proposed: docs/ and sandbox/ directory structure | Claude |
| April 10, 2026 | YAML cleaned: removed 7 file references (positions_file, transactions_file, input_file) | Claude |
| April 10, 2026 | portfolio_loader.py v3: no CSV scanning, sanity check, holdings.json as source of truth | Claude |
| April 10, 2026 | portfolio_server.py v2: /api/import, /api/clear-pending active | Claude |
| April 10, 2026 | command_center.html v48: fixed Schwab CSV tokenizer, Fidelity PDF parser, pending banner | Claude |
| April 10, 2026 | portfolio_accounts.yaml v1.2: added roth_conversion_strategy, tax_intelligence, updated DRIP policy, CDEX flag | Claude |
| April 10, 2026 | YAML cleanup: removed positions_file, transactions_file, input_file from all accounts | Claude |
