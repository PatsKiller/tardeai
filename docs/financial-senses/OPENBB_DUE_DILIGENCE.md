# OpenBB due diligence

`OPENBB_DECISION = DEFER`.

## Criteria evaluated

| Criterion | Finding |
|---|---|
| Reduces provider-specific plumbing | UNCLEAR |
| Exposes source identity clearly | PARTIAL |
| Stays behind Trade AI governance | POSSIBLE |
| Duplicates current Data Broker | YES |
| Requires paid provider keys | PARTIAL |
| Dependency footprint | LARGE |
| License | community/enterprise split (needs legal review) |

## Decision

OpenBB is not installed and not adopted. Forbidden: `agent → uncontrolled OpenBB
toolbox`. If adopted later, it must be an optional adapter
`TradeAI FinancialSenseProvider → OpenBBProviderAdapter → provider` behind
governance.
