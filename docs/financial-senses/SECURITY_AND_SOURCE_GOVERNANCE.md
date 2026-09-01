# Security and source governance

Status:      ACTIVE
as_of:       2026-08-16T22:32:42-04:00
Measured at: efcc51365 / not measured

## Source classes

`PRIMARY_REGULATORY`, `PRIMARY_GOVERNMENT`, `CANONICAL_INTERNAL`,
`APPROVED_MARKET_DATA`, `SECONDARY_RESEARCH`, `MEMORY_CONTEXT`,
`MODEL_INFERENCE`.

## Quality ordering by claim type

- Company filing fact: SEC primary > approved market data > secondary > memory
  > model.
- Current portfolio holding: canonical broker/book truth > SEC > memory.
- Macro vintage: ALFRED vintage > current revised macro summary.
- Instrument identity: canonical broker ID + OpenFIGI + CIK consistency > ticker.

## Hard rules

- `MODEL_INFERENCE` / `MEMORY_CONTEXT` can never back a `FACT`.
- Every result carries `source_type`, `as_of`, `quality`, `freshness`.
- No provider exposes arbitrary URL fetch, shell, filesystem write, SQL write,
  or broker/order/stop authority.
- All capabilities are `READ_ONLY` (asserted by
  `test_security_source_governance.py`).
