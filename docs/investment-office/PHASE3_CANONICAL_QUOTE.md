# PHASE 3 — Canonical quote fields (named price lineage)

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Version:** `cio_canonical_quote_1.0.0`

## Problem

Holdings rows overloaded `price` and `current_price` as if they were one
"current" mark. They are not:

| Shape | `current_price` | `price` | What it actually is |
| --- | ---: | ---: | --- |
| DXCM | Finviz last (quote) | `market_value / shares` | implied-from-MV, not a second mark |
| NOC (fractional) | real per-share mark | equals `market_value` | MV stuffed into `price` |
| Clean | one mark | same mark | `shares × mark = MV` |

FinancialTruthGate then preferred `current_price`, fired `dual_price_conflict`
on mark-vs-implied, and `shares_x_price_ne_mv` because broker MV used a
different mark than the quote.

## Contract

Module: `scripts/lib/cio_canonical_quote.py`

`apply_canonical_quote_fields(row) → row copy` (does not mutate input, does
not rewrite `market_value`).

| Field | Meaning |
| --- | --- |
| `canonical_mark` | The display / identity mark |
| `canonical_mark_type` | `live` \| `after_hours` \| `close` \| `unknown` |
| `canonical_mark_source` | Named source (`finviz`, `current_price`, `implied_from_mv`, …) |
| `canonical_mark_as_of` | Timestamp of that mark |
| `broker_position_price` | Broker per-share figure (or implied-from-MV when `price` is stuffed MV) |
| `broker_position_as_of` | Broker as-of |
| `official_close` | Prior / official close if present |
| `official_close_as_of` | Close as-of |
| `implied_price_from_mv` | `market_value / shares` when both present |
| `mv_basis` | `broker` \| `shares_x_canonical_mark` |
| `conflicted` | **Only** two genuine marks disagree |

`classify_row_conflicts(row)` uses the same named semantics.

### Hierarchy (do not blindly prefer `current_price`)

1. If `price ≈ market_value/shares` within **0.15%** and a quote is far from
   that, `price` is `implied_from_mv`, not a mark. `canonical_mark` = quote.
2. If `price ≈ market_value` and that number is **not** a per-share implied
   price (fractional / stuffed MV), `price` is not a mark.
3. If `price ≈ current_price`, `canonical_mark` = that value.
4. If one field is missing, use the other.
5. `conflicted=True` only when **two genuine marks** disagree (`current_price`,
   `last`, `mark`, or a `price` that is actually a mark). Official close is
   **not** a competing current mark.

Genuine marks **exclude** implied-from-MV and stuffed-MV `price`.

## Gate wiring

`scripts/lib/cio_financial_truth_gate.py` `check_position_row`:

- `dual_price_conflict` — two genuine marks only.
- `shares_x_price_ne_mv` — `shares × canonical_mark` vs broker MV, **labeled**
  `broker_mv_uses_different_mark`. This is a real book conflict when the
  broker MV sits on a different mark than the quote; it is not a dual quote.
- `mv_basis` on the position result: `broker` when the row carries broker MV,
  `shares_x_canonical_mark` only when MV is absent and must be derived.

## Repricer

`scripts/portfolio_repricer.py` fail-soft stamps the named fields onto
non-cash holdings after apply and after residual total guards. A thrown
annotate error never aborts the reprice loop.

## Tests

```
python3 -m pytest -q tests/test_cio_canonical_quote.py tests/test_cio_financial_truth_gate.py
```

## What a live reprice still has to clear

This phase **names** the fields. It does not unify broker MV with the quote.

Until the next live reprice (or broker refresh) writes `market_value` on the
same mark as `canonical_mark`:

- DXCM-shaped rows stay `shares_x_price_ne_mv` /
  `broker_mv_uses_different_mark` (no longer `dual_price_conflict`).
- G5 (zero material price conflicts) still fails while that residual exists.
- Meta `updated_at` vs `as_of` lag (Phase 2) is unchanged.

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  
