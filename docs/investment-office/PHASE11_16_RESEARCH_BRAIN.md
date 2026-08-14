# PHASES 11–16 — Research-brain foundation (dry-testable)

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` — context / risk-modifier only.  
**Not:** autonomous execution, broker orders, standalone sells, TRIM-from-August, full-text books, partisan presidential conclusions.

This phase **replaces the 3-seed unverified scaffold** (`sta_september`, `sta_best_six_months`, mechanical cycle) with a real, still-honest research architecture plus a Stock Almanac **reproduction** engine.

`STOCK_ALMANAC_INTEGRATION` and `BROADER_RESEARCH_BRAIN` acceptance categories remain **FAIL** until a later live-integration gate. This document is a foundation closeout, not an integration claim.

## 1. What shipped

| Module | Role |
| --- | --- |
| `scripts/lib/cio_research_registry.py` | `ResearchSourceRegistry`; grades **A/B/C/D/X**; public STA alert citations (title/URL/date) |
| `scripts/lib/cio_research_grader.py` | A robust / B useful / C exploratory / D source claim / X invalidated |
| `scripts/lib/cio_research_library.py` | Families: seasonality, trend, value, risk, breadth, macro, wealth/tax |
| `scripts/lib/cio_seasonality_analytics.py` | Monthly N/mean/median/win-rate/std + presidential-cycle conditioning + Almanac reproduction |
| `scripts/lib/cio_market_calendar.py` | Weekday/weekend; `pandas_market_calendars` or `exchange_calendars` if installed; else weekday + US federal holiday table. Options expiration = 3rd Friday, **not** day 15–21 |
| `scripts/lib/cio_research_retriever.py` | `retrieve_for_decision` / `retrieve_research_context` **before** synthesis |

Fixture (deterministic, no network):

`tests/fixtures/us_equity_monthly_sample.csv` — synthetic but statistically usable monthly % series, 1950-01 through 2024-12, with mechanical cycle labels.

## 2. Evidence grades

| Grade | Label | Meaning |
| --- | --- | --- |
| **A** | robust | Reproduced, adequate N, \|t\|≥2, OOS sign agrees |
| **B** | useful | Reproduced, usable N, directional; effect may be modest |
| **C** | exploratory | Small N, mixed signals, or weak effect |
| **D** | source claim | Citation only; no independent Trade AI reproduction |
| **X** | invalidated | Reproduction contradicts the claim direction |

Three layers are **never collapsed**:

`SOURCE CLAIM` → `TRADE AI REPRODUCTION` → `CURRENT APPLICATION`

## 3. Stock Almanac (no full text)

Public STA **investor alerts** are cited by **title / URL / date only**. Summaries are operator-structured. No book pages, no tables copied from the annual Almanac.

| Slice | Public alert (citation only) | Date |
| --- | --- | --- |
| August general | [August Almanac & Vital Stats: Stronger in Election Years](https://www.stocktradersalmanac.com/Alert/20240718_2.aspx) | 2024-07-18 |
| August midterm | [August Almanac & Vital Stats: No Reprieve in Midterm Years](https://www.stocktradersalmanac.com/Alert/20260716_1.aspx) | 2026-07-16 |
| September general | [September Almanac & Vital Stats: Worst Month of the Year 1950-2023](https://www.stocktradersalmanac.com/Alert/20240815_1.aspx) | 2024-08-15 |
| September midterm | [September Almanac: Worst Month Modestly Better in Midterm Years](https://www.stocktradersalmanac.com/Alert/20220818_1.aspx) | 2022-08-18 |

Functions (each returns `source_claim`, `trade_ai_reproduction`, `n`, `mean`, `win_rate`, `evidence_grade`, `oos_note`, `current_applicability`):

- `august_general()` / `august_midterm()`
- `september_general()` / `september_midterm()`

Reproduction uses monthly index returns (public feed if `allow_network=True` and yfinance works; otherwise the fixture). In-sample through 1999 vs OOS 2000–end is reported honestly.

**2026** is a mechanical `midterm_year` (`year % 4 == 2`). `partisan_conclusion` is always `null`.

**August** is **not** hardcoded bearish. It appears in the weak-month hypothesis **only after** `reproduced_weak_months()` ranks it from the monthly series.

## 4. Integration hook (capital plan)

`build_capital_plan_from_sources` now:

1. Builds seasonality context  
2. Calls `retrieve_research_context(now, symbols)`  
3. Attaches `plan["research_context"]`  
4. Then `compose_strategy_context(..., research_context=research)`

Influence cap: **≤10%** conviction / sizing *language*.  
Never a standalone sell. **Does not create TRIM from August.**

`compose_strategy_context` retrieves research itself when the caller does not pass a context.

## 5. Calendar

- Prefer NYSE via `pandas_market_calendars` or `exchange_calendars`
- Fallback: weekday + US **federal** holiday table (includes Columbus Day and Veterans Day; those are federal, not NYSE closures)
- Options expiration = third Friday (prior session if closed)
- `calendar_effects` no longer tags day 15–21 as expiration

## 6. Tests

- `tests/test_cio_research_brain.py` — grades, 2026 midterm, fixture reproduction, layered claims, no autonomous execution, August ≠ sell
- `tests/test_cio_strategy_seasonality.py` — STA seeds may be `partially_reproduced` when the fixture supports it

```bash
python3 -m pytest -q tests/test_cio_research_brain.py tests/test_cio_strategy_seasonality.py
```

## 7. Copyright / authority

- Summaries + citations only  
- No full-text STA book or newsletter body  
- No partisan presidential performance conclusion  
- No execution authority  

## 8. Honesty residual

This is a **dry-testable foundation**. Fixture statistics are synthetic-but-usable, not a CRSP/Bloomberg print. Do not claim Almanac integration or a broader research brain as production-accepted on the strength of this phase.

## 9. Fixture reproduction snapshot (2026-08-14)

Library facts by grade: **A 0 / B 3 / C 4 / D 4 / X 0** (11 facts).

| Slice | n | mean | win rate | grade |
| --- | --- | --- | --- | --- |
| August general | 75 | −0.07% | 45.3% | B |
| August midterm | 19 | −0.69% | 31.6% | C |
| September general | 75 | −0.19% | 46.7% | B |
| September midterm | 19 | −0.58% | 31.6% | C |

Reproduced weak months: **June, August, September**. August entered that set from the stats, not from a hardcoded bearish flag.
