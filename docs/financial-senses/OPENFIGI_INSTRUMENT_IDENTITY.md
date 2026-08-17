# OpenFIGI instrument identity

Canonical instrument identity via OpenFIGI, fail-closed on ambiguity.

## `InstrumentIdentity@v1` fields

`instrument_id`, `figi`, `composite_figi`, `share_class_figi`, `ticker`, `name`,
`security_type`, `market_sector`, `exchange`, `currency`, `cik`, `cusip`, `isin`,
`broker_symbols`, `underlying_id`, `identity_status`, `identity_confidence`,
`source_refs`, `as_of`.

## Statuses

`RESOLVED`, `AMBIGUOUS`, `NOT_FOUND`, `CONFLICT`, `NOT_CONFIGURED`.

## Policy

- Multiple matches → `AMBIGUOUS` unless exchange / security type / share class
  narrows to one.
- Existing canonical broker IDs are composed, not blindly replaced; a mismatch
  is `CONFLICT`.
- `normalize_ticker` handles `BRK.B` / `BRK-B` / `BRK/B`; GOOG vs GOOGL remain
  distinct.

See `INSTRUMENT_IDENTITY_CONTRACT.md`.
