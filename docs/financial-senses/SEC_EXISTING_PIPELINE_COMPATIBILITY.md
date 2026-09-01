# SEC existing pipeline compatibility

Status:      ACTIVE
as_of:       2026-08-16T22:32:42-04:00
Measured at: efcc51365 / not measured

The provider reuses the existing pipeline rather than replacing it. Verified
compatibility:

- `scripts/sec_data_ingest.py` imports with no side effects (`_get_cik`,
  `ingest_form4`, `get_sec_intel` present and unchanged).
- `scripts/sec_form4_source_maturity.py` and
  `scripts/run_sec_form4_momentum_context.py` import with no side effects.
- Existing SEC regression `tests/test_sec_form4_momentum_context.py` passes
  (17/17) unchanged.
- The provider does not write on read: it only `SELECT`s `sec_form4` /
  `sec_13f` and issues `data.sec.gov` GETs.
- No second scheduler: `run_sec_form4_momentum_context.py` remains the sole
  canonical scheduler.
- Same Form 4 row yields the same source identity (`sec_form4_table` /
  `sec_13f_table` source IDs, `PRIMARY_REGULATORY`).
- Same CIK resolution path (`company_tickers.json` + `sec_data_ingest._get_cik`
  fallback).
- Provider failure (DB down, 429, timeout, malformed XBRL) does not mutate the
  DB.
