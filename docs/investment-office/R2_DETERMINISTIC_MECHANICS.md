# R2 Deterministic Mechanics

Additive, unwired research-governance package. Authority: `READ_ONLY_ADVISORY`.

**Deterministic math is not financial truth.** A formula may be deterministic;
its inputs, conventions, dates, sources, and assumptions may not be.

## Package

`scripts/lib/research_governance/mechanics/`

| Module | Role |
| --- | --- |
| `common.py` | Units, input classes, day-count, dates, status envelope |
| `fixed_income.py` | Coupon/zero/callable: accrued, clean/dirty, YTM/YTC/YTW, duration, DV01, convexity |
| `etf.py` | Official vs indicative vs proxy NAV, premium/discount, TE/TD, spread, creation unit |
| `valuation.py` | Explicit FCF PV, Gordon TV, EV–equity, reverse DCF, sensitivity |
| `results.py` | Typed wrapper for R1 governed receipts |
| `references.py` | Formula registry (no fake book pages) |

Acceptance: `R2_mechanics` = R1 foundation + R2A-1..R2A-15.

## Statuses

`OK` · `UNAVAILABLE` · `INVALID_INPUT` · `AMBIGUOUS_CONVENTION` · `STALE_INPUT` · `UNSUPPORTED`

## Hard invariants

- YTW is UNAVAILABLE if the call schedule is incomplete.
- `30/360` without a variant is `AMBIGUOUS_CONVENTION`; use `30/360_US`.
- PROXY and INDICATIVE_NAV cannot be treated as OFFICIAL_NAV.
- WACC ≤ g is `INVALID_INPUT`.
- Missing debt/cash is `UNAVAILABLE` (never assumed zero).
- Units fail closed; percent ≠ decimal; USD ≠ USD millions.
- Results are governed only via `run_governed_fixed_income` / `etf` / `valuation` producers.

## Not in this phase

No live Alex/CIO/Telegram/report/retrieval wiring. No R3 Almanac. No R4.
No broker/order/stop/2FA. No production DB writes.
