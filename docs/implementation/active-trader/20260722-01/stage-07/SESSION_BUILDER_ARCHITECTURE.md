# Session Builder Architecture — Stage 7
- `scripts/active_trader/session_builder.py`: pure domain (SessionDraftV2, AccountSelection,
  compute_sizing, validate_quick_add, validate_feature_change). Editing→new version; clone→v1;
  prior versions immutable (Stage 1 append-only table + append-only trigger).
- `scripts/active_trader/dev_write_api.py`: DevWriteApp factory. DEV_PREFIX
  `/api/v3/active-trader/dev`; routes: POST session/draft, GET session/<id>, POST session/clone,
  POST features. Guards: SHADOW/SIMULATION only (LIVE unrepresentable), trade_ai_test only
  (production DSN refused, no fallback), test identity required, audit_reason required on mutations,
  optimistic versioning (409 on stale expected_prev_version), audit journal event per write.
  Writes via the lab WRITE identity; the read API uses its separate read-only identity.
- No broker call, no 2FA, no production mount; default-disabled standalone (env gate); Stage 7 is
  app-factory + test-harness only (no standalone listener wired).
