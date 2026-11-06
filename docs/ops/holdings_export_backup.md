# holdings.json is generated from the database (Steps 1–3)

Operator, 2026-11-03: the database `positions_current` is the holdings source of truth; `holdings.json` becomes a
generated backup. Operator, 2026-11-06 ("go with all three"): (a) the export renders every field the readers use,
(b) it runs right after every successful `positions_sync --apply`, and (c) the Home/API readers read the same render
from the database, with the file as the documented fallback.

## What the export does

- Renders the document from `positions_current` (bound to one complete, promoted `positions_sync_runs` receipt) plus
  its enrichment tables, and **carries** from the previous document only the fields other writers own (map below).
  A DB-owned fact is never taken from the file. A 0-byte, corrupt or row-less file carries nothing: the book renders
  from the database alone, the gap is stated in `gaps`, and the owning writers refill their fields on their next run.
- Writes atomically: unique temp in the target directory, `fsync`, `os.replace`, mode `600`, under the shared holdings
  write lock (`lib/holdings_write_lock.py`) so the carry and the replace are one read-modify-write with every other
  holdings writer.
- Refuses on a database failure, a zero-row result or a receipt that does not prove one complete run **before any
  write**; the last good file is left byte-identical.
- Totals are the repricer's own `_recalc_totals` (no second definition of a total); `positions_built_at` moves only
  when the position list changes (the repricer's fingerprint), stamped with the sync run's finish time.
- Retention under `<store dir>/backups/`: last **48 hourly** and **30 daily** snapshots, archived oldest-first with a
  size cap (default 64 MiB).
- Telegram **P1** when the export is **empty**, **older than 30 minutes during US market hours**, two consecutive sync
  runs failed, or the broker market values it carries (`portfolio_totals.broker_market_value_total`) differ from
  `SUM(positions_current.broker_market_value)` by **more than $1**. (`total_value` is the repricer's valuation of the
  same book — shares × canonical mark — and is not compared with the broker's figure.)

## Field ownership (field → source → how it reaches the reader)

Every field the served readers access (`tests/test_holdings_db_first_20261106.py` greps the reader modules and fails
on any field the export does not render) is in exactly one row of this table.

| Fields | Owner / source | How it reaches the reader |
|---|---|---|
| `symbol`, `is_cash`, `broker`, `account_key` | `positions_current` | rendered by the export every run |
| `account`, `account_id` | `positions_current.account_key` → store label (`schwab_roth_ira` → `schwab_roth`; every other key unchanged) | rendered; canonical readers map it back through `lib.account_display.canonical_key` |
| `broker_shares`, `broker_actual_shares` | `positions_current.qty` | rendered (DB wins) |
| `broker_market_value`, `broker_position_price` | `positions_current.broker_market_value` (÷ qty) | rendered (DB wins; previously a write-once repricer snapshot) |
| `avg_cost`, `broker_avg_price` | `positions_current.avg_cost` | rendered |
| `cost_basis_total` | `positions_current.cost_basis_total` (broker average × qty) | rendered |
| `asset_type` | `positions_current.asset_type`; the carried value only when the DB has none | rendered |
| `source`, `broker_source` | `positions_current.source` | rendered |
| `as_of`, `broker_position_as_of`, `broker_position_as_of_at`, `broker_ingested_at` | `positions_current.as_of` (the sync's capture instant), **full ISO-8601 UTC** | rendered; `lib/account_state.parse_time` reads the instant, `[:10]` readers get the date |
| `sync_run_id` (row and top), `sync_run_finished_at` | `positions_sync_runs` receipt | rendered |
| `sector`, `industry`, `profile_source`, `profile_updated_at` | `symbol_profiles` | rendered |
| `quote_price`, `quote_change_pct`, `price_bar_end`, `quote_inserted_at`, `quote_session`, `prior_close`, `reference_basis`, `quote_feed`, `quote_source` | `market_quotes_extended` (held symbols only) | rendered |
| `lookthrough`, `lookthrough_status` | `etf_holdings_snapshot` (not applied live: stated gap) | rendered |
| `shares`, `system_shares`, `share_drift`, `share_drift_status`, `shares_synced_at`, `last_reconciled_at`, `last_reconciliation_source` | share-reconciliation policy in `schwab_position_sync` (`share_reconciliation.stamp_broker_qty`) | **carried**; floor for a new row: `shares = system_shares = qty`, `aligned` |
| `quantity` | the rendered `shares` | rendered |
| `price`, `current_price`, `market_value`, `day_change`, `day_change_pct`, `gain_loss`, `gain_loss_pct`, `portfolio_pct`, `canonical_mark*`, `official_close*`, `analytical_*`, `mv_basis`, `implied_price_from_mv`, `price_source`, `price_field_role`, `current_price_is_alias_of`, `day_change_broker_check`, `updated_at`, `market_session`, `freshness_state`, `observation`, … | `portfolio_repricer` (every 15 min) | **carried**; floor for a new row: price = quote (else broker value ÷ qty), `market_value = broker_market_value`, day change = qty × (quote − prior close) or null, gain = value − basis |
| `broker_day_pl`, `broker_day_pl_price`, `broker_day_pl_at` | `schwab_position_sync` (Schwab's own P/L Day) | **carried** (no DB column) |
| `cost_basis`, `cost_basis_source`, `basis_status`, `basis_partial`, `lots_shares`, `conflicted`, `conflict_reason`, `_rebuild_source`, `_basis_rebased_from` | basis shield / tax-lot rebuild | **carried**; floor: `cost_basis = cost_basis_total` |
| `name`, `bucket`, `delisted`, `account_scope`, any other prior key | loader / sync | **carried**; never invented for a new row |
| top: `schema`, `generated_at`, `exported_at`, `updated_at`, `as_of`, `source`, `gaps`, `export_provenance` | the export | rendered |
| top: `data_as_of`, `data_as_of_account` | oldest row clock (`portfolio_repricer.compute_data_as_of`) | rendered |
| top: `positions_fingerprint`, `positions_built_at` | repricer fingerprint; the sync run's finish time when the list changed | rendered |
| top: `portfolio_totals`, `account_summaries` | previous keys carried, then the export's sums and the repricer's `_recalc_totals` (+ account state refresh) | rendered over carried |
| top: `resolved_sectors`, `resolved_sectors_by_account`, `resolved_sector_contributors`, `resolved_sector_underlyings`, `overlap_analysis`, `lookthrough_as_of` | `phase3_lookthrough_resolver` (16:10 cron) | **carried** |
| top: `last_repriced`, `reprice_source`, `closed_today`, `aggregate_published_at`, `_freshness_note` | `portfolio_repricer` | **carried** |
| top: `owner`, `_rebuild` | loader / holdings rebuild | **carried** |

Rows of an account the database does not sync at all are carried verbatim and named in `gaps`; a position the
database no longer holds is dropped (it was sold).

## Who writes holdings.json now

- `positions_sync.py --apply` → `holdings_export` (after a promoted run, under the holdings write lock).
- The enrichers above keep writing their own fields in place, as before, under the same lock.
- `schwab_position_sync.py` **still writes** the file (see "Not done" below). Its change to stamp
  `broker_position_as_of` as a full ISO-8601 UTC instant ships in a separate PR: that file is an always-held
  broker path and needs the operator's push.

## Readers (Step 3)

`scripts/lib/holdings_document.load_document()` returns the export's render built in memory from the database
(`document_source: "positions_current"`), with every carried field taken from the file exactly as the export would.
The file is the fallback when the database cannot be queried or answers but the render refuses; the document then
says `document_source: "holdings_json_fallback"` and `document_fallback_reason`. Freshness fails closed: each source
keeps its own clocks, and a stale-but-reachable database is served stale rather than swapped for a fresher-looking
file. A non-production store (fixture, offline copy) is read as a file and never reaches the live database. Cached
30 s per process. Switched readers: `lib/cio_truth.resolve` (Home do-now, desks) and
`lib/data_broker/portfolio_snapshot.build_portfolio_snapshot` (Home overview totals).

## Running it

    .venv/bin/python scripts/holdings_export.py --dry-run    # render and print, write nothing
    .venv/bin/python scripts/holdings_export.py --apply      # write the store and the backups (takes the lock)

Exit `1` means the export refused (database unreachable or empty) — the last good file is intact and the freshness
check still pages if it is stale. From `positions_sync.py`, a refusal is reported in the run summary under
`holdings_export` and never undoes the committed database run.

The unit `ops/systemd/tradeai-holdings-export.{service,timer}` is **not installed** and is no longer needed for the
render: every `positions_sync --apply` now runs the export and its freshness check. Proposal for the operator (§17):
leave the unit uninstalled.

## Not done in this step (and why)

- `schwab_position_sync` keeps writing holdings.json. Stopping it today would drop fields no DB table holds:
  `broker_day_pl*`, the share-drift decision and its approval tasks (`share_reconciliation`), delisted/CUSIP
  flagging, the basis shield and divergence flags, and the post-write hooks (holdings-change trigger, watchlist
  membership, cost-basis transfer detection). Those need DB columns or their own store before the sync can become
  the only writer.
- `api_v2._holding_source_timestamp` / `_protective_holding_truth` feed the protective-stop (order) gate — broker
  execution scope (AGENTS.md rule 2) — and keep reading the file, which the export keeps at parity.

## Authority

Read-only against the database. No broker call, no credential in code, no order, no schedule install.
