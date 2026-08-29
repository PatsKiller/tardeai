# Seasonality surface moved to Ken French (2026-08-29)

Wave 3A.3, operator decisions 1 and 2: swap the operator-visible seasonality
consumer off the synthetic file and re-grade off real market data. Numbers were
expected to move. They moved.

## BEFORE vs AFTER

Computed from `cio_seasonality_analytics`, which feeds `home.seasonality`,
`research_context.almanac_headlines` and `strategy_context.relevant_facts`.

| effect | BEFORE — synthetic 1950–2024 | AFTER — Ken French 1926–2026 |
|---|---|---|
| `august_general` | n=75, −0.069%, win 45.3%, **B** | n=100, **+1.153%**, win 63.0%, **X** |
| `august_midterm` | n=19, −0.688%, win 31.6%, C | n=25, +0.081%, win 64.0%, **B** |
| `september_general` | n=75, −0.195%, win 46.7%, B | n=100, **−0.771%**, win 51.0%, **B** |
| `september_midterm` | n=19, −0.584%, win 31.6%, C | n=25, −1.269%, win 48.0%, **B** |
| `best_six_months` | n=450, +1.123%, win 66.7%, B | n=600, +1.241%, win 66.8%, **B** |
| `worst_six_months` (May–Oct, compounded) | +1.317% | **+3.959%**, win 71.7% |
| **weak months reproduced** | **{6, 8, 9}** | **{2, 9, 10}** |
| **strong months reproduced** | {1, 3, 4, 10, 11, 12} | {1, 4, 6, 7, 8, 11, 12} |

### What changed, in words

**August's weak-month claim is contradicted.** On real 1926– data August
averages **+1.15% with a 63% win rate** — positive. The registry's grade **X**
means "reproduction contradicts the source claim's stated direction; do not
apply". The live product had been showing `grade=B` for a weak August, which
read as *independently reproduced* and was not.

**September survives.** −0.77%, win 51.0%, still grade B. The September
weakness claim reproduces on real data.

**October becomes a reproduced weak month.** The synthetic series could never
show this: it contains no crash. Real history contains 1929, 1987 and 2008.

**"Sell in May" remains a differential, not a negative half-year.** May–Oct
compounds to **+3.96%** with a 71.7% win rate; Nov–Apr to +7.68%. Stored as
`calendar_context`, `standalone_sell: False`, and a test asserts no calendar or
regime row carries an imperative.

## What was swapped, and what was not

Two resolvers, one rule — *a determinism fixture may be synthetic, an
operator-visible number may not*:

| resolver | returns | used by |
|---|---|---|
| `operator_monthly_series_path()` | `series/us_equity_monthly_french_1926.csv` | `cio_seasonality_analytics` → every operator surface |
| `us_equity_monthly_path()` | `us_equity_monthly_synthetic_1950_2024.csv` | `research_governance/almanac.py` only |

`research_governance/` was **not touched** (R1 allowlist untouched, per the
brief). Its determinism fixture is unchanged, which is operator decision 4:
keep the synthetic file, never surface it.

The operator series is generated from the ingested French factors by
`scripts/build_french_monthly_normalized.py`; `--check` regenerates and diffs,
and a test runs it so the committed file provably equals its source.

## Two bugs the re-grade exposed

1. **A duplicated enum.** `test_cio_strategy_seasonality` hand-copied a subset
   of `VALIDATION_GRADES` that omitted `failed_reproduction`, so it broke the
   first time any claim was actually contradicted. It now reads the module's
   own enum instead of a copy.
2. **One X poisoned a whole dimension.** `consult()` returned
   `contradicted_grade_x` if *any* matching fact was X, so a contradicted
   August blocked seasonality entirely. "Do not apply" is about that fact —
   August failing says nothing about September. X facts are now dropped, and
   only a dimension with *no* surviving A/B fact reports contradiction.

## Section B ingest

Added to `reference/library/series/`, all hashed, grade A:
Ken French **FF5** and **momentum** monthly, plus the normalised operator
series. Total library 972 KB.

`OFFICIAL_URL_ONLY` (grade B, `refresh: weekly`), with the reason recorded:
**Shiller** monthly 1871– and **Damodaran implied ERP** are legacy `.xls`, and
parsing them needs an `xlrd` dependency this PR does not add. Shiller is
registered as the intended *second* series for `OOS_START_YEAR=2000` checks —
never as a replacement for French as primary.

Per operator decision 3, FOMC minutes / Beige Book / FRBSF WP 2025-30 stay
`OFFICIAL_URL_ONLY` with `refresh: event` and are **not** committed.

### Regime facts (7, context only, `sample_n` + `as_of` on every row)

| fact | n | mean | grade |
|---|---:|---:|:---:|
| `spx_vs_ndx_rs_3m` | 118 | −1.08 pp | B |
| `spx_vs_ndx_rs_12m` | 109 | −4.99 pp | B |
| `vix_regime_lt15_next_3m_spx` | 38 | +1.30% | B |
| `vix_regime_15_to_25_next_3m_spx` | 60 | +3.75% | B |
| `vix_regime_gt25_next_3m_spx` | 20 | +6.72% | C |
| `yield_curve_inverted_next_12m_spx` | 25 | +20.19% | C |
| `yield_curve_normal_next_12m_spx` | 84 | +12.18% | B |

**Read these with the caveat, not the headline.** FRED's `SP500` series starts
in 2016, so every conditional above is drawn from a short, bull-dominated
window. That is why high-VIX and inverted-curve rows — which look
counterintuitively bullish — are graded **C** on sample size. They are
historical distributions, never thresholds: no row encodes "NDX at X → sell",
and grade D applies below n=8.

## Verification

- 165 tests green across the seasonality, library, gate and research-brain surface
- `telegram_sent` false; `cio_run` stays `DETERMINISTIC_PRODUCT`
- host dry: eligible jobs still collapsed, S5 not re-expanded, 0 paid calls
- pin verified by file content, not `git log` inside CURRENT
