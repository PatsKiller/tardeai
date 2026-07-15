# Share Reconciliation (Dividend Reinvestment)

**Status:** Phase 1 — approval-based  
**Date:** 2026-07-15

## Problem

Automatic dividend reinvestment (DRIP) and small corporate actions change the **broker** share count while Trade AI calculations still use `holdings.json` → `shares` (system SSOT). Drift breaks stop sizing, risk %, and P&L.

## Model

| Field | Where | Meaning |
|-------|--------|---------|
| `shares` | holdings.json row | **Operational system shares** (stops, risk, MV) |
| `system_shares` | same | Explicit system book (mirrors `shares` after reconcile) |
| `broker_actual_shares` | same | Last live broker qty from Schwab/SnapTrade sync |
| `share_drift_status` | same | `aligned` · `pending` · `auto_applied` |
| `position_share_drift` | Postgres | Open / snoozed approval tasks |
| `position_reconciliation_log` | Postgres | Immutable audit of approved updates |

## Detection

After **Schwab** (`schwab_position_sync._build_account_rows`) and **SnapTrade** (`snaptrade_sync._merge`) sync:

1. Stamp `broker_actual_shares` from live qty.
2. If prior system shares exist and drift is **DRIP-like** (positive, ≤5% of prior, ≤200 shares absolute):
   - Keep **system shares sticky**
   - Open `position_share_drift` task (source usually `dividend_reinvestment`)
3. Trade-like deltas (large %) and new/sold lots still **auto-apply** broker qty.

Thresholds (env): `SHARE_DRIFT_TOL` (0.01), `SHARE_DRIFT_TRADE_PCT` (0.05), `SHARE_DRIFT_DRIP_CAP` (200).

## Operator workflow

1. Portfolio Holdings shows amber **Shares need update** pill + top banner.
2. Modal: system vs broker, optional stop/risk impact, live-stop warning.
3. **Update system shares** → `POST /api/v2/holdings/share-drift/apply`  
   - Writes holdings via `protected_holdings_write`  
   - Inserts `position_reconciliation_log`  
   - Closes open task  
4. **Snooze** 1d / 7d  
5. **Does not** cancel/replace live Schwab stops — user must use Replace mode if qty mismatches.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v2/holdings/share-drift` | Open tasks |
| GET | `/api/v2/holdings/share-drift/impact` | Stop/risk preview |
| GET | `/api/v2/holdings/share-reconciliation/history` | Audit log |
| POST | `/api/v2/holdings/share-drift/apply` | Approve update |
| POST | `/api/v2/holdings/share-drift/snooze` | Snooze task |
| POST | `/api/v2/holdings/share-drift/detect` | Rescan holdings.json |

## CLI

```bash
.venv/bin/python scripts/share_reconciliation.py --detect
.venv/bin/python scripts/share_reconciliation.py --list
.venv/bin/python scripts/share_reconciliation.py --history --symbol SCHD
.venv/bin/python scripts/share_reconciliation.py --apply-id 12
```

## Non-goals (phase 1)

- Auto-update without approval  
- Auto-replace broker stops  
- Tax lot reconstruction  

## Migration

`migrations/2026_07_15_share_reconciliation.sql` (also auto-created by `share_reconciliation.ensure_tables()`).
