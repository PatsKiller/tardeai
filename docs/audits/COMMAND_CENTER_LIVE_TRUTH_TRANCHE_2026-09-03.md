Status: PROPOSED
Date: 2026-09-03
Authority: bounded Command Center live-remediation tranche evidence

# Command Center Live Truth Tranche

This tranche closes three release-specific wiring defects observed from the served Command Center:

| Surface | Previous divergence | Corrective authority |
|---|---|---|
| Finviz enrichment | `/api/v2/finviz-enrichment` read a checkout-relative cache path while the release served persistent state | `data/portfolios/state/ticker_enrichment_cache.json`; missing symbols remain valid degraded responses |
| Alpaca portfolio | A successful read/write changed holdings rows but waited for an unrelated repricer for aggregate publication | `portfolio_repricer._recalc_totals` plus `compute_data_as_of`, published by the governed sync path |
| Watch Intelligence | A successful empty result had no explicit terminal empty state | `/api/v3/data-broker/watch-intelligence` remains the sole read contract; the UI renders a terminal empty state |

The change preserves the Data Broker boundary, carries read-only observation provenance, and does not
invoke broker-write or order paths. Runtime acceptance must verify these claims from the exact served
release and must remain release-identity-specific.
