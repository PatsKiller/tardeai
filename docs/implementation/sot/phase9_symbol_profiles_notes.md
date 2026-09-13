# Phase 9 — `symbol_profiles`: one write module

Branch `feat/sot-p9-symbol-profiles` · 2026-09-13 · domains `symbol_identity` + `earnings_date`

## What changed

| | before | after |
|---|---|---|
| files that INSERT/UPDATE `symbol_profiles` (gate census) | **8** (baseline ceiling) | **1** — `scripts/lib/writers/symbol_profiles_writer.py` |
| SQL statements for the table | 9 (build_symbol_profiles had two INSERT paths) | 2 templates in one function (`upsert_profile`) |
| column ownership | implicit — whatever each script's SQL named | explicit allow-list per lane (`LANES`); foreign column = rejected row |
| plausibility rails | scattered (expense-ratio cap in two files, nothing on RSI/vocab) | in the module, applied to every write |
| earnings UNKNOWN | never written, by the shape of the caller's `continue` | refused by the module with a reason (`write_earnings`) |
| identity | none | receipt carries `subject_guid` per row, registry-first |

### Where the module lives and why

`scripts/lib/writers/symbol_profiles_writer.py`, re-exported by `scripts/build_symbol_profiles.py`
(the registry's `writer_target`). The producer file is a CLI whose `run()` imports yfinance,
watch_universe and the holding-proxy map; the seven enrichers should not have to import a
producer to reach a write function, and `scripts/lib/` is importable from both `sys.path`
conventions in the tree (`lib.writers…` with `scripts/` on the path, `scripts.lib.writers…` with
the repo root). `build_symbol_profiles.py` stays the registry target and re-exports the public
surface, so `writer_target` remains truthful.

The module spells `INSERT INTO symbol_profiles` / `UPDATE symbol_profiles` literally rather than
interpolating a `TABLE` constant — the gate census is a regex over source, and a module whose SQL
never contains the table name would count as **zero** writers, which is a lie in the other
direction (observed while building: the first cut read `symbol_profiles: 0`).

### Public surface

```
upsert_profile(cur, symbol, fields, *, source, run_id=None, keep_existing_if_null=()) -> WriteReceipt
write_symbol_profiles(cur, rows, *, source, run_id=None, keep_existing_if_null=()) -> WriteReceipt
write_earnings(cur, symbol, *, state, next_earnings_date=None, last_earnings_date=None,
               last_eps_estimate=None, last_eps_actual=None, last_eps_surprise_pct=None, run_id=None) -> WriteReceipt
earnings_state_for(next_earnings_date, *, provider_answered) -> "SCHEDULED" | "NONE_SCHEDULED" | "UNKNOWN"
resolve_subject_guid(row) -> (guid | None, basis)
```

`WriteReceipt`: `table, source, written_by, run_id, written_at, rows_in, rows_written,
rows_rejected, written[{symbol, subject_guid, identity_basis, columns, rows_affected, mode}],
rejected[{symbol, reason, fields}]`. Rejected rows are also logged at WARNING.

### Lanes (the allow-list)

| lane (`source=`) | mode | columns | stamp |
|---|---|---|---|
| `yfinance` `finviz` `proxy_label` `manual` | INSERT … ON CONFLICT (symbol) DO UPDATE | description_1s, sector, industry (+ `source` column = lane) | `updated_at=now()` |
| `earnings_enrich` | UPDATE | next_earnings_date, last_earnings_date, last_eps_estimate, last_eps_actual, last_eps_surprise_pct | `earnings_updated_at` |
| `classify_instruments` | UPDATE | instrument_type, direction_hint, expense_ratio, quote_type | — |
| `validate_expense_ratios` | UPDATE | expense_ratio | — |
| `fund_technicals_enrich` | UPDATE | rsi14, perf_week_pct, perf_month_pct, ytd_return_pct, sma50_pct | `technicals_updated_at` |
| `distributions_enrich` | UPDATE | last_distribution_date, last_distribution_amount, distribution_cadence, next_distribution_est, ttm_distribution_amount | `distributions_updated_at` |
| `etf_performance_enrich` | UPDATE | ytd_return_pct, dividend_yield_pct, ttm_dividend | `perf_updated_at` |
| `etf_analyst_enrich` | UPDATE | analyst_look_through_pct, analyst_basis | — |

Legacy semantics preserved by explicit parameters, not by a second SQL path:

- **proxy_label** used to `ON CONFLICT … SET description_1s, sector, source, updated_at` — *not* industry.
  The base-lane conflict clause now covers exactly the columns the caller supplies, so the
  producer passes `{description_1s, sector}` and an existing industry is left alone. The INSERT
  still lists `industry` (NULL) for a new row, as before.
- **COALESCE keep-if-null** (`expense_ratio`, `quote_type` in classify_instruments; `ytd_return_pct`
  in fund_technicals so it never erases what etf_performance wrote) is `keep_existing_if_null=(…)`.
- `ytd_return_pct` is legitimately shared by two lanes (fund technicals computes it for mutual
  funds Finviz does not cover; etf_performance for ETFs). Both may write it; that is the
  pre-existing contract.

### Rails (all pre-existing, now in one place)

expense_ratio is a **fraction** in (0, 0.025] (`validate_expense_ratios.SANITY_MAX` now *reads*
the module constant); rsi14 in [0, 100]; instrument_type ∈ {stock, etf, fund, inverse_etf,
mutual_fund}; direction_hint ∈ {long, short}; quote_type non-empty, upper-cased; distribution /
dividend amounts ≥ 0; numerics finite (NaN refused); date columns must be dates (ISO strings
accepted); text columns must be text. An off-rail value rejects the **row** — the callers already
pre-filter exactly as they did, so no producer's observable behaviour changed.

### Earnings three-state model — preserved exactly

`earnings_provider` reads a row as **NONE_SCHEDULED** when `earnings_updated_at` is fresh and
`next_earnings_date` is NULL, and as **UNKNOWN** when the row is absent, never enriched, or stale.
Therefore:

- `SCHEDULED` requires a date → writes date + `earnings_updated_at=NOW()`.
- `NONE_SCHEDULED` (aliases `NONE`, `NONE_CONFIRMED`) forbids a date → writes NULL + `NOW()`.
- `UNKNOWN` → **no statement is issued**; the receipt carries the reason. The row keeps its old
  stamp so the reader still sees UNKNOWN and every event gate fails closed.
- `SCHEDULED` without a date is refused, not downgraded to NONE.

`earnings_enrich.py` derives the state with `earnings_state_for(nd, provider_answered=True)` after
`_extract`; a provider that returned nothing is reported in its JSON as `earnings_state: UNKNOWN`
and, as before, writes nothing. Test `test_unknown_is_never_coerced_to_none` pins this.

## Identity — rules (a)–(e)

- **(e) The table has NO identity column.** `migrations/2026_06_12_symbol_profiles.sql` declares
  `symbol TEXT PRIMARY KEY`; every later column was added by producer `ALTER TABLE … ADD COLUMN IF
  NOT EXISTS` and none is a GUID. I did not add one (test
  `test_table_has_no_guid_column_and_the_module_does_not_add_one` will fail the day someone does,
  so it is a deliberate act).
- **(a)/(b)** The module still resolves identity for every written row and returns it in the
  receipt, registry-first: `identity_registry.load_cached()` → `lookup_symbol()` (which follows
  `superseded_by` via `resolve_guid`) → the entity's active `subject_guid`; otherwise
  `security_identity.resolve_identity_spine(row)` → `identity_registry.subject_guid_of(spine, sym)`
  (security > issuer > ticker alias). Nothing is computed locally, nothing minted, and the module
  never writes to the registry (`test_write_module_does_not_mint_into_the_registry`).
  No legacy writer resolved identity at all, so there is no divergence to record under (b).
- **(c)** A symbol-only row round-trips to `identity_registry.ticker_alias_guid(sym)` ==
  `memory_fact.subject_from_security(symbol=sym)["subject_guid"]` — the one alias GUID the
  system already uses.
- **(d)** Autouse fixture pins `TRADEAI_IDENTITY_REGISTRY` to a temp file in every test.

## Proposed migrations (operator to grant — NOT applied)

1. **`subject_guid uuid` on `symbol_profiles`**, populated only through
   `resolve_subject_guid` (the module already computes it per row and would simply add it to the
   INSERT column list and the UPDATE SET). This is the identity anchor for sector/industry/
   instrument_type and today it is keyed by ticker only. Include `identity_basis text` so a
   CANDIDATE vs CONFIRMED vs alias-only key is auditable.
2. **Write provenance columns** `written_by text`, `written_at timestamptz`, `run_id text`. Three
   lanes (classify_instruments, validate_expense_ratios, etf_analyst_enrich) have **no** timestamp
   column at all, so nothing can say when their columns were last written; the receipt carries
   all three fields today, the table cannot.
3. **Move the six `ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS` self-migrations** out of
   the producers into `migrations/`. They are DDL (not matched by the writer census) and were left
   in place; they are the last schema authority that lives in producer code.
4. `earnings_state text` column (the `required_fields` of the `earnings_date` domain names it,
   but it is derived at read time today). If added, `write_earnings` sets it and the UNKNOWN rule
   still holds: UNKNOWN is never a stored value.

## Gates (verbatim, at HEAD of this branch)

```
$ python3 scripts/check_data_source_authority.py --json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['writers'],d['findings'])"
{'market_quotes': 3, 'symbol_profiles': 1, 'yahoo_analyst_targets_history': 1, 'news_articles': 16, 'ticker_prices': 4, 'sector_rs_daily': 1, 'market_regime_snapshots': 1, 'options_iv_history': 1, 'hermes_research_intelligence': 32, 'watch_directives': 18, 'watch_candidate_events': 1, 'private_company_proxies': 1, 'ticker_dividend_data': 1, 'fred_economic_series': 2, 'fundamental_data': 1, 'watchlist_agent_results': 1, 'agent_debate_log': 2, 'ai_reports': 4} []

$ grep -rnE "(INSERT\s+INTO|UPDATE|COPY)\s+symbol_profiles\b" scripts/ --include=*.py | grep -v /tests/
scripts/lib/writers/symbol_profiles_writer.py:…   (the only file)

$ python3 -m pytest tests/test_sot_p9_symbol_profiles_writer.py -q
42 passed

$ python3 -m pytest tests/test_data_source_authority_20260913.py tests/test_cio_canonical_identity.py tests/test_finviz_phase0_reconcile.py -q
3 failed, 58 passed   (the 3 failures call portfolio_options._get_earnings_dates; origin/main's
                       scripts/portfolio_options.py:72 reads "# _get_earnings_dates (FMP) removed
                       2026-09-13" — stale tests inherited from main, portfolio_options.py is not
                       in this branch's diff; all earnings_provider tests in that file pass)

$ python3 -m pytest tests/test_identity_registry.py tests/test_backfill_subject_identity.py tests/test_identity_memory_module_wiring.py tests/test_identity_lookup_failure_visible.py tests/test_cio_pipeline_slice15_subject_guid.py -q
62 passed

$ python3 scripts/check_dark_contracts.py      -> NEW (unexplained): 0
$ python3 scripts/check_line_endings.py --range origin/main..HEAD -> line-ending churn: none
$ python3 -m py_compile <9 touched .py files>  -> OK
```

## For the integrator

- `config/data_source_authority_baseline.json`: `writers.symbol_profiles` may fall **8 → 1**.
- `config/data_source_authority.json`: `symbol_identity.writer` can become
  `"scripts/build_symbol_profiles.py"` with `writer_status` removed (or point it at
  `scripts/lib/writers/symbol_profiles_writer.py` — the gate only checks the file exists);
  `earnings_date.writer` stays `scripts/earnings_enrich.py` (it is the producer; the SQL is in the
  module it calls).
- Test file: `tests/test_sot_p9_symbol_profiles_writer.py` (42 tests) — add to
  `scripts/run_cio_hardening_ci.py`.
- Not touched: `scripts/api_v2.py` (reads only), any broker/order code (grep for
  place_order/submit_order/cancel_order/2FA over all 8 producers: no hits).
