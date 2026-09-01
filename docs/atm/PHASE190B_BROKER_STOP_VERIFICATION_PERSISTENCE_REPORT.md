# PHASE 190B — Broker Stop Verification Persistence Report

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 09:47 ET · Alpaca **paper** only · Live endpoint blocked
**Script:** `scripts/verify_paper_trade_broker_stops.py` (READ-ONLY on broker; writes only
paper_trades protection metadata; never places/modifies/cancels orders).

---

## What it does
1. `ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS …` for the 11 missing protection columns.
2. GET the Alpaca **paper** order book (`paper-api.alpaca.markets/v2/orders?status=open`).
3. Match each open `paper_trades` row to a `sell/stop` order by symbol + qty.
4. Persist `stop_order_id, stop_verified_at, stop_verified_source='alpaca_paper_order_book',
   broker_stop_status, current_stop, protection_status, protection_defect_reason,
   profit_protection_status, last_broker_protection_check_at`.

A hard assertion refuses any non-`paper-api.` base URL (live-endpoint guard).

## Result (persist run)
| Metric | Value |
|---|---|
| Trades scanned | 6 |
| Broker stops found | 6 |
| stop_order_id persisted | 6 (3 already tracked + **3 backfilled**) |
| Backfilled (were untracked) | **SNOW, TMHC, ANY** |
| Unverified stops remaining | 0 |
| Unmatched broker stops | 0 |
| Errors | 0 |
| **Open trades without stop_order_id AFTER** | **0** |

## Persisted state (formerly untracked)
| Sym | stop_order_id | current_stop | broker_stop_status | protection_status | defect_reason |
|---|---|---|---|---|---|
| ANY | 8bfdde82… | 3.07 | new | PROTECTED_TRACKED | stop_order_id_backfilled |
| SNOW | 8737e56d… | 254.38 | new | PROTECTED_TRACKED | stop_order_id_backfilled |
| TMHC | f7347a29… | 68.02 | new | PROTECTED_TRACKED | stop_order_id_backfilled |

`defect_reason='stop_order_id_backfilled'` is an audit breadcrumb recording that the id was
recovered from the broker book rather than captured at submission (that source-capture is fixed
in 190C). The metadata **survived a subsequent 10:00 ET position sync** — persistence is durable.

## Guardrails
No order placed, modified, or cancelled. Broker interaction was GET-only. Paper endpoint only.
Schedule recommendation: add this verifier to cron (every 5–15 min, market hours) — see 190D/190I.
