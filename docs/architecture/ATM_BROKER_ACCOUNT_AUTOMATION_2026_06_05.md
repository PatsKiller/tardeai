# ATM → Broker/Account Automation Console (Phase 1) — 2026-06-05

Status:      HISTORICAL
as_of:       2026-06-05T15:47:01-04:00
Measured at: efcc51365 / not measured

Refactors the hard-coded `alpaca_paper` ATM page into an account-aware Automation Control Center.
Phase 1 = data model + backend + UI; NO live writes, NO Schwab arm, NO strategy/GO-WAIT change.

## Data model (additive — `scripts/migrate_broker_account_model.py`)
- `broker_accounts` (account_key, display_name, broker, environment[paper|sandbox|live|import|read-only],
  api_read_enabled, api_write_enabled, supports_*, broker_adapter, connection_status, …)
- `account_automation_policies` (automation_mode, approval_policy, risk fields, flags, source[database|
  default_seed|legacy_import]) — UNIQUE per account
- `account_automation_policy_audit` (immutable old→new)
- `proposal_account_routes` · `broker_capability_checks`
- Seeded from `accounts` + `atm_config.yaml`: alpaca_paper=paper/read+write/AUTO_PAPER (legacy_import);
  schwab×3=live but **NO trading API yet** (api_read/write=false, MANUAL_REVIEW); fidelity=import/no-API/DISABLED. **Only alpaca_paper has a real trading API** — `?api_only=true` returns alpaca only. `accounts` +
  `atm_config.yaml` retained (legacy); UI shows policy source+timestamp.

## API (read + guarded write; `/api/v2` namespace serving canonical v3)
- GET `/api/v2/broker-accounts` (`?api_only=true` → API-capable only — the ATM default)
- GET `/api/v2/broker-accounts/enums` (environments incl live/paper/sandbox; modes; approval policies)
- GET `/api/v2/broker-accounts/automation-policy?account=` · `/readiness?account=`
- POST `/api/v2/admin/broker-account/api` (add/edit broker API — the Manage-APIs modal)
- POST `/api/v2/admin/broker-account/policy` (automation mode + risk PATCH)
  All writes via `admin_write` guard. **Gate-interlock:** AUTO_LIVE, or AUTO_PAPER/api_write on a LIVE
  account → 403 until the live-trading gate passes (`live_trading_interlock.assert_writable`).

## Frontend (`apps/command-center-v3/src/components/ATMControlPanel.tsx`)
Automation Control Center: safety badges + "Manage APIs"; account selector (API-capable only, fidelity
hidden); per-account automation **edit modal** (mode + approval + risk; AUTO_LIVE locked/gate-interlocked); per-account risk editor (source shown); broker-readiness checklist; ManageApiModal
(account_key/display_name/broker/environment[paper|sandbox|live]/read+write/capabilities). All writes →
AdminConfirmModal (preview→confirm→audit). No hard-coded account/broker; no v2 UI.

## Ownership map
- UI: ATMControlPanel.tsx (TradingHub "ATM Controls" tab) · API: api_v2.py (_broker_account_*) ·
  DB: broker_accounts + account_automation_policies(+audit) + proposal_account_routes + broker_capability_checks ·
  adapter: broker_adapter.py (BrokerAdapter Protocol) + alpaca_paper_adapter.py + schwab_adapter.py (write NOT_PROVEN).

## Verified (8/8 backend + UI screenshot)
api_only hides fidelity; enums expose live/paper/sandbox; policy/readiness GET; add-API sandbox→needs_confirm;
enable-write-on-live→403 interlock; invalid env→400; AUTO_LIVE→403. UI renders 4 API accounts + modal.
No mutations (preview/403/no-token). No live trading, no Schwab arm, no strategy/GO-WAIT change.

## Remaining (Phase-1 continuation)
Proposal grid + edit-modal (account-routing) redesign; test-connection/dry-run-order endpoints;
BrokerAdapter additive methods (get_quote/validate_order/dry_run/cancel/replace/reconcile); SchwabAdapter
write stubs return NOT_PROVEN; legacy atm_config.yaml decommission once policy is execution-source-of-truth;
full unit/api/frontend test suite.


## 2026-06-05 executor wiring
The auto-approver now CONSUMES `automation_mode` (additive gate): DISABLED/MANUAL_REVIEW/PAUSED/EMERGENCY → held; AUTO_PAPER/AUTO_LIVE-on-paper → submit (paper endpoint); AUTO_LIVE-on-live → live-interlock-gated. See `ATM_EXECUTOR_AUTOMATION_MODE_WIRING_2026_06_05.md`.
