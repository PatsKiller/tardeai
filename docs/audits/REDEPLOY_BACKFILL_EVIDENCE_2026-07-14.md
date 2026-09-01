# Redeploy Historical Backfill Evidence — 2026-07-14

Status:      HISTORICAL
as_of:       2026-07-14T00:05:24-04:00
Measured at: efcc51365 / not measured

Part B acceptance evidence for the portfolio-wide capital-allocation book.
All runs **dry-run** (`apply=False`), read-only, against production `trade_ai`.

## Transaction universe

- `trade_transactions`: 655 rows spanning **2022-04-29 → 2026-07-14**
- Materiality: proceeds ≥ $500 (`MIN_PROCEEDS_USD`), cash/SPAXX excluded
- Idempotency: `event_key` unique (txn dedupe_key), duplicates impossible by constraint

## Dry-run counts by window

| Window | Material sells found | New events needed | Errors |
|---|---|---|---|
| All history (2022-04-29 →) | 144 | 0 | 0 |
| Last 365 days | 142 | 0 | 0 |
| Last 180 days | 71 | 0 | 0 |
| Last 90 days | 31 | 0 | 0 |

## Reconciliation vs `deploy_events` (via `/api/v2/redeploy/history`)

| Metric | Count |
|---|---|
| Sales found (full history) | 144 |
| Events already matched | 144 |
| Unmatched (events to create) | **0** |
| Duplicate events | 0 (unique `event_key`) |
| Open (unresolved proceeds) | 31 |
| Dismissed (incl. `historical_backfill_over_90d` policy) | 113 |
| Missing account mappings | 0 |

## Capital truth (book snapshot at audit time)

- Total historical proceeds evented: **$1,037,287**
- Production-evidence deployed dollars: **$0** (the only recorded fills were the
  quarantined phase_e test fixtures — see `REDEPLOY_FIXTURE_AUDIT_2026-07-13.md`)
- Unallocated remaining across 31 open events: **$341,975.91**
  - `schwab_rollover_ira`: $254,855.63 open-event remaining (incl. FCNTX #144 $107,023.01), $17,540.67 visible cash
  - `fidelity_rollover_ira`: $60,103.80 open-event remaining (SMCI #134, HPE #128, GCTS #127), $108,180.39 visible cash

**Conclusion:** the sale-event detector's coverage is already complete — no
backfill apply run is required. The gap the capital book closes is *visibility*
(these 31 open events and $342k of unallocated proceeds were previously only
reachable one event-modal at a time), not detection.
