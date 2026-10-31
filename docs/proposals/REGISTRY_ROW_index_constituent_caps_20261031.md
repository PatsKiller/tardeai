# Registry-row proposal: index constituent market caps (Market Risk Engine, event concentration)

```
Status:   PROPOSED — §7A row first, then a writer (AGENTS.md §7A, §17; operator decision §11 item 1 covers new stores)
Design:   DSN-20261031-market-risk-engine (P1-T6 event concentration)
as_of:    2026-10-31
```

## Why

The event category weights each upcoming earnings report by the reporter's share of index market cap. It needs caps
for the 35 largest constituents in `config/market_risk_policy.yaml` `event.index_universe`, and reads
"not measured" below 80% coverage.

Measured on the live database on 2026-10-31, read-only:

| Source | Names of the 35 with any cap | Fresh within 30 days |
|---|---|---|
| `market_quotes.market_cap` (registered) | 8 | 5 |
| `aegis_symbol_snapshot_nightly.market_cap_b` (not in the registry; not read) | 7 | 5 |

So the live engine reports earnings concentration as **not measured**. No registered store carries broad index caps.

## Candidate source (verified reachable 2026-10-31)

The Nasdaq public stock screener, `https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true`.
- One unauthenticated GET returns about 6,950 US listings, each with `symbol` and `marketCap`. It needs no key or
  credential, only a browser User-Agent.
- Sample from 2026-10-31: AAPL 5.09T, NVDA 5.15T, MSFT 3.94T, LLY 1.29T, BRK/B 1.20T, JPM 0.91T.
- Share class tickers use a slash (`BRK/B`). The writer maps them to the registry's dotted form (`BRK.B`).

Yahoo's v7 quote endpoint was also tested. It refuses without a session crumb ("Unauthorized"), so it is not usable.

## Proposed row (to append to `proposed_domains` after PR #2333 merges, to avoid a conflict)

```json
{
  "domain": "index_constituent_caps",
  "status": "proposed",
  "entity": "Index constituent",
  "title": "Market caps of the largest index constituents (event concentration weights)",
  "class": "external",
  "facts": ["symbol", "market_cap", "as_of"],
  "store": {"table": "index_constituent_caps"},
  "writer": "scripts/lib/writers/index_caps_writer.py",
  "provider": "nasdaq_public_screener (no key)",
  "cadence": "weekdays 06:20 ET and 16:45 ET",
  "stale_after_hours": 30,
  "freshness_sla": "30 h; below 80% coverage of event.index_universe the event category reads 'not measured'",
  "projection": "market_risk.index_weights (PgReader.index_weights)",
  "readers": ["Market Risk Engine (event, ai_concentration)"],
  "no_coverage": "say_so",
  "approval": {"status": "pending", "note": "operator §11 item 1 approved new stores for the engine; this provider was not named"}
}
```

## Until it exists

`PgReader.index_weights` keeps reading only the registered `market_quotes.market_cap`. The event card keeps saying
"not measured", and it names the missing caps. Nothing fetches the screener from inside the engine (§24.1 single
source).
