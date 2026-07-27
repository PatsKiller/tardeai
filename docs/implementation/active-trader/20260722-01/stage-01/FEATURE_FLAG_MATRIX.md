# Feature Flag Matrix — Stage 1

**Run ID:** 20260722-01 · Registry: `scripts/active_trader/contracts.py` (`FLAG_REGISTRY`)
Storage: `active_trader_feature_flags` — append-only versioned rows (audit built-in:
version, reason, changed_by, changed_at, rollback_mode), scope_key + JSONB scope,
optional expiry (expired ⇒ OFF).

Modes: `OFF · READ_ONLY · SHADOW · SIMULATION · LIVE_CANARY`

| Flag | Prod default | Test default | Dev default |
|---|---|---|---|
| active_trader_next_visible | OFF | OFF | **READ_ONLY** |
| active_trader_next_read_only | OFF | OFF | OFF |
| active_trader_session_builder_enabled | OFF | OFF | OFF |
| active_trader_simulation_enabled | OFF | OFF | OFF |
| active_trader_live_canary_enabled | OFF | OFF | OFF |
| active_trader_multi_account_enabled | OFF | OFF | OFF |
| active_trader_runner_enabled | OFF | OFF | OFF |
| active_trader_overnight_conversion_enabled | OFF | OFF | OFF |
| broker_alpaca / broker_moomoo / broker_schwab | OFF | OFF | OFF |
| broker_failover | OFF | OFF | OFF |
| smart_entry / quick_add | OFF | OFF | OFF |
| cancel_one / cancel_all / flatten / smart_sell | OFF | OFF | OFF |
| resilience_resistance | OFF | OFF | OFF |
| journal_replay | OFF | OFF | OFF |
| drive_sync / operator_email | OFF | OFF | OFF |

## Authority limits (tested)
- A flag can **restrict** an action (`broker_<x>=OFF` blocks) but can **never grant**:
  `authorize_order` requires a valid session authorization for LIVE regardless of any
  flag state (`test_flags_alone_cannot_authorize_trading`).
- Flags cannot enlarge a session envelope (quantity/account checks read only the signed
  authorization), cannot override broker capability, cannot bypass risk or 2FA contracts,
  and change nothing in `/v3` (no production flag row exists; /v3 build proof green).
- Invalid names/modes fail closed; unknown deployment environment fails closed.
- No production flag row was created in Stage 1 (production DB untouched).
