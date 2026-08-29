# CIO institutional corpus map (2026-08-29)

What is on disk today, where it lives, and whether the research gate consults
it. Written before building the gate so the gate queries what exists instead of
minting a parallel store.

## Verdict: `CORPUS_UNLOCATED` for the 20–30 publication set

There is no store of 20–30 named institutional publications. The closest thing
is `cio_research_library.library_facts()` — **11 structured facts across 7
families**, all defined in code, not ingested documents.

Directories searched (repo + host, depth 4):

    CURRENT/data, CURRENT/tests/fixtures
    persistent-state/data/{cio,hermes,research,runtime,portfolios,health}
    trade-ai-releases/{agent-jobs,portfolio-server/*}
    name globs: *corpus* *publication* *almanac* *rag* *knowledge* *kb*
                *librar* *book* *transcript*

No transcript store exists. No PDF/book ingest exists. Nothing was scraped to
fill the gap, per the prompt.

## What actually exists

| store | path | records | as_of | consulted today |
|---|---|---:|---|---|
| Research library | `scripts/lib/cio_research_library.py` (code) | **11 facts / 7 families** | static | yes — `strategy_context.relevant_facts` (3 surfaced) |
| STA public alerts | `scripts/lib/cio_research_registry.py` `STA_PUBLIC_ALERTS` | **4** (Aug + Sep only) | static | yes — via library |
| Seasonality series | `tests/fixtures/us_equity_monthly_sample.csv` | **901 rows**, 1950→ | static | yes — `seasonality` on `/home` |
| Earnings calendar | `persistent-state/…/state/earnings_dates.json` | **55 symbols** | 2026-08-24 | yes — `earnings` on `/home` |
| Momentum catalysts | `persistent-state/data/hermes/momentum_catalysts/*.jsonl` | **777 rows / 62 files** | 2026-08-26 | not by the research gate |
| Research results (reuse pool) | `persistent-state/data/cio/hermes_research_results.jsonl` | **471 rows** (470 completed) | 2026-08-29 | attach path only |
| Production cases | `persistent-state/data/cio/cio_production_cases.jsonl` | 31 MB | 2026-08-29 | CASE_SUMMARY |

### Family coverage of the library

    seasonality 5 | trend 1 | value 1 | risk 1 | breadth 1 | macro 1 | wealth_tax 1

Seasonality is the only family with real depth. Everything else is a single
placeholder fact, so a `corpus_hit` outside seasonality is currently unlikely
by construction — worth knowing before reading gate counters.

## Two things worth naming

**1. The seasonality series lives in `tests/fixtures/`.** It is *not* toy data —
901 rows of real monthly US equity returns from 1950 with cycle labels, and it
backs the `grade=B` / `grade=C` numbers on the live product. But a live surface
reading its authoritative series out of a test-fixture path is a location
smell: a fixture edit made for a test would silently move operator-visible
numbers. Not changed here (out of scope); recorded.

**2. The almanac facts are code seeds, not ingested sources.**
`default_seed_facts()` builds three `sta_*` facts and overlays reproduction
stats computed from the fixture. `license_class` is
`operator_structured_summary_no_fulltext` and validation is
`partially_reproduced` — the layering (source_claim ≠ reproduction ≠
application) is already correct and is preserved by the gate.

## How the gate uses this

`cio_corpus_index.py` is a **read-only adapter** over the above. It adds no
store and copies no facts. `corpus_hit` requires a fact whose family and
horizon actually match the question dimension — a seasonality fact may close a
seasonality question, never a bear-case question.
