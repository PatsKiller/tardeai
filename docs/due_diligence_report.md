# Trade AI v12 — Post-Incident Due Diligence Report
**Period:** April 6–8, 2026  
**Prepared:** April 8, 2026  
**Severity:** High — system failed to run autonomously for ~36 hours

---

## Executive Summary

Three independent failure modes combined to break the system from Sunday night through Wednesday morning. None were caused by market conditions or API changes. All were caused by **Claude-introduced code changes that were not tested against the production baseline**, plus **one pre-existing Task Scheduler misconfiguration** that was dormant until a machine state change exposed it.

---

## Root Cause Analysis — What Actually Broke

### Failure #1: Task Scheduler `%ROOT%` Variable (Pre-existing, Exposed April 8)
**Severity:** CRITICAL — caused zero Trade AI runs all morning  
**Origin:** Pre-existing misconfiguration — Task Scheduler was set to run:
```
%ROOT%\launchers\run_continuous.bat
```
`%ROOT%` is not a Windows system environment variable. It expanded to nothing, causing the task to fail silently with **exit code 1** every morning. This had been masked previously because the runner was being started manually.

**Evidence:** `schtasks /query` showed `Task To Run: %ROOT%\launchers\run_continuous.bat`, `Last Result: 1` (failure). The `scheduler_starts.log` file did not exist until Claude added logging — meaning no prior evidence of the task ever firing.

**How it was exposed:** After session work on April 7–8, the machine apparently was not left with the runner running manually, so the broken scheduled task was the only thing that would have restarted it.

**Fix applied:** `fix_scheduler_ps.ps1` — recreated task with hardcoded absolute path: `cmd.exe /c "C:\Users\john\...\launchers\run_continuous.bat"`

---

### Failure #2: LIVE Cycles Never Updated `dashboard_live.html`
**Severity:** HIGH — dashboard stuck on yesterday's data even when runner was working  
**Origin:** Design gap in `continuous_runner.py` — `run_live_cycle()` wrote HTML to `reports/2026-04-08/0700/dashboard_2026-04-08_0700.html` but never copied it to `reports/dashboard_live.html`. Only FULL pipeline runs (at 6AM, 7AM, 8AM, 9AM, 10AM anchors) updated `dashboard_live.html`.

**Evidence:** On April 8 from 8:13–8:58 AM, live cycles were running and generating fresh HTML in the dated subfolder, but `dashboard_live.html` remained at `01:19:05 GMT` (yesterday). Users opening `localhost:7777/reports/dashboard_live.html` saw stale data.

**Fix applied:** Added `shutil.copy2(html, root/"reports"/"dashboard_live.html")` after each live cycle HTML generation.

---

### Failure #3: `continuous_runner.py` Started at 6AM, Not 4AM
**Severity:** MEDIUM — 4AM and 5AM runs never happened as full scans  
**Origin:** `SCHEDULE` in `continuous_runner.py` defined windows starting at `"06:00"`. Task Scheduler fires at 4AM. The runner would start, wait for 6AM, then begin. The 4AM–6AM window was completely dead.

**Evidence:** All three days' logs (`continuous_20260406.log`, `continuous_20260407.log`, `continuous_20260408.log`) show the runner banner: `Schedule: 6–9 AM (15min)`. No cycles before 06:00 in any log.

**Fix applied:** 
- SCHEDULE extended to `("04:00", "06:00", 30, True)`
- `HOURLY_FULL_ANCHORS` extended to include `"04:00"` and `"05:00"` 
- Added **startup FULL run** that fires immediately on launch, regardless of time

---

### Failure #4: Fidelity 401k SMA Cross Spam (April 8 — New)
**Severity:** MEDIUM — 20 false Telegram alerts at 9AM  
**Origin:** `portfolio_live_monitor.py` checks `sma50_pct` for every holding. Fidelity proprietary fund symbols (`FID-CONTRA-F`, `SS-SMMD`, etc.) have `sma50_pct = 0.0` by default because Yahoo Finance doesn't have SMA data for Fidelity institutional fund codes. Zero falls exactly within the `±1.0%` trigger band, causing every fund to fire "crossed 50-day MA" and "crossed 200-day MA" every morning the monitor starts.

**Evidence:** 20 consecutive SMA alert messages at exactly 9:00 AM, all showing `SMA distance: +0.0%`. This is the mathematical signature of default-zero triggering, not a real crossing event.

**Fix applied:** Added `_is_proprietary = "-" in sym and len(sym) > 5` guard before all SMA/RSI trigger checks. Price-based alerts (±3%, concentration) still fire for these funds.

---

### Failure #5: File Delivery Issues (April 8 — Claude-induced)
**Severity:** LOW-MEDIUM — wasted ~1 hour of debugging time  
**Origin:** Multiple Claude-generated files delivered via zip built on Linux had **LF-only line endings**. Windows CMD requires CRLF for `.bat` files and Windows PowerShell requires CRLF for `.ps1` files.

**Specific errors:**
- `run_continuous.bat` — syntax error on `if not "%%a:~0,1%"=="#"` (invalid CMD syntax in `.env` loader loop)
- `fix_scheduler_ps.ps1` — `Missing closing '}'` (PowerShell couldn't parse LF line endings)
- `fix_scheduler_ps.ps1` — `-DisallowStartIfOnBatteries` parameter doesn't exist on older PowerShell versions

**Fix applied:** Rewrote both files using Python with explicit CRLF (`\r\n`), removed the broken `.env` loader loop from bat file, replaced PowerShell cmdlet-based settings with `schtasks + XML string replacement` approach that works on all PS versions.

---

## Timeline of Events

| Time | Event |
|------|-------|
| Apr 6 AM | `continuous_runner.py` starts at 6AM (4AM–6AM gap existed but unnoticed) |
| Apr 6 6AM–11AM | 11 LIVE cycles, 0 FULL runs — `dashboard_live.html` not updated by LIVE cycles |
| Apr 7 AM | Same pattern — 9 LIVE cycles, 0 FULL runs in continuous log |
| Apr 7 evening | Session ends — runner not manually restarted |
| Apr 8 4AM | Task Scheduler fires — `%ROOT%` fails — exit code 1 — no log, no runner |
| Apr 8 8:13AM | User manually runs `launchers\run_continuous.bat` — old unpatched code starts |
| Apr 8 8:25AM | `scheduler_starts.log` first entry — confirms new launcher working |
| Apr 8 8:57AM | Patched runner starts — `[STARTUP]` FULL run fires — Telegram sends |
| Apr 8 9:00AM | 20 false Fidelity SMA alerts flood Telegram |
| Apr 8 9AM–11AM | All fixes deployed, system fully operational |

---

## What Was Working Before and Must Be Preserved

These are the confirmed-working baselines that any future Claude session must not break:

### Trade AI v12
- `trade_ai_orchestrator.py` — 23-stage pipeline completes fully
- `finviz_ingestion.py` — Finviz Elite cookie + API token working
- Telegram alerts via `alerting.py` → `telegram_alert.py` — confirmed working
- `dashboard_live.html` — now updated by BOTH FULL runs AND LIVE cycles ← **new baseline**
- `continuous_runner.py` — now fires FULL run at startup ← **new baseline**
- SCHEDULE now active from 4AM ← **new baseline**

### Portfolio Intelligence v1.2
- All 18 tabs healthy, zero errors
- Fidelity 401k: $504,030, +$580.81 today, real cost_basis and gain_loss per fund
- Period returns: 7 periods from 1D to 1Y using price cache reconstruction
- Account filter pills on Performance tab (5 pills)
- Period Returns block on Overview tab
- `portfolio_orchestrator.py` auto-copies to both report locations
- Attribution uses 2-year price cache window (SPY/ITA/AGG auto-downloaded on first run)

---

## Claude's Operational Rules Going Forward

**BEFORE making any change to a working file:**
1. Read the current file completely
2. Identify the exact minimum change needed
3. Make only that change
4. Validate syntax (Python: `ast.parse`, bat: visual inspection, PS1: brace count + CRLF check)
5. Test in browser against live dashboard before declaring success

**File delivery rules:**
- All `.bat` files must be written with CRLF (`\r\n`) — use Python `'wb'` mode
- All `.ps1` files must be written with CRLF — use Python `'wb'` mode  
- All zip files must be built from CRLF-correct source files
- Never use bash heredoc (`cat << EOF`) for Windows files — always use Python to write them
- Always verify with `python3 -c "with open(f,'rb') as f: print('CRLF' if b'\\r\\n' in f.read() else 'LF-only')"`

**PowerShell compatibility rules:**
- Never use `-DisallowStartIfOnBatteries` (not in older PS)
- Never use `-StartWhenAvailable` as cmdlet param (not in older PS)  
- Use `schtasks /create` + XML string replacement for Task Scheduler
- Verify brace count before delivering any PS1: `opens == closes`

**Task Scheduler rules:**
- Always use hardcoded absolute paths — never `%ROOT%`, `%~dp0`, or any variable in the `Task To Run` field
- Always use `cmd.exe /c "full\path\to\launcher.bat"` as the action
- Always verify with `schtasks /query /tn "TaskName" /fo LIST /v | findstr "Task To Run"`

**Baseline protection rule:**
- When updating `continuous_runner.py`, `portfolio_dashboard.py`, `portfolio_loader.py`, or any core pipeline script: make targeted surgical patches, never full rewrites
- Always run `python3 -c "import ast; ast.parse(src)"` before saving
- Always preview in browser before declaring done
- Never kill `taskkill /f /im python.exe` without explicitly noting it will also kill `portfolio_server.py`

---

## Changes Made to Production Files (April 6–8)

| File | Change | Status |
|------|--------|--------|
| `scripts/continuous_runner.py` | SCHEDULE 4AM, startup FULL run, LIVE→dashboard_live copy, anchors 4AM+5AM | ✅ Deployed |
| `launchers/run_continuous.bat` | Hardcoded path, scheduler_starts.log, CRLF | ✅ Deployed |
| `scripts/portfolio_loader.py` | Fidelity 401k data updated from live Fidelity website | ✅ Deployed |
| `scripts/portfolio_dashboard.py` | Period returns on Overview, sector labels, account filter pills, card layout | ✅ Deployed |
| `scripts/portfolio_performance_attribution.py` | 2-year price cache reconstruction | ✅ Deployed |
| `scripts/portfolio_performance_history.py` | Fidelity fund mapping for period returns | ✅ Deployed |
| `scripts/portfolio_live_monitor.py` | Fidelity proprietary fund SMA guard | ✅ Deployed |
| `scripts/portfolio_orchestrator.py` | Auto-copy to both report locations | ✅ Deployed |
| `fix_scheduler_ps.ps1` (root) | Task Scheduler repair script | ✅ Applied |

---

## Recommended Process Changes

1. **Before any session that modifies working code:** take a snapshot of the current state via `schtasks /query` and note the dashboard URL + run date
2. **Never close a session without confirming:** `scheduler_starts.log` exists and shows today's date, `dashboard_live.html` shows today's date
3. **After any `portfolio_*.py` file is changed:** run `run_portfolio.bat` and confirm `Today: +$X,XXX` is reasonable before finishing
4. **After any `continuous_runner.py` is changed:** restart the runner and confirm `[STARTUP]` appears in the log within 30 seconds
5. **Zip file delivery:** always state the exact files in the zip, their destination paths, and verify CRLF before zipping
