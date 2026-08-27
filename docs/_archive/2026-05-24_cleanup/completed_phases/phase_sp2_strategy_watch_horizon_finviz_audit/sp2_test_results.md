# SP-2 Test Results

**Date:** 2026-05-18

## SP-2 Tests: 16/16 PASS

```
test_01_compiles ... ok
test_02_recovery_watch_multi_day ... ok
test_03_momentum_scalp_intraday ... ok
test_04_dividend_long_horizon ... ok
test_05_classify_new_candidate ... ok
test_06_classify_expired ... ok
test_07_recommend_action_human_review ... ok
test_08_watch_horizon_report_compiles ... ok
test_09_finviz_screener_quality_compiles ... ok
test_10_strategy_assignment_audit_compiles ... ok
test_11_no_db_writes ... ok
test_12_no_strategy_activation ... ok
test_13_no_yaml_mutation ... ok
test_14_no_trade_creation ... ok
test_15_no_secrets_printed ... ok
test_16_existing_sp1_tests_pass ... ok
```

## Regression: SP-1 13/13 PASS

## Report Outputs

- Watch horizon: 1,139 candidates across 12 strategies
- Screener quality: 18 screeners, all insufficient_data (naming mismatch between tables)
- Assignment engine: 74/83 proposals missing route audit, quality: missing_route_audit
