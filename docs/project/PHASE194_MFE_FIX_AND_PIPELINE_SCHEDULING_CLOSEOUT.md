# PHASE 194 — MFE Units Fix + Protection Pipeline Scheduling — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T13:01:40-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~12:40–13:05 ET · Alpaca **paper** only · data-quality + ops; no execution

---

## What shipped
- **194A — MFE units fix (data-integrity):** `trade_execution_analyzer.py` wrote `mfe_r`
  (R-multiple) into `max_favorable_excursion` (a **percent** column) — corrupting units. Fixed to
  write percent. Reconciler now sources give-back from authoritative bar-based
  `trade_mfe_analysis` (`money_left` $, `mfe_price` %); no-bar trades are honest unknowns. Added
  `profit_left_on_table_usd`, `mfe_source` to outcomes.
- **194B — scheduling:** `scripts/run_protection_pipeline.sh` orchestrates the read-only/advisory
  chain; cron every 30 min market hours + 20:30 after close (holiday-gated). Proposal generator
  made idempotent (supersede). Execution step deliberately excluded.

## Corrected learning result (retracts Phase 193's 41.7%)
| Metric | Value |
|---|---|
| Closed trades | 24 |
| Measurable (bar-based MFE) | **3** |
| Unmeasurable (no entry/exit timestamps) | 21 |
| Of measurable, gave back profit | **3 / 3** |
| **Total profit left on table** | **$414.68** (ASPN $265, NVDA $103, INFU $46) |

ASPN is the textbook case: closed **flat** after peaking **+8.9%** — exactly what profit-protection
advisories target.

## Closeout fields
- **Phase 194 complete:** ✅ YES
- **MFE root cause found + fixed:** ✅ YES (dual-writer unit collision; analyzer now writes %)
- **Backfill:** 3 closed trades bar-validated; 21 nulled as honest-unknown
- **Reconciler authoritative-source:** ✅ YES (money_left $) — fabrication removed
- **Baseline finding corrected/retracted:** ✅ YES (41.7% → 3/3 measurable, $414.68)
- **Pipeline scheduled:** ✅ YES (orchestrator + 2 cron, idempotent)
- **Endpoint updated:** ✅ `/api/v2/atm/protection-advisory-outcomes` (measurable vs unknown + $ left)
- **No execution / no stop changes / no orders:** ✅ YES
- **Live trading:** ZERO · **Live endpoint:** blocked · **GO/WAIT mutation:** ZERO ·
  **Strategy mutation:** ZERO · **Level 7:** PROHIBITED
- **Next recommended gate:** **Phase 195 — fix trade-close timestamp capture** (21/24 closed trades
  lack entry/exit times → unmeasurable MFE; this is the deeper data gap), then accumulate advised-
  trade outcomes for threshold tuning, and surface outcomes in the v3 Journal/Learning hub.

## Secondary finding (Phase 195 candidate)
**21 of 24 closed paper trades have no entry/exit timestamps**, blocking bar-based MFE. The
`alpaca_sync`/adapter close paths don't always persist `entry_time`/`exit_time`. Fixing this makes
profit-left-on-table measurable for the whole book.

## Guardrail attestation
No live account/endpoint/broker mode, no live trades, no holdings mutated, no stops moved/cancelled,
no strategy configs changed, no GO/WAIT logic changed, Level 7 not enabled, auto-update not run.
Writes limited to MFE columns, outcomes table, proposal status, and 2 cron entries (rollback documented).
