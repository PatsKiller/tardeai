# RUNTIME_HARNESS_SUMMARY

- status: PASS
- mode: hermetic
- build_sha: cd049cb4eb20add7a24de28b5a5e42eafcc4d673
- spa: 48/48
- core_apis: 19/19
- negatives: 7/7
- boundaries: 8/8
- get_mutation_detected: False
- freshness: {"stale": true, "reason": "data 45h \u00b7 alpaca_ACCOUNT_REDACTED", "asOf": "2026-09-01", "ageHours": 45.0, "surfaceLabel": "STALE \u00b7 data 45h \u00b7 alpaca_ACCOUNT_REDACTED", "dataAsOf": "2026-09-01", "dataAsOfAccount": "alpaca_ACCOUNT_REDACTED"}

## Failures
- none

## Defect guard
Current price/value paired with old child `data_as_of` must render STALE and must never
borrow loader `as_of` / `last_repriced` as a fresh chrome date.
