# ATM Controls → Broker/Account Automation — Due Diligence (Phase 1)

Status:      ACTIVE
as_of:       2026-06-05T13:39:17-04:00
Measured at: efcc51365 / not measured

## Current components
- Frontend: `apps/command-center-v3/src/components/ATMControlPanel.tsx` (217 lines) — hard-codes
  `alpaca_paper` (×2), `atm_config`, and a "Schwab Live Readiness" box. Mounted in TradingHub "ATM Controls" tab.
- Backend: ~33 `/api/v2/atm/*` endpoints exist (status, mode, accounts, config, gate-status,
  schwab-readiness, actionable-proposals, …) + guarded `/api/v2/admin/{atm/set-state, risk-config,
  proposal/approve|adjust-approve|edit-criteria}`.

## Current data sources
- **`accounts` table already IS a broker-account abstraction**: account_label, broker, mode (paper/live),
  auto_execution_capable, equity_source, routing_adapter, enabled, api_enabled. Rows: alpaca_paper
  (paper, auto+api+write, adapter=scripts.alpaca_paper_adapter), schwab_rollover_ira/roth_ira/taxable
  (live, api_enabled, NOT auto), fidelity_401k (live, no api/auto).
- Risk config: global `config/atm_config.yaml` (max_pct_per_trade 0.05, max_pct_per_strategy 20,
  max_pct_per_sector 30, max_concurrent 10, max_new_per_day 25, daily_loss_pct_hard_pause 2.5).
- ATM state: DB `atm_state` (id=1, global) — currently `active` (paper auto-approver).

## Current broker abstraction (already present)
- `scripts/broker_adapter.py` → `class BrokerAdapter(Protocol)`: submit_order, get_order_status,
  confirm_fill, get_positions, get_open_orders, get_account, get_status + `adapter_for(account_label)`.
- `scripts/alpaca_paper_adapter.py` (impl), `scripts/schwab_adapter.py` (has submit_entry but
  unproven), `broker_confirm_schwab.py` **missing** (Schwab fills can't be confirmed → write not proven).
- `scripts/live_trading_interlock.py` — fail-closed gate (live accounts refused until gate passes).

## Current hard-coded assumptions (to fix)
- ATMControlPanel hard-codes `alpaca_paper`, the global `atm_config`, and a Schwab-only readiness box.
- Durable `DRY_RUN` exists as an ATM state in `atm_state` (should become a per-order action).
- Risk config shown as universal, not per-account.

## Gaps (the real Phase-1 work)
- No `broker_accounts`, `account_automation_policies` (+ audit), `proposal_account_routes`,
  `broker_capability_checks` tables → **created additively this phase**.
- No per-account automation policy / capability flags / account-aware UI.

## Proposed minimal-safe refactor (Phase 1)
1. **Additive** DB tables (no destructive change); seed broker_accounts from `accounts`,
   automation policies (alpaca_paper from atm_config = `legacy_import`; live accounts DISABLED/
   MANUAL_REVIEW, write=false), capability checks.
2. Read endpoints (`/api/v2/broker-accounts`, `/{id}/automation-policy`, `/{id}/readiness`) + guarded
   PATCH policy. Extend `BrokerAdapter` additively (get_quote/validate_order/dry_run_order/cancel/
   replace/reconcile); SchwabAdapter write methods return NOT_PROVEN.
3. Account-aware UI (selector → policy panel → readiness → proposal grid/modal) — staged continuation.
- Keep `accounts` + `atm_config.yaml` as legacy until compatibility proven; UI shows policy source+timestamp.
- NO live writes, NO Schwab arm, NO strategy/GO-WAIT change, NO disabling of open-position protection.
