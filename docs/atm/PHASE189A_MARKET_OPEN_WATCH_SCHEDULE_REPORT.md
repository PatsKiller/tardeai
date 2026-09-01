# PHASE 189A — Market-Open Watch Schedule Report

Status:      HISTORICAL
as_of:       2026-06-02T09:13:00-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~09:08 ET · Alpaca **paper** only

| Field | Value |
|---|---|
| Scheduler created | ✅ YES |
| Mechanism | Date-pinned cron one-shot (no user-systemd available; `atd` inactive) |
| Job name | `atm-market-open-watch-0930` |
| Scheduled time | **09:30 ET today (2026-06-02)** — cron `30 9 2 6 *` (system TZ = America/New_York) |
| Script (READ-ONLY) | `scripts/atm_market_open_watch.py` via `market_day_gate.sh` (holiday/weekend guard) |
| Cron line | `30 9 2 6 * cd $PROJ && bash scripts/market_day_gate.sh $PY scripts/atm_market_open_watch.py >> logs/atm_market_open_watch.log 2>&1  # atm-market-open-watch-0930` |
| Crontab backup | `backups/crontab_pre_phase189_*.txt` |
| Rollback / disable | `crontab -l \| grep -v 'atm-market-open-watch-0930' \| crontab -` |
| Paper account verified | ✅ YES — Alpaca account `PA3E93QWASV1`, status ACTIVE, `ALPACA_MODE=paper` |
| Alpaca broker verified | ✅ YES — `paper-api.alpaca.markets` reachable (read-only) |
| Live endpoint blocked | ✅ YES — no live keys/URL configured; adapter is paper-only |
| Level 7 | **PROHIBITED** |

## What the watch does (all READ-ONLY — no orders, no stops, no mutations)
1. ELMT live-quote revalidation (freshness, spread, eligibility verdict).
2. Open-position protection audit (DB stop vs **broker** stop order).
3. Broker stop verification against the Alpaca **paper** order book.
4. Trailing eligibility via STOP-V2.3 `recommend_stop()` (recommendation-only).
5. Counts: naked / protected-unrecorded / protected-tracked / take-profit-missing.
6. Writes `docs/atm/PHASE189F_MARKET_OPEN_REVALIDATION_REPORT.md` + log.

The script explicitly performs **no** order submission, stop placement/modification, trade
mutation, strategy-config change, or GO/WAIT change. It is a pure observability run.

## Note
A premarket dry-run of the watch already executed successfully at ~09:08 ET (read-only) to
validate the path; the authoritative run fires at 09:30 ET and refreshes 189F with live data.
