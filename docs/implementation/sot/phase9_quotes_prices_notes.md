# Phase 9 — one write module per store: `market_quotes` and `ticker_prices`

Branch `feat/sot-p9-quotes-prices`. 2026-09-13. Authority: READ_ONLY_ADVISORY; no broker,
order or execution code touched (api_v2.py contains such code; only the one hunk that wrote
`market_quotes` was edited).

## Result

| Store | Domain | Writer files before (baseline) | After | Write module |
|---|---|---|---|---|
| `market_quotes` | quote_price | 3 (`api_v2.py`, `watchlist_enrichment_sweep.py`, `external_market_data_ingest.py`) | **1** | `scripts/lib/writers/market_quotes_writer.py` |
| `ticker_prices` | technicals | 4 (`scrub_ticker_price_outliers.py`, `lib/redeploy_price_history.py`, `portfolio_repricer.py`, `price_db_sync.py`) | **1** | `scripts/lib/writers/ticker_prices_writer.py` |

Gate (`scripts/check_data_source_authority.py --json`) after the change:
`'market_quotes': 1, ... 'ticker_prices': 1` with `findings == []`.

### Why a `scripts/lib/writers/` module rather than the SQL inside the writer_target

The registry names `scripts/external_market_data_ingest.py` and `scripts/portfolio_repricer.py`
as `writer_target`. Both now **re-export** the write function (`write_market_quotes`,
`write_ticker_prices`) so either name works, but the SQL lives in `scripts/lib/writers/` because:

- the targets are CLI scripts with import-time side effects (`external_market_data_ingest`
  imports `finviz_http` at module load; `portfolio_repricer` is 970 lines of repricing logic).
  `api_v2.py` and the scrub must not drag those in to write a row;
- the gate counts *files* whose text contains the statement, so the lib file is the one counted
  writer and the targets, producers and tests must not repeat the phrase (they do not — the
  negative-control test asserts the matching file set is exactly the module);
- the modules import `receipt` relatively so they work under both the `lib.` and `scripts.lib.`
  spellings (the dual-import identity hazard recorded in `scripts/lib/__init__.py`).

## Public functions

`scripts/lib/writers/market_quotes_writer.py`
- `write_market_quotes(conn_or_cursor, rows, *, source, run_id=None, resolve_identity=True) -> WriteReceipt`
- `coerce_quote_row(row, *, source)`; constants `COLUMNS`, `REQUIRED`, `CONFLICT_RULE`

`scripts/lib/writers/ticker_prices_writer.py`
- `write_ticker_prices(conn_or_cursor, rows, *, source, on_conflict="nothing"|"overwrite", round_to=4|None, stamp_created_at=False, run_id=None, resolve_identity=True) -> WriteReceipt`
- `restore_ticker_prices_from_quarantine(conn_or_cursor, symbol, *, run_id=None) -> WriteReceipt` (the scrub's `--restore`, SQL verbatim)
- `sync_ticker_prices_from_market_quotes(conn_or_cursor, symbols, *, min_ratio, max_ratio, run_id=None) -> WriteReceipt` (price_db_sync's bounded INSERT..SELECT, SQL verbatim)
- constants `COLUMNS`, `CONFLICT_RULES`, `AUTHORITATIVE_SOURCES`, `RESTORE_SQL`

`scripts/lib/writers/receipt.py`
- `WriteReceipt` (`WriteReceipt@v1`): table, source, written_by, run_id, conflict_rule, rows_in,
  rows_accepted, rows_written (Σ rowcount), rows_rejected [{row, reason}], identity {symbol → guid},
  identity_lookup {symbol → RESOLVED|DERIVED_ALIAS|LOOKUP_FAILED|NOT_APPLICABLE}, statements.
- `resolve_subject_identity(row)`, `attach_identity(receipt, rows)`.
- Rejected rows are logged at WARNING on logger `tradeai.writers` and returned; never dropped.

Neither module commits: the producer owns its transaction exactly as before.

## Per-producer migration and what was preserved

| Producer | Legacy statement | Now | Semantics note |
|---|---|---|---|
| `watchlist_enrichment_sweep._price` | INSERT (symbol, price, day_change_pct, source='yfinance', fetched_at=NOW()) | `write_market_quotes(conn, [...], source="yfinance")` | `fetched_at` left to the column's DB default (`now()`), which is what the `NOW()` literal said. |
| `api_v2._protective_stop_refresh_quote` | INSERT (symbol, source='refresh:<p>', price, fetched_at=<event time>) via `_db_query(fetch=None)` | `write_market_quotes(db_adapter._get_conn(), [...], source=f"refresh:{source}")` + commit, rollback on error | **Kept, not removed.** api_v2 excludes `refresh:%` rows from its own step-4 read, but the other 13 direct readers and the `market_quote` projection take the latest row regardless of source, so an operator refresh gives them a fresher Schwab/Alpaca price than the 15-minute ingest. Removing it would change what they see. Same swallow-all `except: pass` as before; rollback added so a failed write cannot leave the thread-local connection in an aborted transaction. |
| `external_market_data_ingest.ingest_yfinance_quotes` | 13-column INSERT | one call per symbol, same 13 columns in the same order, `None` where `info` lacked the field | `fetched += rc.rows_accepted` (1 or 0) |
| `external_market_data_ingest.ingest_alpaca_quotes` / `ingest_finviz_quotes` | 6-column INSERT | same six columns | a rejected row (negative price) is no longer counted as fetched and falls to the next tier, where before it was written |
| `portfolio_repricer._sync_ticker_prices` | UPDATE today's row SET close_price, source='portfolio_repricer'; if rowcount 0 INSERT (…, CURRENT_DATE, …, now()) | `write_ticker_prices(cur, rows, source="portfolio_repricer", on_conflict="overwrite", round_to=None, stamp_created_at=True)` | Emits `INSERT … VALUES (%s, CURRENT_DATE, %s, %s, now()) ON CONFLICT (symbol, price_date) DO UPDATE SET close_price = EXCLUDED.close_price, source = EXCLUDED.source`. Same effect under the `(symbol, price_date)` unique index every other legacy writer already relied on; `CURRENT_DATE` and `now()` stay server-side; price written unrounded as before; count printed is rows accepted; rejections now printed. |
| `price_db_sync.sync_daily_prices` (finviz) | upsert `DO UPDATE SET close_price = EXCLUDED.close_price, source = 'finviz'` | `on_conflict="overwrite"`, `round_to=4` | `source = EXCLUDED.source` ≡ `'finviz'` since that is what is inserted. `today` (ISO string) is parsed to a `date` — same value psycopg2 would have had Postgres cast. |
| `price_db_sync.sync_daily_prices` (holdings) | `DO NOTHING`, `round(…, 4)` | `on_conflict="nothing"`, `round_to=4` | unchanged |
| `price_db_sync.sync_quotes_to_ticker_prices` | bounded CTE INSERT..SELECT from `market_quotes` | `sync_ticker_prices_from_market_quotes(cur, syms, min_ratio=…, max_ratio=…)` | SQL byte-equivalent after whitespace normalisation (golden test embeds the legacy text). The follow-up SELECT that lists skipped candidates for the jsonl quarantine is a read and stays in the producer. |
| `price_db_sync.backfill_yfinance_history` and `lib/redeploy_price_history.backfill_symbol_history` | `DO NOTHING`, `idx.date()`, `round(px, 4)`, count = Σ rowcount | `on_conflict="nothing"`, `round_to=4`, `.rows_written` | Rows are batched per symbol into one call instead of one execute per row inside the loop; the statements issued are identical. The producers' `px <= 0: continue` pre-filter is kept so zeros stay quiet; **NaN closes, which `float(nan) <= 0` never caught and which were therefore insertable before, are now rejected with a reason.** |
| `scrub_ticker_price_outliers.restore` | INSERT..SELECT from `ticker_prices_quarantine` `ON CONFLICT DO NOTHING` | `restore_ticker_prices_from_quarantine(cur, symbol).rows_written` then the DELETE of the quarantine copies, same transaction, same order | Symbol is passed through un-normalised on purpose: the DELETE that follows uses the same argument and the two must select the same rows. The detector (`scan`, two-sided medians, single pass) and `apply_quarantine` (quarantine INSERT before live DELETE) are untouched; `tests/test_cio_gap_price_01.py::test_scrub_inserts_quarantine_before_live_delete` still pins that order. |

`DELETE FROM ticker_prices WHERE id = %s` (scrub) and `DELETE FROM ticker_prices_quarantine` remain in
the scrub: a different verb, outside the gate's regex by design, and the quarantine's own contract.

## Rails (one rule now, where each writer had its own `if not price` / `px <= 0`)

- price / close_price: finite, strictly `> 0`. Negative, zero (with or without volume), NaN, ±inf
  and non-numeric are rejected → receipt + WARNING log. Nothing is ever written negative or
  zero-with-volume.
- symbol non-empty; source non-empty; a `source` on the row may not contradict the writer's.
- market_quotes: unknown key → rejected row (the Finviz-shift failure mode is a value landing in
  the wrong column; an unknown key is the same smell). `fetched_at` must be a datetime/date/ISO string.
- ticker_prices: `price_date` must be a date / ISO string / pandas Timestamp, or `None` for the
  DB's `CURRENT_DATE`.
- The ratio-against-prior-close guard (`price_db_sync.is_price_outlier`, C3 Stage A) **stays in the
  producer**: it needs a DB read of the prior close per symbol and writes that producer's jsonl
  quarantine ledger; `tests/test_cio_pipeline_slice12_price_outlier.py` imports it from there.
  The set-based sync keeps its bound inline in the (verbatim) SQL.

## Identity — rules (a)–(e)

- **(e) applies: neither table has an identity column.** Evidence: every legacy INSERT's column
  list (13 distinct columns for `market_quotes`, 5 for `ticker_prices`), no DDL for either table in
  the repo, and the brief forbids running anything against the live DB. No column was added; no
  GUID is written. `test_neither_table_has_an_identity_column_so_none_is_written` pins it.
- **(a)/(b)** The receipt carries `subject_guid` per symbol through the existing resolvers only:
  `scripts.lib.cio_subject_guid.lookup_subject` (registry lookup, no mint, follows supersede chains
  via `identity_registry.resolve_guid`) → if the registry has no entity,
  `identity_registry.subject_guid_of(security_identity.resolve_identity_spine(row), symbol)`, which
  is security > issuer > ticker alias — the same GUID `identity_registry.register()` would mint for
  the row (test asserts equality with `register()`'s `by_symbol`). No UUID is computed in the writers.
  No legacy writer resolved identity at all, so there is no legacy difference to record.
- **(c)** Ticker is an alias: a symbol-only row resolves to `identity_registry.ticker_alias_guid`
  (defined once in `memory_fact.subject_from_security`); a row with cik/company resolves to the
  issuer-derived security GUID and differs from the bare alias (tests).
- **(d)** Autouse fixture pins `TRADEAI_IDENTITY_REGISTRY` to a temp file and clears
  `identity_registry._CACHE`; the supersede-chain test builds its own minted registry there.
- Identity lookup failure is `LOOKUP_FAILED` on the receipt and never rejects a price row (no
  legacy writer needed identity to write). `resolve_identity=False` is available for hot loops.
- CASH/PORTFOLIO/MMKT → `NOT_APPLICABLE`, `None` (cio_subject_guid's rule).

## Proposed migrations (operator grant required — not done here)

1. `ALTER TABLE market_quotes ADD COLUMN subject_guid uuid; ALTER TABLE ticker_prices ADD COLUMN subject_guid uuid;`
   then have the two writers populate it from `WriteReceipt.identity` (already resolved). Backfill
   via `identity_registry.lookup_symbol` over distinct symbols; never rewrite a GUID once set.
2. Provenance columns the brief asks for but the tables lack: `written_by varchar`, `run_id varchar`
   on both. `ticker_prices.created_at` exists (repricer stamps `now()`; others take the default);
   `market_quotes.fetched_at` exists (default `now()`). The receipt already carries all three.
3. Verify with `\d ticker_prices` that the `(symbol, price_date)` unique index exists — every legacy
   writer's `ON CONFLICT (symbol, price_date)` and the repricer's upsert depend on it.
4. Consider a `market_quotes` CHECK `(price > 0)` and `ticker_prices` CHECK `(close_price > 0)` so
   the rail is enforced by the store as well as the module.

## Registry / baseline proposal (for the integrator; files not edited here)

`config/data_source_authority.json`:
```json
{"domain": "quote_price", "writer": "scripts/lib/writers/market_quotes_writer.py",
 "writer_status": "CONSOLIDATED", "writer_target": "scripts/external_market_data_ingest.py",
 "_writer_note": "Phase 9 (2026-09-13): 3 writer files -> 1. external_market_data_ingest re-exports write_market_quotes; api_v2 and watchlist_enrichment_sweep call it."}
{"domain": "technicals", "writer": "scripts/lib/writers/ticker_prices_writer.py",
 "writer_status": "CONSOLIDATED", "writer_target": "scripts/portfolio_repricer.py",
 "_writer_note": "Phase 9 (2026-09-13): 4 writer files -> 1. portfolio_repricer re-exports write_ticker_prices; price_db_sync, redeploy_price_history and the scrub call it."}
```
`config/data_source_authority_baseline.json`: `writers.market_quotes 3 → 1`, `writers.ticker_prices 4 → 1`
(regenerate with `--write-baseline`). `tests/test_data_source_authority_20260913.py::
test_unconsolidated_stores_have_a_shrinking_ceiling` will then stop requiring a ceiling ≥ 2 for
these two, and `test_every_domain_has_one_writer_or_declares_it_is_not_yet_consolidated` passes
because the writer path exists. Regenerate `docs/SOURCE_OF_TRUTH.md` from the registry.

## Tests

`tests/test_sot_phase9_quotes_prices_writers.py` — 45 tests: one golden per legacy writer (8 for
the row-based writers, 2 verbatim-SQL goldens for restore and the quotes→closes sync), 4
producer-level tests through the migrated code with fakes injected (scrub restore, repricer sync,
sweep backfill, alpaca ingest incl. a negative-price row stopped at the rail), the api_v2 hunk
pinned by source text, 15 rejected-row cases, 6 identity tests, and the negative control (baseline
3/4 > 1, `count_writers` == 1, matching file set == the module).

Mutation: weakening the rail to `price < 0` makes the zero-with-volume case fail
(`test_market_quotes_rejects_off_rail_rows[row1-price: must be > 0]`: 1 failed, 7 passed); restored.

## Pre-existing failures (not caused here — reproduced on a pristine `origin/main` checkout)

`tests/test_redeploy_analytics.py::test_pro_forma_three_state_arithmetic`,
`::test_performance_distinguishes_price_and_total_return` (data-state assertions in
`redeploy_pro_forma` / `redeploy_performance`: SCHD `history_days: 1`),
`tests/test_cio_evidence_domain_wiring.py::test_store_construction_is_fail_soft`
(reads `cio_wake_dispatch_entrypoint.py`, expects a `CIOHealthBoundary()` call that is absent on
main). Same 3 fail on `origin/main` at 6644600c7 with an untouched tree.
