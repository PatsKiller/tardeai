# Portfolio stress engine

Status:      ACTIVE
as_of:       2026-08-16T22:32:42-04:00
Measured at: efcc51365 / not measured

Deterministic scenario P&L. Calculates scenarios; never issues trades; never
invents sensitivity coefficients.

## Tiers

1. **CASH** — cash/cash-like shock is zero (unless an explicit FX/cash scenario).
2. **MAPPED_SECTOR** — explicit sector shock applied directly.
3. **SENSITIVITY_MODEL** — beta / duration applied only when the coefficient has
   a governed source (`approved_vendor`, `verified_regression`,
   `explicit_etf_lookthrough`, `sector_industry_mapping`,
   `duration_credit_characteristics`).
4. **FACTOR_MODEL** — sourced factor loadings × factor shocks.
5. **UNAVAILABLE** — no valid input; counted in `unmodeled_value`.

## Outputs

`portfolio_value`, `estimated_pnl`, `estimated_pct`, `cash_buffer_effect`,
`top_loss_contributors`, `top_gain_contributors`, `sector_contribution`,
`factor_contribution`, `unmodeled_value`, `coverage_pct`, `assumptions`,
`limitations`.

## Invariants

- Cash shock = 0.
- Sum of modeled position PnL = modeled portfolio PnL.
- Unmodeled positions explicit; `coverage_pct <= 100%`.
- One tier per position (no double counting of overlapping shocks).

## Scenario library

`broad_equity_minus_10`, `broad_equity_minus_20`, `nasdaq_minus_25`,
`rates_plus_100bp`, `rates_minus_150bp`, `credit_plus_200bp`, `oil_plus_40`,
`oil_minus_40`, `usd_plus_10`, plus custom.
