# Brave Research Router

**Status:** ACTIVE (library; operator surface deferred — see below)
**Authority:** `READ_ONLY_ADVISORY`
**MBI_BEHAVIOR:** 0
**Schema:** `BraveResearchRouter@v1`
**Module:** `scripts/lib/brave_research_router.py`
**As of:** 2026-09-03

## What this is

The single governed entry point to paid Brave Search. Every Brave query in this
repository goes through it. `scripts/brave_search.py` is a compatibility shim
that delegates here; it is no longer an independent client.

## The measured plan (do not re-guess it)

Measured live 2026-09-03 from `x-ratelimit-*` on a routed request:

```
x-ratelimit-policy: 50;w=1, 0;w=2592000
x-ratelimit-limit:  50, 0
x-ratelimit-remaining: 49, 0
x-ratelimit-reset:  1, 2339976
```

* **50 requests per second** (`w=1`).
* A 30-day window (`w=2592000`) the provider declares as `0` — it publishes
  **no metered monthly quota** on this plan.

Two things follow, and both matter:

1. The historical "1,000/month free tier" (in `brave_search.py`) and
   "2,000/mo free tier" (in `phase2b_analyst.py`) were **both invented**, and
   they disagreed with each other. Neither was ever measured.
2. `SEARCH_BUDGET_BRAVE_MONTHLY = 850` is therefore **local cost policy**, not
   a provider limit. It is a legitimate spend control; it must not be presented
   to an operator as "the plan allowance".

Read the windows by the largest `w`, never by `max()` of the values —
`max(50, 0) = 50` reports a 50-per-**second** plan as 50 per **month**.

## What Brave is for

| Purpose | Use |
|---|---|
| `EVIDENCE_GAP` | canonical free sources cannot answer a material question |
| `CATALYST_CORROBORATION` | a time-sensitive catalyst has only one source |
| `PRIMARY_SOURCE_DISCOVERY` | find the filing/release/ruling itself |
| `LONG_TAIL_DISCOVERY` | niche industry, supply-chain, legal, scientific |
| `SOURCE_DISCOVERY` | find durable feeds for later free ingestion |
| `SOCIAL_LEAD_DISCOVERY` | locate discussions when native feeds are down |
| `TRANSCRIPT_DISCOVERY` | find interviews; acquire transcripts elsewhere |
| `CONTRADICTION_SEARCH` | deliberately seek disconfirming evidence |

## What Brave is not for

`QUOTE_RETRIEVAL`, `BULK_SYMBOL_POLLING`, `PAGE_LOAD` and `SENTIMENT_SCORING`
are named `Purpose` values so that asking for one is `DENIED_POLICY` **with a
reason**, rather than quietly allowed. A page load must never reach a paid
provider.

## Guarantees

* **One ledger.** Spend is consumed atomically via
  `search_budget.try_consume` under an exclusive flock. Concurrent processes
  cannot both spend the last unit.
* **Fail closed.** An unreadable ledger denies and is never rebuilt as a fresh
  zero counter.
* **Durable cache.** Keyed by a normalised query fingerprint, stored under the
  state root, so it survives the process that filled it. Token *order* is
  preserved — "TSLA recall" and "recall TSLA" are different questions.
* **Coalescing.** Concurrent identical queries share one result.
* **Reserve.** A configurable share (default 15%) only `HELD_CAPITAL` and
  `URGENT_CATALYST` may draw on.
* **Per-purpose quotas.** Sum to at most `100 - reserve_pct`; asserted at
  import so they cannot silently consume the reserve.
* **Weekend deferral by priority**, not by caller name. Held capital and urgent
  catalysts are never deferred.
* **Distinguishable failures.** Every return is an `Outcome` with a `Status`
  and an operator-legible `degradation_note()`. `[]` is never the answer to
  "what happened?".
* **Attribution.** Every result is `SEARCH_DISCOVERY`. A Brave hit pointing at
  a Reddit or X page is a pointer to a discussion, never native sentiment and
  never verified fact.
* **No trading authority.** Asserted structurally by
  `test_router_holds_no_trading_authority`.

## Effectiveness, not volume

`effectiveness_report()` reports cache-hit and coalesce rates, non-empty rate,
unique domains, evidence gaps closed, **adoption**, calls per adopted evidence
item, remaining allowance and reserve, and four separate clocks:
`last_attempt`, `last_success`, `last_nonempty`, `last_adopted`.

A lane that spends and produces evidence nobody cites is
`PRODUCING_NOT_ADOPTED`, not healthy — `health()` fires
`brave_producing_not_adopted` for exactly that.

Call `record_adoption()` when a downstream research product actually cites a
result. Without it, adoption reads zero and the lane reports as unadopted.

## Budget projection

Worst-case cron volume for the routed lanes is ~1,028 calls/month against 723
usable after the reserve. The per-purpose quotas bound it to ~156/month.
See `BRAVE_BUDGET_PROJECTION.json` in the campaign evidence.

## Not yet wired

`effectiveness_report()` and `health()` have **no API route or Command Center
panel yet**: `scripts/api_v2.py` and the shared frontend were leased by an
unmerged campaign at the time of writing. The exact integration patch is in
that campaign's `DEFERRED_SHARED_PATH_INTEGRATION.md`. Until it is applied, the
metrics exist but no operator surface displays them.

## Tests

`tests/test_brave_research_router.py` (51) — allowance, concurrency, corrupt
ledger, cache, coalescing, reserve, quotas, error classes, attribution,
primary-source ranking, page-load denial, metrics, adoption, projection.
`tests/test_brave_no_bypass.py` (9) — repo-wide: only this module may name the
provider endpoint, send the subscription header, or resolve the API key.
