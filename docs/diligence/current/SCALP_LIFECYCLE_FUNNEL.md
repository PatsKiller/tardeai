# Scalp Lifecycle Funnel

**Status: PASS**  
_Generated: 2026-06-28T04:24:22.455809+00:00 | window: 30d_  
_Source: `python3 scripts/scalp_lifecycle_funnel_report.py --days N --json`_  

Read-only. No broker writes. Social-only signals are advisory (WATCH/WAIT) only.

> **Operator correction 2026-06-28: no confirmed momentum_scalp paper trades were expected; prior counts (e.g. 17 opened / 3 closed) were over-attributed (non-executed rows + unlinked direct-label row). Counts below reflect conservative TRUE attribution.**

**Confirmed momentum_scalp paper trades:** 2 closed (trade IDs [45, 22]); ambiguous/unlinked excluded (IDs [19]).

## Funnel stages

| Stage | Count | Source |
|-------|-------|--------|
| Social posts ingested | 5156 | ok |
| Unique tickers mentioned | 190 | ok |
| Social scalp scan rows | 1480 | ok |
| Scalp scans alerted (final GO) | 159 | ok |
| Scalp scans with discovery_trace_id | 0 | ok |
| Scalp final decision = GO | 37 | ok |
| Scalp final decision = WAIT | 1371 | ok |
| Scalp final decision = AVOID | 72 | ok |
| trade_ai_scans rows (scalp-eligible) | 29091 | ok |
| strategy_signals (momentum_scalp) | 74 | ok |
| Proposals (momentum_scalp) | 67 | ok |
| Proposals expired on intraday TTL | 0 | ok |
| Proposals approved for paper | 0 | ok |
| ACTUAL momentum_scalp paper trades opened (confirmed) | 2 | ok |
| ACTUAL momentum_scalp paper trades closed (confirmed) | 2 | ok |
| Confirmed closed winners (momentum_scalp) | 1 | ok |
| Unknown-strategy paper trades (ambiguous + mismatched) | 1 | ok |
| Ambiguous-attribution rows (direct-label, no lineage/fill) | 1 | ok |
| Non-executed momentum_scalp rows (cancelled/dedup — NOT trades) | 19 | ok |

## Conversion rates

| Transition | Rate |
|-----------|------|
| scan_to_signal | 5.0% |
| signal_to_proposal | 90.5% |
| proposal_to_approved | 0.0% |
| approved_to_opened | — |
| opened_to_closed | 100.0% |

## Validation gate (momentum_scalp)

- Closed paper trades: **2** (need ≥ 30)
- Win rate: **50.0%** (need ≥ 50%)
- Profit factor: **1.40** (need ≥ 1.3)
- Calendar months observed: **unknown** (need ≥ 6)
- **Gate met: False** — Validation gate NOT met — momentum_scalp remains TESTING (paper only); confirmed closed paper trades = 2 of 30.
- Live-ready claim: **False** (momentum_scalp is TESTING)

## Rejected / deferred reasons

| Decision | Count |
|----------|-------|
| SKIPPED_STRATEGY_CRITERIA | 368 |
| SKIPPED_RECENTLY_REJECTED | 338 |
| SKIPPED_OUTSIDE_RTH | 283 |
| SKIPPED_NOT_GO | 175 |
| CREATED | 170 |
| SKIPPED_LIQUIDITY | 156 |
| SKIPPED_DUPLICATE | 69 |
| SKIPPED_RECENTLY_CLOSED | 37 |
| SKIPPED_OPEN_TRADE | 17 |
| SKIPPED_NO_ANALYST | 14 |
| SKIPPED_LOW_SCORE | 5 |
| SKIPPED_STALE_QUOTE | 5 |
| SKIPPED_PREPROMOTION | 1 |

