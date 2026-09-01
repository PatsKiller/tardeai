# OpenFIGI instrument identity

Status:      ACTIVE
as_of:       2026-08-17T11:10:54-04:00
Measured at: efcc51365 / not measured

Canonical instrument identity via OpenFIGI, fail-closed on ambiguity.

## `InstrumentIdentity@v1` fields

`instrument_id`, `figi`, `composite_figi`, `share_class_figi`, `ticker`, `name`,
`security_type`, `market_sector`, `exchange`, `currency`, `cik`, `cusip`, `isin`,
`broker_symbols`, `underlying_id`, `identity_status`, `identity_confidence`,
`source_refs`, `as_of`.

## Statuses

`RESOLVED`, `UNVERIFIED_IDENTIFIER`, `AMBIGUOUS`, `NOT_FOUND`, `CONFLICT`,
`NOT_CONFIGURED`.

## Policy

- Multiple matches → `AMBIGUOUS` unless exchange / security type / share class
  narrows to one.
- Existing canonical broker IDs are composed, not blindly replaced; a mismatch
  is `CONFLICT`.
- `normalize_ticker` handles `BRK.B` / `BRK-B` / `BRK/B`; GOOG vs GOOGL remain
  distinct.
- Fail-closed on uncertainty: any asserted identifier job that returns a
  warning or error — even with candidates — cannot yield a clean `RESOLVED`;
  it downgrades to `UNVERIFIED_IDENTIFIER`. A no-result job prevents
  `RESOLVED`, and every asserted identifier is surfaced as a note/diagnostic,
  never silently dropped. Only when all asserted identifiers are clean and
  agree on exactly one FIGI does the result become `RESOLVED`.

See `INSTRUMENT_IDENTITY_CONTRACT.md`.
