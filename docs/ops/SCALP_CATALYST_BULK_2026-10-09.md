# Scalp lane bulk catalyst read — 2026-10-09

Operator, 2026-10-09: "APPROVE_AGENTS_POLICY_4_0_0 and build the finviz API fix".

## Problem

The 5-minute Trade-AI scalp lane (`scripts/run_trade_ai_scalp_live.py`, lane `trade-ai-scalp-live`) finished no run
between 13:27 and about 15:30 ET on 2026-10-09.

Every catalyst-cache miss went through `catalyst_enrichment.enrich_ticker`. That made about two Finviz requests per
ticker:
- the Elite news export without `v=3`, which returns market-wide news filtered by headline text and so is usually
  empty;
- then a quote-page scrape.

All Finviz traffic runs through the platform-wide throttle, `finviz_throttle`, which allows one request per
`FINVIZ_MIN_INTERVAL` (2.5 s) across every process. Once the 20-minute cache expired for the whole universe, the
lookups alone took longer than the lane's 295 s timeout. #1564 and #1572 stopped the loop of killed runs; they did not
remove the cost.

## Change

`scripts/scalp_catalyst_bulk.py` reads catalysts for the whole due set in bulk, in the order of
`config/trade_ai_scalp_lane.yaml` `catalysts.source_order`:

| Source | What it reads |
|---|---|
| `data_broker_news` | `news_articles` through `data_broker.catalyst_record.get_news_bulk`: one query, quote-page rows excluded, same-title rows collapsed |
| `finviz_elite_news_bulk` | The Finviz Elite news export with `v=3` (stock news) for `finviz_batch_size` tickers per request, through `finviz_http.finviz_get` and the shared throttle. Mapping uses the export's `Ticker` column. Dates are Eastern wall time, converted to UTC. |

Each symbol's articles go through `catalyst_enrichment.build_enrichment`. That is the classification half of
`enrich_ticker`, now split out, so scoring and catalyst verification see identical fields.

Fallback and failure handling:
- Up to `per_ticker_fallback_max` symbols that neither source covers still get the old per-ticker lookup, inside
  `enrich_budget_s` (#1572). The rest score on today's cached lookup.
- A 429 or a network error stops further batches. `finviz_get` publishes the global cooldown.

`continuous_runner.run_live_cycle` takes `bulk_catalysts=` (the config block). The full runner passes nothing and is
unchanged.

Timestamps are normalised to `YYYY-MM-DDTHH:MM:SSZ`. `catalyst_enrichment._parse_iso` rejects other offsets, so a DB
row in -04:00 would otherwise read as 9,999 hours old and be dropped.

## Measured, live, no writes (2026-10-09 ~15:28 ET, 76-name universe)

| | Seconds | Finviz requests | Covered |
|---|---:|---:|---:|
| Before: per-ticker `enrich_ticker` (6 names timed at 4.7 s each, extrapolated) | ~360 | ~152 | n/a |
| After: `enrich_bulk` | 18.2 | 8 | 64 of 76 |

Of the 64 covered names: 7 high impact, 5 medium, 36 low, 16 none. The 12 uncovered names are mostly closed-end funds
(MHD, MQY, MUC, NAC, NMZ, PML and others).

The data-broker news table covers only 9 of the 76 names in 72 hours. News ingestion follows the watchlist and
holdings, not the scalp screeners, so the Finviz export does most of the work.

## Known limits

- Each export request returns at most 100 rows. At 10 tickers a request, a heavy-news name can crowd out the others in
  its batch. Lower `finviz_batch_size` if coverage drops.
- Yahoo news is no longer read for bulk-covered names. The per-ticker fallback still reads it for uncovered names.
- The per-ticker `_fetch_finviz_news` still calls the export without `v=3` and parses its dates as UTC (they are
  Eastern). That path is unchanged here.
