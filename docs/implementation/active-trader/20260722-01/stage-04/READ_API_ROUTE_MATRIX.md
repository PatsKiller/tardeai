# Read API Route Matrix — Stage 4

Prefix: `/api/v3/active-trader` · GET only (non-GET → 405) · machine contract:
`scripts/active_trader/read_api_contract.json` (typed route-contract manifest — the
repo has no OpenAPI generator and adding a package is prohibited).

| Route | Class | Filters | Source | Notes |
|---|---|---|---|---|
| /health | general | — | lab DB | env, DB connectivity + identity + read-only proof, schema version, deps, production_access=DISABLED; no paths/credentials |
| /version | general | — | lab DB | arch v3.3, program v1.1, contract stage4-v1.0, code SHA, migration versions |
| /session | general | — | lab DB | latest session projection; explicit NO_SESSION (not 404); authorization SHORT hash only (12 chars) |
| /candidates | general | state,symbol,broker,limit,cursor,sort(symbol\|state\|rvol) | SYNTHETIC fixture | microstructure UNAVAILABLE until Stage 5 warning; freshness computed |
| /symbol/{s} | heavy | — | fixture + lab DB | conservative validation (`^[A-Z][A-Z0-9.\-]{0,9}$`, traversal→400); no broker call; rejection history included |
| /accounts | general | — | stage-02 snapshot + lab DB | masked IDs enforced; discrepancies surfaced as CONFLICT warning |
| /brokers | general | — | stage-02 snapshot | moomoo NOT_INSTALLED; snaptrade/fidelity/tastytrade marked excluded |
| /brokers/capabilities | general | broker,account,capability,state,limit,cursor | lab DB | expired SUPPORTED → effective UNKNOWN + STALE warning |
| /rejections | heavy | broker,account,symbol,normalized_code,requires_operator,requires_broker_call,from,to,limit,cursor | lab DB | redacted rows only; REDACTED warning; 92-day range cap |
| /notifications | general | status,severity,from,to,limit,cursor | lab DB | read-only — cannot send/ack/resolve/escalate |
| /orders | general | account,broker,symbol,state,environment,from,to,limit,cursor | lab DB | `environment <> 'LIVE'` in SQL; no live refresh |
| /positions | general | limit,cursor | lab DB | marks/P&L explicitly UNAVAILABLE pre-market-data stages |
| /journal | heavy | session,symbol,event_type,from,to,limit,cursor | lab DB | replay REFERENCES only (`replay://…`), never inlined |
| /features | general | — | lab DB + Stage 1 defaults | production effective mode always OFF (asserted in-handler); immutable via API |
| /parity | heavy | — | lab DB | NOT_STARTED/BASELINE_ONLY; explicit "no UI parity" note pre-/v3-next |

Pagination: opaque urlsafe-base64 cursor, default 50, max 200, deterministic ORDER BY,
invalid cursor/limit/sort/date → 422. Rate limits: general 120/min, heavy 30/min per
identity (heavy = journal, rejections, parity, symbol). Response ceiling 1.5 MB;
≤20 warnings; ≤10 sources; ≤92-day date ranges.
