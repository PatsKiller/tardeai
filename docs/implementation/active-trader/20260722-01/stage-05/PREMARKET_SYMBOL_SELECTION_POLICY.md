# Representative-Symbol Selection Policy

Pure, read-only, informational. Selects at most ONE strategy-representative U.S. common stock to sit
alongside the always-present baseline **US.AAPL**. Creates NO trade candidate, authorization, or
recommendation — it only widens the DATA-observation surface so Level 2 momentum suitability can be
judged on a symbol that actually moves premarket. AAPL alone cannot produce a suitability PASS.

## Filters (observation-surface filters, NOT strategy-profitability thresholds)
- U.S.-listed **common stock only**; exclude OTC, warrants, rights, units, options, ETFs, ETNs,
  preferred shares, and leveraged/inverse products (by type and by name keywords).
- Price **$1.00–$50.00**.
- Absolute premarket change **>= 5%**.
- Premarket volume **>= 100,000**.
- Fails closed on unknown security types (must be positively identified as common).

## Ordering (deterministic)
premarket turnover DESC, then premarket volume DESC, then symbol ASC.

## Output status
`SELECTED` · `NO_QUALIFYING_CANDIDATE` · `RANK_UNAVAILABLE` (endpoint None) · `INVALID_SOURCE_DATA`
(payload not a list, or all rows malformed).

Module: `scripts/active_trader/premarket_symbol_selector.py` (selector-version `premarket-selector-1`).
