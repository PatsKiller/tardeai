# The 35,928 catalyst skips are not a registry gap

Date: 2026-08-30 · `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0`
Evidence: recomputed from source today; every figure below is `[VERIFIED]`.

## Why this needed recomputing

`catalyst_graph_latest.json` records `skipped: {symbol_not_registered: 35928,
entity_has_no_issuer: 2962}` and **discards the symbols behind them**. A tally
that keeps counts and drops its members is a hypothesis, not a measurement — it
cannot be audited, only quoted. It was being quoted as evidence that identity
resolution is the catalyst family's blocker.

Two things were wrong with reasoning from it:

1. The tally is from a **2026-08-27** graph build. Three days stale.
2. My own first recomputation used the wrong population. The momentum-catalyst
   feed has 777 rows / 275 distinct symbols, of which **13** are unregistered.
   Nothing like 35,928. The graph is built from the `catalyst_events` table.

## The real composition

From `catalyst_events`: **5,052 distinct symbols, 137,098 events.**
Registered 3,458 · **unregistered 1,594, behind 61,194 events.**

| bucket | symbols | events | what they are |
|---|---:|---:|---|
| research-directive slugs | 374 | **40,198** | `D124_EARNINGS_SEASON_OPTION_TRADING_FRAMEWORK`, `D107_ENERGY_TRANSITION_AND_TRADITIONAL_ENERGY` |
| ticker-shaped, unknown | 1,071 | **18,484** | `ASSET`, `SSDI`, `IRMAA`, `NEED`, `TO`, `STUDY`, `FIND`, `BSE` |
| ticker-shaped, **real** | **149** | **2,512** | `VIG`, `DGRO`, `EW`, `MCY`, `NOVA`, `RDCM` |

Validated against a 6,346-symbol real universe assembled from `ticker_prices`
and the Finviz quote cache.

**66% are not symbols at all** — research directive IDs written into the
`symbol` column. **30% are English words and acronyms** lifted from article
prose: `SSDI` is Social Security Disability Insurance, `IRMAA` is the Medicare
surcharge, `TO` and `NEED` are words.

**4% — 149 symbols behind 2,512 events — are the genuine registry gap.**

## The guard is not the defect

`catalyst_graph.py` refuses to bind an unregistered symbol, and its own
docstring gives the reason: *"an edge to the wrong company is worse than a
missing edge."* That is correct and stays. The noise is upstream: the extractor
is writing non-securities into a symbol column, and identity is correctly
declining to invent an entity for them.

## Three fixes, in this order — order is load-bearing

1. **Filter directive slugs at ingestion.** `D\d+_`-prefixed rows are not
   securities and must never reach identity. Removes ~40,198 drops.
2. **Constrain the extractor to a known ticker universe.** Any 1–5 uppercase
   run is not a symbol. Removes ~18,484.
3. **Register the 149 real names deliberately**, one at a time, each verified.
   Do not widen a rule to catch them — registration before filtering would mint
   `ASSET`, `SSDI` and `TO` into the registry permanently.

## On the 98.9% identity figure

P2-WS4's "98.9% resolvable" was measured on **production records** — holdings,
re-entry, watch names — symbols already owned or previously owned. Catalyst
intake is the opposite population: names not held. Both numbers are true of
their own population, and quoting 98.9% as evidence that identity is solved for
catalyst intake would be wrong.

The gap is real but it is **149 names wide**, not 35,928 — the difference was
58,682 rows of extraction noise that made a cleanup look structural.
