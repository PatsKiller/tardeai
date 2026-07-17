# Fidelity Rollover IRA → Schwab (ACATS reflection) — 2026-07-16

## Operator report

Fidelity Rollover IRA assets are now at Schwab. Command Center still showed a **Fidelity Rollover IRA** book (~$566k) alongside **Schwab Rollover IRA** (~$583k), **double-counting** the rolled positions (e.g. SCHG 5000@Fidelity + 2774@Schwab while Schwab API already showed **7774** SCHG in one account).

## Live SSOT (Schwab API)

`get_positions('schwab_rollover_ira')` returned **20** equity positions including former Fidelity names:

| Symbol | Qty (live) | Notes |
|--------|------------|--------|
| SCHG | 7774 | was 2774 Schwab + 5000 Fidelity |
| SCHD | 6155.25 | was 4155 + 2000 |
| JEPQ | 1355 | was 355 + 1000 |
| ANET, ARKX, DIVI, XAR, DXCM, CSCO, QCOM | Fidelity-only → now on Schwab |
| CASH | ~$156k | SPAXX / cash consolidated |

Account equity (API): ~**$1.144M** (incl. cash).

## Actions taken

1. **Backup:** `data/portfolios/state/holdings.json.bak_fidelity_to_schwab_20260717T031925Z`
2. **Live** `sync_schwab_positions('schwab_rollover_ira')` — broker SSOT for that account
3. **Removed** all `fidelity_rollover_ira` holding rows (0 left)
4. **Account summary:** `fidelity_rollover_ira` → `status=closed_rolled_to_schwab`, `total_value=0`
5. **Basis:** combined SCHG/SCHD/JEPQ cost = fidelity lot + pre-ACATS Schwab lot (`fidelity_plus_schwab_pre_acats_sum`)
6. **Config:**
   - `assets/portfolio_accounts.yaml` — Fidelity closed, Schwab notes updated
   - `config/snaptrade_accounts.json` — **disabled** Fidelity SnapTrade map (prevents ghost re-import)
7. Portfolio total after dedupe: **~$1,264,328** (was inflated ~$1.27M with double-count of overlapping SCHG/SCHD/JEPQ + full fidelity book)

## UI expectation after hard-refresh

- Filters: **All**, **schwab_rollover_ira**, **schwab_taxable**, **schwab_roth** only  
- **No** “Fidelity Rollover IRA” active book / no **F** broker badge on those tickers  
- Former F names (ANET, ARKX, DIVI, …) under **Schwab Rollover IRA**  
- **Sync Schwab** remains SSOT; **Sync SnapTrade** no longer writes Fidelity IRA  
- **Sync Fidelity GTC stops** is legacy for closed account — stop targets should be managed on Schwab

## Verify

```bash
python3 -c "
import json
from pathlib import Path
from collections import Counter
d=json.loads(Path('data/portfolios/state/holdings.json').read_text())
print(Counter(h['account'] for h in d['holdings']))
print('fid rows', sum(1 for h in d['holdings'] if h['account']=='fidelity_rollover_ira'))
print('total', d['portfolio_totals']['total_value'])
"
# dry-run should show 0 added if already synced
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from dotenv import load_dotenv; load_dotenv()
from schwab_position_sync import sync_schwab_positions
print(sync_schwab_positions('schwab_rollover_ira', dry_run=True))
"
```

## Follow-ups

1. Re-arm **protective stops** on Schwab for positions that had Fidelity manual GTC stops (`config/fidelity_rollover_stops.json` is historical).  
2. Confirm SnapTrade still links a closed Fidelity account — leave unmapped.  
3. ~~Optional: hide closed `fidelity_rollover_ira` from account chips~~ — chips are derived from live holdings only; 0 Fidelity rows → no chip (verified 2026-07-16 evening).  
4. 401k **loan** tax treatment still operator-owned (YAML note retained).

## Post-migration verification (2026-07-16 ~23:20 ET)

| Check | Result |
|-------|--------|
| `holdings.json` fidelity rows | **0** |
| Live `/api/v2/portfolio/holdings` fidelity | **0** (accounts: schwab_rollover_ira / taxable / roth only) |
| Schwab dry-run sync | `added=[]` `removed=[]` |
| SnapTrade map | `accounts: {}` (Fidelity disabled) |
| Combined basis SCHG / SCHD / JEPQ | **260422.40 / 192864.67 / 81416.23** in holdings + `cost_basis_anchors` |
| Portfolio total (deduped) | **~$1.264M** |

**If Command Center still shows F badges / Fidelity chip:** hard-refresh the browser (Ctrl+Shift+R). The SPA polls `/api/v2/portfolio/holdings` every 60s with `cache: no-store`; a stale tab from before the write will still render the dual book until reload.
