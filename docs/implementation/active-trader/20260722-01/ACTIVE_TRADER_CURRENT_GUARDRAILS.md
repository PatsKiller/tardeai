# Active Trader Stage 0 — Current Guardrails Inventory

**Run ID:** 20260722-01 · **Base SHA:** 87c2fa09 · **Date:** 2026-07-22
These rails are inventory only. Stage 0 changed none of them.

## 1. Central execution gate — `scripts/brokers/execution_guard.py`
- `authorize(intent, action)` (`:204`) / `require()` raises `ExecutionBlocked` (`:304-307`).
- Default mode per broker: `BROKER_DISABLED` (`:21`); fail-closed on any DB/error path.
- `_live_future_unlocked()` (`:46-75`) requires ALL of: (env `BROKER_LIVE_ENABLED=true` OR unexpired `system_controls.pilot_armed_until` OR `system_controls.schwab_pilot_standing_unlock=true`) AND `system_controls.broker_live_enabled=true` AND ≥1 unrevoked row in `broker_live_approvals`.
- `_protective_unlocked()` (`:78-99`): Stage-2c protective SELL stops — committed `protective_stop_policy.ENABLED` AND `system_controls.protective_stops_enabled=true`.
- BUY orders route through `canary_gate.evaluate` (`:209-232`); fail-closed if gate unavailable.
- Strategy markers select envelopes: `PROTECTIVE_STOP_2C`, `FIDELITY_PROTECTIVE_MARKER`, `OPTIONS_EXECUTION_MARKER`, `QUEUE_ENTRY_MARKER` (`:101-104`).

## 2. Per-order 2FA — `scripts/brokers/approval_service.py`
- The "FOURTH lock" (env flag + DB control + standing signed approval + per-trade 2FA) (`:1-9`).
- Channels: web (typed-ticker proof via `POST /api/v2/broker-orders/approve`) and Telegram (one-time 6-digit code); some flows also cite email codes (`protective_stop_pilot.py:9,144`).
- `TRADE_APPROVAL_REQUIRED_CHANNELS` default **1** (either channel suffices) (`:26`); TTL `TRADE_APPROVAL_TTL_MIN` default 10 min (`:24`); single-use, intent-bound, fail-closed on missing/expired/reused/partial.
- ONE ORDER AT A TIME: `request_approval()` refuses while another intent holds an active approval (`:87-102`).
- State: DB `broker_order_intents` (PREFLIGHTED→SUBMITTED/FILLED/CANCELLED/REJECTED) + `trade_approvals`.
- **There is NO session-scoped 2FA anywhere** — the v3.3 `MOMENTUM_SCALP_LIVE_SESSION` envelope does not exist yet (to be built additively; per-order 2FA untouched).

## 3. Pilot fences
- `brokers/canary_gate.py`: committed BUY envelope — symbol allowlist `("GRAB","XRX")`, price ≤ $4, qty ≤ 10, notional ≤ $40, EQUITY, LONG. **`GATES_REMOVED=True` (`:41`) currently makes `evaluate()` a pass-through** — matches memoryed "GATES_REMOVED; per-order 2FA only remaining gate" state; recorded as the live posture (per-order 2FA remains the operative gate).
- `brokers/pilot_caps.py`: `PILOT_ACCOUNT_ALLOWLIST` (3 Schwab accounts); `MAX_PILOT_ORDERS_TOTAL=9999` in code vs "operator cap 5" in docstring — MISMATCH, authority UNVERIFIED (operator TODO).
- `brokers/protective_stop_pilot.py`: every submit passes taxable-only assert → api_write_enabled → guard → per-order 2FA.

## 4. Kill switches
- `brokers/kill_switches.py`: DB `kill_switch_state`/`kill_switch_audit`; scopes global/broker/account/strategy/symbol/asset_class/options_only/equities_only; DB unavailable ⇒ global switch treated ACTIVE (fail-closed). CLI enable/disable with confirm phrase.
- `scripts/hermes_killswitch.py`: file `data/runtime/HERMES_DISABLED`.
- Schwab stream: file `data/state/STREAM_DISABLED`.

## 5. Write fences & validators
- Schwab: `validate_schwab_no_writes` (12/12 fence), `validate_schwab_write_policy.py --source-only` (CI), `broker_write_scanner.py`, `tests/test_no_broker_write_bypass.py` (CI).
- SnapTrade: `snaptrade_trade.ENABLED=False` master gate; Fidelity `allows_trading=False` live check.
- CI gate: `.github/workflows/release-readiness.yml` — read-only release proof, never performs broker writes.

## 6. Notification rails (existing)
- Telegram primary: `scripts/telegram_alert.py` (router-policy-gated, `ENABLE_TELEGRAM=true`), callback poller `run_telegram_callback_poller.py` + watchdogs; unified dispatcher `alert_dispatcher_unified.py`; policy `config/operator_alert_policy.yaml`.
- Email: via `gog gmail send` subprocess (`scripts/email_notifier.py`; operator `john@jwwhiting.com`; keyring `~/.openclaw/credentials/gog_keyring_password`); SMTP scaffold only, `ENABLE_EMAIL=false`.
- Audit: `scripts/audit_ledger.py` — append-only hash-chained JSONL + optional `audit_ledger_events` table.

## 7. Live flag values (verified 2026-07-22, live .env — names + non-secret values)
```text
BROKER_LIVE_ENABLED=true      (one of three arming inputs; still requires DB controls + approvals + 2FA)
ALPACA_MODE=paper
ENABLE_ALPACA_PAPER=true
DEFAULT_PAPER_ACCOUNT=alpaca_paper
ENABLE_TELEGRAM=true · ENABLE_EMAIL=false · ENABLE_SLACK=false · ENABLE_WHATSAPP=false
```

## 8. Stage 0 assertion
No guardrail above was modified, weakened, or exercised. No approval was requested. No 2FA was triggered. No broker write occurred.
