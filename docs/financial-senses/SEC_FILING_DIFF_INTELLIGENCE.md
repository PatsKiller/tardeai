# SEC filing diff intelligence

Status:      ACTIVE
as_of:       2026-08-17T12:35:13-04:00
Measured at: efcc51365 / not measured

`sec_filing_diff.py` compares two periods of company facts deterministically —
structured facts, not prose.

## Canonical keys

`revenue`, `operating_income`, `net_income`, `operating_cash_flow`, `capex`,
`cash`, `debt`, `shares`, `segment_metrics`.

## Comparison rules

- Values are compared only when both periods have the fact and units match.
- Unit mismatch, taxonomy change, or a missing period → `COMPARISON_UNAVAILABLE`.
- Duration facts must share equivalent duration context (annual vs quarterly vs
  YTD). Annual↔quarter and quarter↔YTD are `COMPARISON_UNAVAILABLE`.
- YTD facts are horizon-aware: a six-month cumulative (Q2 YTD) and a nine-month
  cumulative (Q3 YTD) both classify as YTD but are NOT like-for-like. Same fiscal
  period (Q2↔Q2, Q3↔Q3) or a within-tolerance span compares; a differing horizon
  → `COMPARISON_UNAVAILABLE`.
- Relative change computed as `(b - a) / |a|`; materiality thresholds per key.
- Net income sign flip is always material.
- Unmapped tags are reported, never silently compared.
