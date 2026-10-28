# yfinance snapshot feed — one Yahoo `.info` per symbol, read by the prospectus fund block

```
Status:      PROPOSED (branch feeds/yfinance-snapshot-20261026; lane yfinance-info-snapshot at SHADOW)
as_of:       2026-10-26T23:35:00-04:00
Measured at: base 27ac49d9e (origin/main); temp-root dry/apply proof with a stub DB; one live yfinance probe of a
             public index ETF (shape of .info + funds_data)
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Runbook-Id:  yfinance-info-snapshot
Tests:       tests/test_yfinance_info_snapshot_lane_20261026.py
```

**Why.** Operator decision 2026-10-26 (verbatim: "Yahoo Finance feed … switched on: yes"). The store
`yfinance_info_snapshot` was approved on 2026-10-10 (CONSOLIDATION_PLAN.md §D.13) with a migration, a single writer
and a broker projection, but no producer (§D.12) and the migration was never applied. The prospectus fund block
printed "assets under management: not held in any house store" for every fund.

## What runs

| Part | Path |
|---|---|
| Producer (owner lane) | `scripts/yfinance_info_snapshot_refresh.py` |
| Single writer (unchanged) | `scripts/lib/writers/yfinance_info_snapshot_writer.py` |
| Read path (unchanged) | `scripts/lib/data_broker/yfinance_info.py` (`get_info_batch`) |
| Migration (unchanged, **not applied**) | `migrations/2026_10_10_yfinance_info_snapshot.sql` |
| Lane | `yfinance-info-snapshot`: `config/lane_registry.json`, `config/n8n_run_allowlist.json`, `config/n8n_health_contracts.json` |
| Consumer | `scripts/lib/prospectus/etf_profile.py` (`yfinance_snapshot`, `fund_profile`), table rows in `extensions.fund_tables` |

**Universe** — never the scanner list: non-cash holdings with shares > 0 in any account
(`lib.portfolio_positions.load_store`), the operator's My Watchlist (`watch_domains.membership_operator`) and the
prospectus universe (`data/prospectus/universe.json`). Each symbol passes `lib.provider_ticker_guard` (profile
`quote`); CUSIP-like identifiers never reach Yahoo.

**Rate limits.** A symbol is fetched only when its stored row is older than 20 h (`ok`) or 168 h (`no_profile` /
`error`, the negative cache). At most 300 fetches per run, one at a time, 1 s apart (`--max-symbols`, `--sleep`).
A throttle (HTTP 429 / "Too Many Requests" / rate limit) stops the run; the rest is recorded as `rate_limited`.
Held names go first.

**Fund extras.** For `quoteType` ETF / MUTUALFUND the payload also carries `_house_fund`: `funds_data` top holdings
(symbol, name, weight %), the description and the overview (`family`, `categoryName`, `legalType`).

**Prospectus fund block.** With a fresh `ok` row (≤ 30 days, `config/prospectus.json`
`domains.yfinance_info_snapshot.stale_days`): AUM (`totalAssets`), issuer (`fundFamily`, else overview `family`),
inception (`fundInceptionDate`), index tracked (a capitalised "… Index" name in the description; Yahoo often writes
only "the index", and then it is a named gap), holdings count (only if published; Yahoo gives top holdings only).
Top holdings: the house look-through (`fund_lookthrough.json` / `fund_holdings_cache.json`) still wins; the snapshot
fills in only when the look-through has none. Table absent, row missing, stale or `no_profile`/`error`: every field
is a named gap exactly as before.

## Modes and exits

| Mode | Does |
|---|---|
| `--dry-run` (default; the SHADOW stage clamp passes it) | READ ONLY session; universe + store read; probes ≤ 3 symbols; prints `DRY-RUN {…}`; writes nothing |
| `--apply` | fetches what is due, writes through the single writer, commits, writes `data/runtime/yfinance-info-snapshot_last.json` (LaneRunReceipt v2 output fields) |

Exit 0 = run completed (rows written, or `nothing_due`); 1 = `unconfigured` (table missing),
`dependency_unavailable` (DB, store read, every fetch throttled/failed, write), `universe_empty_unexpected`.

## Operator steps

1. **Apply the migration (operator; additive, `CREATE … IF NOT EXISTS` only).** From the served checkout, as the
   application role so it owns the table:

   ```bash
   cd ~/trade-ai-releases/portfolio-server/CURRENT
   psql -h localhost -U trade_ai -d trade_ai -v ON_ERROR_STOP=1 -f migrations/2026_10_10_yfinance_info_snapshot.sql
   psql -h localhost -U trade_ai -d trade_ai -Atc "SELECT to_regclass('public.yfinance_info_snapshot')"   # expect: yfinance_info_snapshot
   ```

   Then update `config/data_source_authority.json` `domains[yfinance_info_snapshot].store_presence` /
   `cadence` in the canary PR (re-render SOURCE_OF_TRUTH / DATA_DICTIONARY).
2. **Shadow is live on merge + release**: the dispatcher fires weekdays 05:40 ET with `--dry-run`.
3. **Canary (a later registry PR):** allowlist `live_arg ["--apply"]`, registry `stage canary` + `dispatch.mode
   live`, contract `stage canary`; then add the lane to `TRADEAI_N8N_RELAY_LIVE_LANES` (host step). Rollback: revert
   that PR or drop the lane from the relay live list.

## Proof (2026-10-26, temp state root, stub DB, mocked provider)

```
== DRY
DRY-RUN {"dry_run": true, "lane_id": "yfinance-info-snapshot", "summary": {"due": 4, "fresh": 0, "over_cap": 0,
 "probe": {"ZZA": "ok", "ZZF": "ok", "ZZP": "ok"}, "sources": {"held": "ok (2)", "prospectus": "ok (1)",
 "watch": "ok (1)"}, "universe": 4, "would_fetch": 4}, ...}
rc 0 fetched ['ZZA', 'ZZF', 'ZZP'] inserts 0 readonly True
files: ['state/data/portfolios/state/holdings.json', 'state/data/prospectus/universe.json']
== APPLY
[yfinance-info-snapshot] wrote 4 snapshot rows (4 ok); receipt <tmp>/state/data/runtime/yfinance-info-snapshot_last.json
rc 0 fetched ['ZZA', 'ZZF', 'ZZP', 'ZZW'] inserts 4 readonly False
{"status":"ok","produced_count":4,"attempted_count":4,"skipped_reasons":{},"output_fields":"LaneRunReceipt@v2"}
```

A single live probe of a public index ETF returned `status ok`, `quoteType ETF`, 105 keys incl. `totalAssets`,
`fundFamily`, `fundInceptionDate`, and `_house_fund` with top holdings (symbol, name, weight %), description and
overview — the shapes the fund block reads.
