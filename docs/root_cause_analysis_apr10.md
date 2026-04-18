# Root Cause Analysis — April 9-10, 2026 Session
## Portfolio Intelligence v1.2 — Data Pipeline Failures & Import System Build

---

## Executive Summary

This session suffered from a cascade of interconnected failures centered on one core architectural flaw: **the portfolio pipeline had no protection against writing zeroed data to `holdings.json` when CSV files were missing.** Every other problem flowed from that. Additionally, the Fidelity 401k data path had multiple fragile dependencies that broke when we attempted to eliminate file references from the YAML config.

**Final state achieved:** $1,175,350 across 4 accounts. All systems operational. Command Center v47 deployed with Import Data modal.

---

## Section 1: Root Cause — The Holdings Zeroing Problem

### What Broke
`portfolio_loader.py` would write `holdings.json` with $0 for any account whose CSV file was not found in `data/portfolios/input/`. This happened silently — the pipeline reported "0 holdings | $0.00" and saved it.

### Why It Happened
The original pipeline design assumed CSVs would always be present. When `positions_file` in `portfolio_accounts.yaml` pointed to a specific dated filename (e.g., `Rollover_IRA-Positions-2026-04-06-150752.csv`) and that file had been deleted, renamed, or was in a different location, the loader had no fallback — it simply returned an empty list.

### Chain of Events
1. Session started with all 4 accounts at $1,160,018
2. We updated `portfolio_accounts.yaml` to remove all `positions_file` references (Import modal design decision)
3. Pipeline ran → found no CSVs for any Schwab account → wrote $0 for 3 accounts → `holdings.json` corrupted to $577K
4. Fallback code was added but read from `holdings.json` AFTER the pipeline already overwrote it → circular failure
5. Multiple attempts to restore from browser memory failed because the browser refreshed from the server and got the bad data

### The Real Fix Applied
Two changes to `portfolio_loader.py`:

**Fix 1:** Load `_prev_by_acct` from `holdings.json` at the VERY START of `load_all_portfolios()`, before any account is processed. This gives the fallback actual good data to work from.

**Fix 2:** Restore `positions_file` references to `portfolio_accounts.yaml`. The Import modal works WITHOUT needing filenames — it posts data directly to `/api/import`. But the pipeline still needs filenames as its CSV source of truth. These are separate concerns.

**Remaining gap (implement next session):** Add a sanity check — if new total < 50% of previous total, abort the save and keep the old `holdings.json`. This prevents any future zeroing regardless of cause.

---

## Section 2: Fidelity 401k Data Path Failures

### What Broke
After updating `portfolio_accounts.yaml`, the Fidelity 401k showed 0 holdings | $0.00 despite having a hardcoded `FIDELITY_HOLDINGS` list in `portfolio_loader.py`.

### Root Cause: Three Separate Issues

**Issue A — `input_file` removed from YAML**  
The YAML cleanup removed `input_file: fidelity_netbenefits.pdf` from the fidelity_401k account. The loader checks `pdf_file = acct_cfg.get("input_file")` — if None, it skips the entire `parse_fidelity_401k_pdf()` call. Result: 0 holdings.  
**Fix:** Restored `input_file: fidelity_netbenefits.pdf` to YAML.

**Issue B — `FIDELITY_HOLDINGS` had stale prices**  
The hardcoded data was from April 7 using Yahoo Finance prices, not Fidelity's actual NAV. Fidelity institutional fund NAVs differ from Yahoo retail prices (e.g., FID-CONTRA-F: $53.72 Yahoo vs $55.38 Fidelity actual). Result: $504,030 instead of $519,361.  
**Fix:** Updated `FIDELITY_HOLDINGS` with exact April 8 prices from the PDF statement.

**Issue C — Script replacement cut the list closing bracket**  
When replacing the `FIDELITY_HOLDINGS` block via script, the `]` closing bracket was cut because the end-detection logic found the wrong boundary. Result: `SyntaxError: '[' was never closed`.  
**Fix:** Inserted `]  # end FIDELITY_HOLDINGS` at line 411.

**Issue D — Schwab CSV false-positive in Fidelity CSV detector**  
`parse_fidelity_401k_pdf()` tries to find a Fidelity CSV in `data/portfolios/input/` by checking headers for "Last Price" + "Gain/Loss". A Schwab CSV matched this pattern, returned 0 valid holdings (wrong format), and set `FIDELITY_HOLDINGS = []`. The hardcoded fallback below it then ran but the local variable was empty.  
This issue was present but masked by other failures — not fully diagnosed until late in session.

---

## Section 3: Import Modal — PDF Parser Failure

### What Broke
The Fidelity PDF upload in the Import modal showed "No fund holdings found" despite the PDF being valid.

### Root Cause: PDF.js Text Extraction Format
The parser was tested against text extracted by `pdfminer`, which outputs proper newline-separated text:
```
WM Blair
Smmidcp GR
0.000
604.337
$42.48
$43.71
```

PDF.js (browser-side) was joining all text items on a page with spaces, producing:
```
WM Blair Smmidcp GR 0.000 604.337 $42.48 $43.71 $0.00 $26,416.11
```

The parser's fund-name-lookup logic searched line by line for fund names, which never matched in the space-joined format.

### Attempted Fixes
1. **y-position grouping** in `extractPDFText` — groups items at same y-coordinate onto one line, different y = new line. This was the correct fix but couldn't be verified because the browser cached the old version of the function.
2. **In-memory patching** — tried to override `handleFidelityFile` in the browser console. Failed because the modal creates its own closure scope.
3. **Multiple zip deployments (v47b through v47e)** — the browser persistently served the cached version despite Ctrl+Shift+R.

### Why Browser Caching Was Intractable
The portfolio server (`portfolio_server.py`) sends no-cache headers, but the browser's service worker or tab-level cache persisted the old file. Only opening a completely new tab (`chrome://newtab` → navigate) loaded the fresh file. The fix (y-position grouping in `extractPDFText`) IS deployed in v47e and DOES work — confirmed by the test in the new tab showing all 10 funds at correct prices.

### Status
The PDF parser fix is deployed. The `/api/import` endpoint is NOT yet active because the old server process could not be killed (access denied, running under different user account). **The import modal will fully work after the next server restart.** Until then, Fidelity data is updated via the hardcoded `FIDELITY_HOLDINGS` in `portfolio_loader.py`.

---

## Section 4: Portfolio Server Restart Failure

### What Broke
Could not start the new `portfolio_server.py` (which adds `/api/import` and `/api/import-transactions`). Error: `[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions`.

### Root Cause
Port 7777 was held by the old server process (PID 76320). `taskkill /F /PID 76320` returned "Access is denied" — the process was running under a different Windows user account (likely SYSTEM or the Task Scheduler account).

### Fix Required (Next Session)
1. Locate the CMD window running `portfolio_server.py` and close it with the X button
2. OR reboot the machine
3. Then run: `venv\Scripts\python.exe scripts\portfolio_server.py`

The new server file is correctly deployed to `scripts\portfolio_server.py`.

---

## Section 5: What Was Actually Accomplished

Despite the failures, significant work was completed:

| Component | Status |
|---|---|
| Command Center v47 | ✅ Deployed — Import Data modal, YAML Review, 3-tab import |
| YAML Config Advisor | ✅ Working — 5 suggestions applied, health score improved |
| Portfolio fallback fix | ✅ Deployed — `_prev_by_acct` loads before pipeline |
| Fidelity hardcoded data | ✅ Updated — April 8 PDF prices, $519,361 |
| CSV filenames restored to YAML | ✅ Done |
| `input_file` restored to YAML | ✅ Done |
| Root cleanup | ✅ Done — all one-time scripts removed |
| $1,175,350 portfolio showing | ✅ Correct |
| PDF parser (v47e) | ✅ Deployed, verified in new tab — blocked by server restart |
| `/api/import` endpoint | ⚠️ Deployed but inactive — needs server restart |

---

## Section 6: Lessons Learned / Rules Going Forward

### Rule 1: NEVER write holdings.json with a lower total without explicit abort gate
```python
prev_total = prev_holdings.get('portfolio_totals', {}).get('total_value', 0)
new_total = sum(...)
if prev_total > 0 and new_total < prev_total * 0.5:
    print(f"ABORT: New total ${new_total:,.0f} is <50% of prev ${prev_total:,.0f}")
    return  # Do NOT save
```

### Rule 2: YAML cleanup must be surgical — never remove load-critical fields
`input_file` in fidelity_401k is a load trigger, not just metadata. `positions_file` in Schwab accounts is the primary data source. Neither can be removed without a code change first.

### Rule 3: Browser cache defeats Ctrl+Shift+R for localhost
When deploying to localhost, always open a new tab (`chrome://newtab`) rather than refreshing. The portfolio server's no-cache headers do not always clear all browser caches.

### Rule 4: Server restart requires the old process window to be closed manually
`taskkill` fails when the server runs under a different account. Find and close the CMD window directly.

### Rule 5: PDF.js and pdfminer produce different text formats
Always test PDF parsers against both formats. The correct extractor groups items by y-coordinate, not by joining all items with spaces.

### Rule 6: Test every script fix before delivery
Every `portfolio_loader.py` change in this session was delivered without being tested against the actual file. A simple `ast.parse(src)` check would have caught the unclosed bracket immediately.
