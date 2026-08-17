# SEC filing diff intelligence

`sec_filing_diff.py` compares two periods of company facts deterministically —
structured facts, not prose.

## Canonical keys

`revenue`, `operating_income`, `net_income`, `operating_cash_flow`, `capex`,
`cash`, `debt`, `shares`, `segment_metrics`.

## Comparison rules

- Values are compared only when both periods have the fact and units match.
- Unit mismatch, taxonomy change, or a missing period → `COMPARISON_UNAVAILABLE`.
- Relative change computed as `(b - a) / |a|`; materiality thresholds per key.
- Net income sign flip is always material.
- Unmapped tags are reported, never silently compared.
