# PHASE 190A — Protection Metadata Schema & Write-Path Audit

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~09:50 ET · Alpaca **paper** only · Read-only audit

---

## Schema audit (paper_trades — before Phase 190B migration)

| Field | Existed? | Action |
|---|---|---|
| stop_order_id | ✅ text | reuse as broker stop id |
| stop_verified_at | ✅ tstz | reuse |
| planned_stop | ✅ numeric | reuse (was unset on adapter path) |
| take_profit_price | ✅ numeric | reuse |
| stop_verified_source | ❌ | **added (190B)** |
| broker_stop_status | ❌ | **added** |
| current_stop | ❌ | **added** |
| stop_type | ❌ | **added** |
| take_profit_order_id | ❌ | **added** |
| profit_protection_status | ❌ | **added** |
| trailing_active | ❌ | **added** |
| trailing_policy_version | ❌ | **added** |
| protection_status | ❌ | **added** |
| protection_defect_reason | ❌ | **added** |
| last_broker_protection_check_at | ❌ | **added** |

`broker_stop_order_id` was **not** added as a separate column — `stop_order_id` already serves
that role; adding a duplicate would create a second source of truth. Documented decision.

## Write-path audit — who writes protection metadata, and the gaps

| Write path | File | Wrote stop id? | Gap |
|---|---|---|---|
| Proposal submitter → adapter (bracket) | `alpaca_paper_adapter.py` INSERT `:596+` | child leg only | `stop_order_id` not persisted; `planned_stop` unset |
| Adapter post-fill stop (market/ext-hrs) | `alpaca_paper_adapter.py:526-534` | **NO** — `_api_post` return discarded | the core bug (190C) |
| alpaca_sync onboarding | `alpaca_paper_adapter.py:155-166` | **NO** — `unknown_sync`, no stop/target/proposal | 190B backfill + future onboarding fix |
| paper_trade_monitor | `paper_trade_monitor.py:372-377` | only if `stop>0` | NULL stop → silent skip |
| unified_stop_supervisor | `unified_stop_supervisor.py` | no (report-only) | log-swallowed (190D) |
| broker reconciliation | `reconcile_stop_v21_broker_stops.py` | no (report-only, not in cron) | doesn't persist id |
| ATM dashboard API | `api_v2.py` | n/a (read) | no protection panel (190F) |
| journal writer | various | no | `planned_stop`/`stop_type` absent |
| Hermes safe views | `hermes_v_*` | n/a | no protection fields (190E) |

## Why ANY/SNOW/TMHC had broker stops but NULL DB fields
- **ANY, SNOW** — created by `alpaca_sync` onboarding (`:155-166`), which inserts `unknown_sync`
  with **no** stop/target/proposal/strategy metadata. The broker stops were placed out-of-band;
  nothing wrote them back to the DB.
- **TMHC** — created by the adapter market-order path; the post-fill stop **was** posted to the
  broker (`:526-534`) but the `_api_post` response (carrying the order id) was **discarded**, so
  `stop_order_id` stayed NULL and `planned_stop` was never set.

Remediation implemented in 190B (backfill/verify), 190C (capture at source), 190D (alerting),
190E (Hermes), 190F (dashboard).
