# Positions Source of Truth Plan

2026-10-05 · operator: John · living plan — every session executes against this file and updates the status table.
Readable copy (with diagram): https://claude.ai/code/artifact/1b51db7e-f6db-4a03-83bc-1bf333f299ad

We will move portfolio truth from holdings.json to database tables with one broker-sync writer, compute every price at read time from the Command Center data broker, prove it in shadow mode for 10 trading days, then switch readers over in batches. Nothing that serves the operator today changes until each step passes its gate.

## Status

| Phase | Status | Gate result | PR | Updated |
| --- | --- | --- | --- | --- |
| 0 — stop the bleeding | DONE — LIVE c96bec23c (#1456/#1457); 2026-10-06 live Schwab check: values + cash match, 4 defects found and fixed in the phase 1 PR (docs/ops/POSITIONS_FIXES_2026-10-06.md) | 4 issues → fixed in phase 1 PR | #1456 | 2026-10-06 |
| 1 — build in shadow | BUILT, PR open (operator approved 2026-10-06 "yes start phase 1 and fix all of it"); dry run read all 5 live accounts OK; awaits merge, migration, deploy and the cron grant | dry run green; first --apply run pending migration | wt/positions-phase1-20261006 | 2026-10-06 |
| 2 — prove it (10 trading days) | NOT STARTED | day 0 of 10 | — | — |
| 3 — switch reads in batches | NOT STARTED | batch 0 of 4 | — | — |
| 4 — retire holdings.json as a store | NOT STARTED | — | — | — |

## Why

All three failures share one cause: a stored copy whose writer stopped, while readers kept trusting it with no freshness check.

| When | What failed | Effect |
| --- | --- | --- |
| 2026-10-05 | `current_price` in holdings.json not refreshed by the repricer; tables read it instead of `price` | 22 of 27 positions shown at stale prices (SPCX $136.46 vs $171.09: −$8,272 shown, +$2,123 real) |
| 2026-07-03 | Dead database holdings tables retired (PR #58); holdings.json made the only store | 293 Python readers and 8 frontend files now depend on one file with many writers |
| 2026-04-19 to 05-09 | Database holdings writer and its JSON mirror died silently | Five live jobs (AI health checks, Hermes budgeting) used April holdings for months |

The fix is not "database instead of file". It is one writer, no stored prices, a freshness heartbeat, and a nightly check against the broker.

## Target architecture

```
Schwab API ─┐
moomoo ─────┤                         ┌──────────── Positions database ───────────┐      Data broker quotes
Alpaca live ┼──► positions_sync.py ──►│ position_snapshots · positions_current     │      (price + age, per read)
Fidelity    ┘    (the only writer,    │ position_lots · realized_lots              │──►        │
(manual)          heartbeat each run) │ positions_sync_runs                        │      One accessor
                                      └────────────────────┬───────────────────────┘   lib/portfolio_positions.py
                                                           ▼                                   │
                                          holdings.json (read-only export, tripwire)    Every surface:
                                                                                         Command Center, alerts, CIO, reports
```

Brokers feed one writer; every surface reads positions through one accessor and gets prices from the data broker at read time, so no screen can show a stored, stale price.

## Data model

Five new tables hold only what brokers report; no table stores a market price as truth.

| Table | Holds | Single writer | Fed from |
| --- | --- | --- | --- |
| `position_snapshots` | Every broker position per sync: account, symbol, qty, cost basis total, broker market value, `captured_at`, `sync_run_id` | `positions_sync.py` | Schwab (existing read path, `schwab_positions_live` today), moomoo, Alpaca live read, Fidelity manual entry |
| `positions_current` | One row per account + symbol: qty, cost basis, lots count, `as_of`, `source` | `positions_sync.py` (derived from the latest complete run) | `position_snapshots` |
| `position_lots` | Open lots: buy date, qty, unit cost, account | `positions_sync.py` | Broker transactions (`trade_transactions`) |
| `realized_lots` | Every sell matched to its lots: proceeds, cost, fees, P&L, method | `positions_sync.py` | Broker transactions; checked against broker realized gain/loss where available |
| `positions_sync_runs` | Heartbeat: run id, start, end, accounts OK/failed, row counts | `positions_sync.py` | — |

Rules that make the April and October failures impossible:

1. **One writer.** Only `positions_sync.py` writes these tables. A test fails the build if any other script writes them.
2. **No stored prices.** Price, value, day change and unrealized P&L are computed when read, from the data broker quote, and always shown with its age.
3. **One accessor.** Every reader goes through `lib/portfolio_positions.py`. A ratchet test fails on any new direct read of holdings.json or of the tables.
4. **Freshness contract.** If the latest complete sync run is older than 30 minutes during market hours, every surface shows "positions stale" and a health alert fires.
5. **Atomic runs.** A sync run commits all accounts or none; a partial run never becomes `current`.
6. **History kept.** Snapshots and runs are append-only, so "what did we hold at 10:07" is a query.
7. **Broker check.** A nightly reconciliation compares `positions_current` and `realized_lots` to the broker, and alerts on any gap above tolerance.

## Phases and gates

We build everything up front but switch nothing until each gate passes; every phase can be rolled back by flipping the accessor's source.

1. **Phase 0 — stop the bleeding (in progress).** Every surface computes price from the data broker; `current_price` reads retired; one accessor added; ratchet test blocks new holdings.json readers; full reconciliation of every holding and every sale against Schwab. **Gate:** reconciliation report shows CC = broker for all 27 positions within $1, and every closed trade matches a broker sell.
2. **Phase 1 — build in shadow (about 2 days to build).** Create the five tables, `positions_sync.py`, lots and realized-lot matching, heartbeat, and the nightly reconciliation job. The sync writes the tables alongside today's holdings.json; nothing reads them yet. **Gate:** builds green; one full sync run completes for all accounts.
3. **Phase 2 — prove it (10 trading days).** Run the day-by-day tests below; a nightly diff compares the tables vs holdings.json vs Schwab. **Gate:** 10 consecutive trading days with zero unexplained differences, every sync run complete, heartbeat never late.
4. **Phase 3 — switch reads in batches (about 1 week).** The accessor reads the tables, with a last-known-good snapshot as fallback if the database is down (marked stale). Readers move in batches: Command Center surfaces first, then alerts and the CIO, then reports, then everything else. **Gate per batch:** before/after outputs identical except prices that were stale; 2 days clean before the next batch.
5. **Phase 4 — retire (about 2 days).** holdings.json becomes a generated, read-only export from the tables with an `as_of` stamp and a tripwire if it falls behind; its old writers are removed (archived, not deleted). **Gate:** ratchet count of direct readers = 0; no writer of holdings.json except the export.

Estimated calendar: about 4 weeks from 2026-10-05, mostly the 10-day proof. Phase 0 lands this week.

## Day-by-day test plan

Each trading day of the proof tests one feature on live data; a day that fails is fixed and re-run before moving on.

| Day | Feature tested | How | Pass when |
| --- | --- | --- | --- |
| 1 | Position sync, all accounts | Every 15 min in market hours; compare to Schwab, moomoo, Alpaca live reads | Shares and cost basis match the broker for every position, every run |
| 2 | Read-time pricing | Value and P&L from data-broker quotes vs thinkorswim at 3 set times | Every position within 0.1% of thinkorswim; quote age shown on every surface |
| 3 | Lots and realized P&L | Rebuild lots and every sell since account open from broker transactions | Each closed trade matches a broker sell (qty, price, fees, date); totals match Schwab realized gain/loss where available |
| 4 | A live trade end to end | The operator's next buy and sell (or a scalp) | Shows in the tables within 15 min; realized P&L correct; Active Trader tags it to its alert |
| 5 | Writer failure | Stop the sync for 45 min on purpose | "Positions stale" appears on every surface; health alert fires within 30 min |
| 6 | Database outage | Block the accessor's database connection for 10 min | Surfaces serve the last-known-good snapshot, marked stale; nothing crashes; recovers on its own |
| 7 | Corporate actions | Dividend reinvestment (PFLT drift), any split | Share drift resolved from broker data; no manual edit |
| 8 | Concurrency | Repricer, stop sync, Active Trader and the CIO running at once | No partial reads; every read sees one complete sync run |
| 9 | Consumers | Command Center pages, alerts, CIO and reports read through the accessor (shadow comparison) | Outputs identical to today except corrected stale prices |
| 10 | Full day | All of the above together | Zero unexplained differences; nightly report clean |

The nightly reconciliation report goes to the operator on Telegram each evening during the proof: positions checked, differences found, and the cause of each.

## Risks and fallbacks

| Risk | Seen before | Fallback |
| --- | --- | --- |
| Sync writer dies silently | April 2026 | Heartbeat check every 15 min; stale banner on every surface; health alert |
| Database down or connection-starved | 36 idle-in-transaction kills on 10-05; power cuts in September | Accessor serves the last-known-good snapshot, marked stale; short read-only transactions only |
| Broker API down or token expired | Schwab token expiry 10-05 | Keep last complete run; mark stale; never blend a partial run |
| A reader migrated wrongly | 293 readers | Batches with before/after comparison; per-batch rollback by switching the accessor source |
| Lot method differs from the broker | Schwab cost basis vs thinkorswim's order-panel average (164.03 vs 148.37) | Use the broker's reported cost basis as truth; our lots must reproduce it, or the difference is flagged |
| Fidelity has no position API | Manual entries today | Kept as a labelled manual source with its entry date; never counted as broker-verified |

## Operator decisions

- [x] Approve the plan and the five-table design (2026-10-06, phase 1 start)
- [ ] Approve the 10-trading-day proof as the gate for switching reads
- [ ] Choose the stale threshold during market hours (proposed 30 minutes; set provisionally in config/portfolio_positions.yaml `positions_sync.stale_after_minutes_market`; operator may change it)
- [ ] Approve each reader batch switch (four approvals across phase 3)
- [ ] Approve retiring holdings.json as a store (phase 4)

## How we execute it

- **This file is the plan of record.** Every session reads it first, executes the next open step, and updates the Status table (phase, gate result, PR, date).
- **One PR per phase**, each with its own tests and gate registered in CI; nothing merges without green CI and the operator's release approval.
- **A daily progress line** in the evening Telegram report during the proof: day N of 10, feature tested, pass or fail, differences found.
- **The readable doc** (link above) is updated at each gate, with the result.
