# ATM Executor ← automation_mode Wiring (2026-06-05)

The auto-approver/executor (`scripts/atm_auto_approver.py`) now reads the per-account
`account_automation_policies.automation_mode` (broker/account model) and gates auto-approval on it.

## Behaviour (ADDITIVE safety layer — can only restrict, never bypass existing gates)
Per proposal, after the account is resolved (`target_account`), before all existing ATM gates:
- `DISABLED | MANUAL_REVIEW | PAUSED_ENTRIES | EMERGENCY_STOP` → **HELD**: no auto-approve, proposal
  left PENDING (manual review). No rejection (does not kill the proposal).
- `AUTO_PAPER`, or `AUTO_LIVE` on a **paper** account → **PROCEED** through the normal gates and submit.
  Submission endpoint is unchanged — governed by the account adapter + `ALPACA_MODE` (paper account →
  Alpaca paper endpoint, no real money).
- `AUTO_LIVE` on a **live** account → **HELD** unless `live_trading_interlock.assert_writable` passes
  (it does not today: `live_trading_allowed=False`, Schwab/Fidelity no trading API). Fail-closed.
- No policy row → no override (prior behaviour preserved).

Helper: `_account_automation_mode(conn, account)` (normalizes `_ira`; read-only; tolerant of missing
table → None).

## Safety invariants (unchanged)
- Does NOT change the submission endpoint or `ALPACA_MODE` (paper). Does NOT bypass the live-trading
  interlock, the 11 paper safety gates, kill-switch, fill verification, or atm_state.mode.
- AUTO_LIVE on the paper account = auto-submit to the **paper** endpoint (no real money). Real live
  trading still requires a live account + api_write + the live gate (all currently closed).
- Read path only adds a gate; it never creates/submits an order by itself.

## Current effect
`alpaca_paper` = AUTO_LIVE + paper → executor PROCEEDs (auto-submits to paper, as before, now
controllable via automation_mode — e.g. set MANUAL_REVIEW to halt auto-approval). All live accounts
remain held by the interlock.

## Verified
Helper reads alpaca_paper=AUTO_LIVE, schwab=MANUAL_REVIEW, unknown=None. Decision matrix correct.
Executor one-cycle run clean (0 pending, mode=active, exit 0); 0 orders submitted. No endpoint/
interlock/strategy/GO-WAIT change. Phase 205 untouched.
