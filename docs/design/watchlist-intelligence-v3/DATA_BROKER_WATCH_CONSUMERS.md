# Data Broker — Watch Intelligence consumers

Watch Intelligence is **not a side API**. It is a projection in the existing
`scripts/lib/data_broker` package, advertised next to `market_quote`,
`symbol_profile`, `reentry_decision_desk`, and the rest.

**Catalog (discover everything):**

```http
GET /api/v3/data-broker
GET /api/v3/data-broker/catalog
```

Contract: `watch_intelligence.broker.v1`  
Module: `lib.data_broker.watch_intelligence`  
Primary UI: `/v3/watch`

Endpoints:

- `GET /api/v3/data-broker/watch-intelligence`
- `GET /api/v3/data-broker/watch-intelligence/{symbol}`
- `GET /api/v3/data-broker/watch-filters`
- `GET /api/v3/data-broker/watch-lists`
- `GET /api/v3/data-broker/watch-reviews/{symbol}`

## Composes (existing broker domains)

| Domain in projection | Underlying store / module |
|----------------------|---------------------------|
| CanonicalQuote | `watch_canonical_quote` + market_quotes lineage |
| SymbolIdentity | `symbol_profiles` (same store as `data_broker.symbol_profile`) |
| StreetConsensus | Yahoo targets + `data_broker.analyst_rollup` |
| CatalystContext | `catalyst_events` / catalyst_record pattern |
| TradeAiDecision | decision_packets + projection |
| Cio/Agent reviews | immutable runtime artifacts only when fully provenanced |
| WatchMembership | operator_starred_symbols, holdings.json, screener_find_pins |

Write commands (not broker):

- `POST /api/v3/watch/commands/star`
- `POST /api/v3/watch/commands/list-membership`
- `POST /api/v3/watch/commands/alert`
- `POST /api/v3/watch/commands/refresh-data`

## Domain → consumer map

| Domain | Watch Intelligence | Portfolio | Re-Entry | Risk | Active Trader | Research Intel | Agents | Reports |
|--------|--------------------|-----------|----------|------|---------------|----------------|--------|---------|
| SymbolIdentity | card header | holdings name | closed symbol | symbol label | ticket symbol | desk identity | agent job symbol | narrative header |
| CanonicalQuote | price/change/freshness | mark-to-market | exit price context | stop distance | live ticket | idea pricing | review inputs | performance tables |
| WatchMembership | starred/held/origin filters | — | membership context | — | — | watch admission | job targeting | coverage counts |
| SavedListMembership | list filter | — | — | — | — | list cohorts | — | list snapshots |
| ScreenerOrigin | Screener Finds view | — | — | — | — | discovery lineage | — | origin stats |
| StreetConsensus | primary rating | — | — | — | — | Street desk | — | rating history |
| TradeAiDecision | state/action | — | re-entry gate | eligibility | readiness | decision band | action policy | audit exports |
| CioReviewArtifact | CIO box | — | — | — | — | CIO desk | CIO agent | digest reports |
| AgentReviewArtifact | Maria box | — | — | — | — | research narrative | agent ledger | artifact reports |
| CatalystContext | catalyst line | — | event risk | — | event halt | catalyst desk | catalyst agent | catalyst digests |
| IndustryComparison | catalyst vs industry | sector sleeve | — | concentration | — | peer desk | — | peer reports |
| RelativePerformance | rel perf summary | sleeve RS | — | heat | — | momentum desk | — | performance |
| FundamentalSnapshot | full symbol page | fundamentals | — | — | — | valuation desk | — | F/V reports |
| TechnicalSnapshot | support/R/tech | — | technical prior | — | setup | technical desk | — | tech reports |
| PositionContext | held badge | holdings | closed lot | exposure | open ticket | — | — | position reports |
| AlertContext | armed alerts strip | — | — | — | — | — | alert agents | alert audit |
| FreshnessAndLineage | quote/session/id | pricing stamp | stale exit data | — | quote age | evidence | artifact freshness | lineage export |

## Rules

1. Consumers read broker envelopes (`value`, `source`, `source_record_id`, `observed_at`, `freshness_state`, `quality_state`).
2. No consumer invents quote identity, Street rating, or LLM model names.
3. Page load of any consumer of this projection must not call providers.
4. Watch React layout is not a dependency of the broker contract.
