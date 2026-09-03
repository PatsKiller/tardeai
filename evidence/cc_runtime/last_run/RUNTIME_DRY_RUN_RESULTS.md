# RUNTIME_DRY_RUN_RESULTS

## Negative controls
- inconsistent_position_count: PASS
- split_root_stale_date: PASS
- literal_fresh_stale_file: PASS
- missing_envelope_fields: PASS
- wrong_build_sha: PASS
- unaccounted_route: PASS
- attempted_live_write: PASS

## Timezone / boundary cases
- midnight_et_date_only: PASS (stale=True)
- within_36h: PASS (stale=False)
- exactly_market_session_prior: PASS (stale=False)
- dst_spring_forward_date: PASS (stale=True)
- future_skew_rejected: PASS (stale=True)
- clock_regression_old: PASS (stale=True)
- missing_data: PASS (stale=True)
- malformed_data: PASS (stale=True)

## Transport / failure injection
```json
{
  "code_304": 304,
  "partial_quality": "ok",
  "malformed_quality": "malformed_json",
  "network_quality": "network_failure",
  "mutation_detected": false,
  "write_probe": {
    "attempted_method": "POST",
    "path": "/api/v2/overview",
    "safety_allowed": false,
    "safety_reason": "mutating_method_POST_refused_against_live_or_preview",
    "host_class": "live_refused",
    "http_status": null,
    "detected": true,
    "detection": "preflight_refused"
  },
  "freshness": {
    "stale": true,
    "reason": "data 45h \u00b7 alpaca_ACCOUNT_REDACTED",
    "asOf": "2026-09-01",
    "ageHours": 45.0,
    "surfaceLabel": "STALE \u00b7 data 45h \u00b7 alpaca_ACCOUNT_REDACTED",
    "dataAsOf": "2026-09-01",
    "dataAsOfAccount": "alpaca_ACCOUNT_REDACTED"
  },
  "honesty": {
    "pipeline_status": "ok",
    "pipeline_completed": "2026-09-02T20:00:00Z",
    "chrome_stale": true,
    "chrome_label": "STALE \u00b7 data 45h \u00b7 alpaca_ACCOUNT_REDACTED",
    "chrome_asOf": "2026-09-01",
    "literal_fresh_with_stale_data": false,
    "misleading_current_date": false,
    "pass_defect_guard": true
  }
}
```
