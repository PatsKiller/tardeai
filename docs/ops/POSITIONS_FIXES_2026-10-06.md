# Positions fixes and phase 1 — 2026-10-06

Operator, 2026-10-06: *"something is wrong portfolio and prices on homepage are off … validate with schwab"*,
then *"yes start phase 1 and fix all of it, document fixes, edit agents.md with correct source of truth …
also check alpaca and moomoo make sure they are correct."*

## 1. What was checked against the brokers

Live, read-only reads at about 10:15 ET through the existing read clients (no orders, no auth changes).

| Account | Broker | Command Center | Result |
|---|---|---|---|
| Schwab Rollover IRA | equity $1,149,017.41 · cash $777,901.28 | $1,148,986 · cash $777,901.28 | match (quotes minutes apart) |
| Schwab Roth IRA | equity $49,950.96 · cash $1,472.72 | $49,744 · cash $1,472.72 | value matches; **V basis wrong** |
| Schwab Taxable | equity $69,144.92 · cash $50,576.97 | $69,164 · cash $50,576.97 | value matches; **PFLT shares wrong** |
| Alpaca Taxable (live) | cash $5,000 · equity $5,000 · no positions | $5,000 | match; no paper value in live totals |
| moomoo Taxable (live) | cash $500.00 + NVDA 0.133 sh ($32.14) = $532.14 | $500 cash shown, $531 in Returns, dated 2026-09-28 | **NVDA hidden; data frozen at 09-28** |

Today's P&L from Schwab's own figures was about +$2,680, the same as the header's +$2,681.

## 2. Defects found and fixed

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | PL showed 1,000 sh at cost $1,766 (+944%); broker $18,398 | `check_basis_divergence` keyed stored basis by symbol only, read a field live rows do not carry, and checked every account's rows. It flagged PL's correct new basis and the caller **reverted** it. | Compare per (account, symbol) with `broker_avg_price × shares`, only for the account being synced. With `cost_basis_truth: broker` a flagged row is **rebased** to the broker. Basis was also corrected in place the same morning (`sync_basis_from_broker.py --apply`). |
| 2 | V Roth basis $39,951.37; broker $40,125.75 | `sync_basis_from_broker.py` tier 1 let an April CSV lot (130 sh) win because 130.4985 sh is within 1% | The CSV lot only answers when the broker reports no average price and `cost_basis_truth: broker` |
| 3 | PFLT 12.0071 sh; broker 12.1461 (reinvested dividend) | Reinvestment-sized increases were held "sticky" until an operator click; every earlier one was cleared by hand | Increases are applied from broker data, logged `auto_drip` in `position_reconciliation_log`, and open drift tasks are closed. Cost is rebased on the broker average. Config: `positions.share_drift_drip_auto` |
| 4 | moomoo frozen at 2026-09-28; ⚠ STALE badge; "session 2026-09-28" | `moomoo_live_read_sync.py` wrote holdings.json without the shared write lock; the repricer (same minute, ~60 s, holds the lock) wrote its older copy back | The merge now runs under `lib/holdings_write_lock.py`. The same unlocked pattern in `schwab_position_sync.py` and `sync_basis_from_broker.py` is fixed too. |
| 5 | moomoo NVDA (0.133 sh, $32) and small Schwab leftovers not shown | Hard-coded `< 50` filter in `/api/v2/portfolio/holdings` | Threshold is `positions.table_hide_below_usd` (set to 0: show everything the broker reports) |

## 3. Phase 1 — the positions store (shadow)

- `migrations/2026_10_06_positions_store_phase1.sql` creates five tables with `CREATE … IF NOT EXISTS`. Nothing is dropped.
- `scripts/positions_sync.py` is the **only** writer, enforced by a test. One run:
  1. writes a heartbeat row;
  2. reads all five live accounts;
  3. rebuilds lots and realized lots (FIFO) from the broker ledger;
  4. writes everything in one transaction.
- A run becomes `positions_current` only when all three Schwab accounts read OK. Alpaca and moomoo are optional and keep their last rows, with their own `as_of`, if they fail.
- `--check-fresh` returns exit code 2 when the last complete run is older than 30 minutes during market hours, or 72 hours when the market is closed.
- `--diff` writes the phase 2 shadow diff to `data/runtime/positions_shadow_diff_latest.json`.
- Dry run on 2026-10-06 at 10:13 ET: all 5 accounts read OK, 34 position rows, 178 open lots, 214 realized lots, status `complete`.

**Known gap (phase 2 work):** Schwab's ledger stores transfer quantities without a direction. Rebuilt lots therefore over-count: SCHG shows 12,000 against the broker's 2,000, from an in/out pair of 5,000 on 07-17. The run records these as `lot_checks` and does not correct them.

## 4. Steps that need the operator

1. **Merge the PR.** Agents cannot merge.
2. **Apply the migration on prod**: `psql … -f migrations/2026_10_06_positions_store_phase1.sql`.
3. **Deploy.** The release is the operator's grant. After the promote, restart the API, which runs on port 7777.
4. **Grant the cron**, then add the lane registry row in the same change:
   `9,24,39,54 9-16 * * 1-5 cd $PROJ && flock -n /tmp/positions_sync.lock timeout 240 $PY scripts/positions_sync.py --apply >> logs/positions_sync.log 2>&1`,
   plus `--check-fresh` and `--diff` after the close.
5. **Confirm the 30-minute stale threshold**, and approve the 10-trading-day proof (plan decisions).
6. Open since 10-05: download the Schwab Realized Gain/Loss CSV so the 33 basis-unknown sells ($901,194 of proceeds) can be priced.

## 5. Still open (not fixed here)

- **"Today" is computed three ways** at the same moment:
  - the header uses the snapshot's `day_change`;
  - Returns reprices on read with Finviz;
  - the Portfolio page sums table rows in the browser.

  The Home news tiles show Finviz `change_pct`, and the Portfolio rows show the repricer's %. The fix is one `day_pl()` accessor in `lib/portfolio_positions.py`, done as a phase 3 reader batch.
- **moomoo NVDA arrived at cost $0** (a promotional share). Returns counts the +$31 as gain when it is an inflow.
- **moomoo is still flagged retired.** `account_summaries.moomoo_taxable_live` says `retired: true` (2026-09-01), but the broker reports the account active.
- **Schwab reports SCHG Rollover `day_pl` as −$36,215**, which is a broker-side artifact. No surface uses `broker_day_pl` yet.

## 6. Afternoon: prices overwritten with stale values (fixed 2026-10-06)

At 12:01, 13:01 and 14:00 ET, 22 of 25 held positions dropped to Oct 2 cached prices with 0% day change. Today's P&L read about +$1,000 instead of about +$2,300.

**Writer:** `scripts/portfolio_live_monitor.py`, a cron-started loop (`*/20`, `flock -n`) that runs all day.
- It loaded the book once.
- Every hour it called `reprice_portfolio` on that in-memory copy and saved it with `save_state`.
- Its Finviz fetch came back empty, so the Yahoo/NAV fallback marked every Schwab row at a days-old close.
- The 12:01 and 13:01 runs were a process still running the pre-deploy release (promote restarts units, not cron loops).
- The 14:00 run was the fresh relaunch, so the design itself was at fault.

**Caught by** a watcher on `holdings.json` writes that recorded the running processes at each write. Prices were restored each time by rerunning the repricer.

**Fixes:**
- The live monitor no longer reprices or writes `holdings.json`. The `*/15` repricer is the only price writer.
- The repricer refuses to write when, in market hours, fewer than `positions.reprice_min_live_coverage` (0.5) of held symbols get a live quote. The last good marks stand, and it exits 3.
- The health agent raises `portfolio_stale_marks` (critical) when more than `portfolio_price_freshness.stale_marks_max` (3) held positions carry fallback marks in market hours. Its auto-remediation reruns `portfolio_repricer.py`, and tier-1 escalation pages the operator.
