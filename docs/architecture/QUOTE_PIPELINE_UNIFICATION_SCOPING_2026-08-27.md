# Quote Pipeline Unification — Scoping (Audit Finding H4)

**Status:** SCOPING ONLY — no code changed by this doc
**Date:** 2026-08-27
**Context:** docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md, finding H4. Operator
decision (2026-08-27): investigate and scope only; the actual migration is
deliberately not attempted in this pass — it touches order-sizing code and
needs staged rollout with side-by-side comparison logging, not a blind swap.

## Corrected framing

H4 as originally written described "34+ files bypassing canonicalization" —
querying different sources independently, disagreeing arbitrarily. That
overstates the shape of the problem. On inspection:

**All 31 of the "34+" files call the same shared function**,
`market_quote_provider.get_best_quote(symbol)` — they are not bypassing
canonicalization; they are correctly using one shared resolver. That
resolver already does real cross-provider canonicalization internally (tries
a `PROVIDER_CHAIN`, e.g. Schwab/Alpaca, picks the freshest via
`_quote_sort_key`, documents which providers were tried/considered).

The real disagreement is narrower and more structural: **two independent,
parallel quote pipelines, not 34 independent call sites.**

| Pipeline | Table | Written by | Provider priority |
|---|---|---|---|
| **Watch** | `market_quotes` | `watchlist_enrichment_sweep.py`, `external_market_data_ingest.py`, `api_v2.py` (3 separate writers) | Alpaca-primary, "kept current by the repricer" (`watchlist_enrichment_sweep.py:8`) |
| **Trading/proposals** | `market_quote_snapshots` | `market_quote_provider.store_quote()`, called from within `get_best_quote()` | Schwab-primary-when-fresher, Alpaca fallback ("Schwab beats stale Alpaca after hours," `market_quote_provider.py:564`) |

`watch_canonical_quote.py` (the module named in the original finding) is
honestly named and scoped — its own docstring says "Canonical **Watch** quote
selection," and it correctly reads only from `market_quotes`. It was never
claiming to be a platform-wide canonical layer; the finding's framing implied
otherwise.

## Why this matters (the real risk, confirmed)

Two symbols' worth of real evidence that this isn't hypothetical:

- The two pipelines have **different primary-provider preferences**
  (Alpaca-primary vs. Schwab-primary-when-fresher) — not just different
  refresh cadences, a structural reason they can disagree even when both are
  "fresh."
- No reconciliation step exists between `market_quotes` and
  `market_quote_snapshots` — confirmed via `grep` for cross-references
  between the two tables/writers; none found.

## Consumer inventory (31 files, `market_quote_provider`/`alpaca_read_client` direct importers)

Classified by what the quote value feeds into — this is the actual migration
prioritization a future effort should use, not file-count or alphabetical
order.

### Tier 1 — touches real order construction/sizing or execution gates (migrate first, most carefully)
`broker_proposal_autocal.py`, `broker_trade_plan_gate.py`,
`proposal_execution_readiness.py`, `approval_revalidator.py`,
`paper_execution_revalidator.py`, `auto_proposal_generator.py`,
`watchlist_proposal_bridge.py`, `small_cap_rotation_bridge.py`,
`strategy_signal_sync.py`, `broker_trade_litmus.py`,
`schwab_broker_trade_monitor.py`, `remediate_proposal_trade_plans.py`,
`broker_queue_hygiene.py`

### Tier 2 — proposal-adjacent analysis/enrichment (real $ figures shown to operator, not directly executed)
`broker_proposal_intel.py`, `proposal_enrichment_loop.py`,
`proposal_technical_snapshot.py`, `proposal_monitor.py`,
`incubator_proposal_promoter.py`, `profit_protection_advisory.py`,
`apply_paper_protection_adjustment.py`

### Tier 3 — paper-only, simulation, logging, one-off validation (lowest real-money risk)
`paper_trade_logger.py`, `momentum_scalp_fast_atm_runner.py`,
`momentum_scalp_paper_fast_path.py`, `simulate_momentum_scalp_paper_path.py`,
`simulate_paper_proposal_approval.py`, `audit_automated_open_trades.py`,
`session23e_validate.py`, `run_proactive_quote_refresh.py`,
`send_telegram_proposal_alert.py`, `alpaca_live_read_sync.py`,
`atm_market_open_watch.py`

### Special case
`api_v2.py` — 7 hits, mixed (serves both display and action endpoints);
needs its own per-endpoint classification, not a single tier assignment.

## Recommended fix shape (for whoever picks this up — not decided or started here)

**Prefer unifying at the write/storage layer over migrating 31 read call
sites.** Two real options, in order of preference:

1. **Point Watch's writers at the trading-side table.** Change
   `watchlist_enrichment_sweep.py`, `external_market_data_ingest.py`, and
   `api_v2.py`'s `market_quotes` inserts to instead call
   `market_quote_provider.store_quote()` (writing `market_quote_snapshots`),
   and repoint `watch_canonical_quote.py`'s reads at that table. **3 writer
   call sites** change, not 31 reader call sites — and every Tier 1/2/3
   consumer above is unaffected, since they already read the canonical table.
2. **Or the reverse**: make `get_best_quote()` read-through
   `market_quotes` when it's fresher, unifying on the Watch table instead.
   Less attractive — `market_quote_snapshots` already has the richer,
   multi-provider-chain resolution logic Tier 1 needs.

Either way, this is a **provider-priority decision** (does the platform
prefer Alpaca-primary or Schwab-primary-when-fresher as the single answer?)
as much as an engineering one — flag for operator sign-off before starting,
same caution as this audit applied to C1/C4.

**Do not** attempt migrating the 31 individual read call sites as the primary
strategy — that's the higher-risk, higher-effort path the original finding
implied was necessary, and per this scoping it isn't; the write-layer fix is
strictly smaller and safer.

## Validation plan for whoever implements this

1. Before any change: log both `market_quotes` and `market_quote_snapshots`
   values for the same symbol/timestamp for a sample window (e.g. 1 trading
   day, all Tier 1 symbols) to quantify how often and how far they actually
   diverge today — this scoping doc asserts the risk is real but did not
   measure its magnitude.
2. After unification: confirm zero Tier 1 consumers changed behavior
   unexpectedly (side-by-side comparison logging for at least one full
   trading day before removing the old table/path).
3. `docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md` finding H4 should be marked
   resolved only once Tier 1 consumers are confirmed unified — Tier 2/3 can
   follow at lower urgency.
