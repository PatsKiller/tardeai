# Moomoo Data-Only Smoke — SUCCESS (2026-07-23, post-agreement)

The operator completed the moomoo OpenAPI regulatory questionnaire + agreement. OpenD login now
clears the disclaimer ("Disclaimer agreed, skip acc judge and questionnaire"), no SMS (device
trusted), no password re-entry. Authorized data-only smoke (§21) PASSED:

- data_login: OK (get_global_state RET_OK)
- market_snapshot US.AAPL: last 325.89, prev_close 327.74 (real data)
- deterministic feature from snapshot: mid 323.85, spread 9.26 bps
- subscribe QUOTE / K_1M / ORDER_BOOK / TICKER: ALL OK (single P0 symbol, no push)
- WAL -> zstd Parquet replay round-trip: row_count 1, verified True
- unsubscribe: done · OpenD stopped · config shredded · 0 processes/listeners after

Notes:
- subscription-quota fields returned null (market closed / basic entitlement) — recorded, not an error.
- No trade context, no order, no account query, no unlock; auto_hold_quote_right=0 (no quote-right grab).
- console=0 runtime posture; no telnet in runtime (telnet was one-time device-auth only).

Gate movement: Stage 5 credential/agreement gate CLEARED. Live-data smoke PASSES. STILL PENDING:
>=30-minute continuous capture during an OPEN US RTH session + the resumable five-RTH-session
observation (hard gate for Stage 9 acceptance / Stage 10 promotion). US market was CLOSED at smoke
time, so those await open sessions. BF-1 (broker-resident disconnect-surviving protection) remains
UNPROVEN → live Moomoo scalping still BLOCKED.
