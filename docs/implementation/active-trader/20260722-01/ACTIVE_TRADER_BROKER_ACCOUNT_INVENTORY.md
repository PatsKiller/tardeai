# Active Trader Stage 0 — Broker and Account Inventory

**Run ID:** 20260722-01 · **Base SHA:** 87c2fa09 · **Date:** 2026-07-22
Evidence-backed from repository at base SHA + live-host read-only checks. Secret VALUES were never read; only key names appear.

## 1. Adapter architecture

Two parallel contract stacks:
- `scripts/broker_adapter.py:20-67` — `FillConfirmation` + `BrokerAdapter` Protocol; `adapter_for(account_label)` dynamically imports `broker_confirm_<broker>.py` (zero vendor literals by design).
- `scripts/brokers/interfaces.py:7-44` — ADR-B1 Protocols (`BrokerAuthProvider`, `BrokerAccountService`, `BrokerMarketDataAdapter`, `BrokerOrderTranslator`, `BrokerOrderAdapter`) + normalized error taxonomy (`BrokerError`, `BrokerRateLimited`, `BrokerRejected`, `BrokerUnavailable`).

## 2. Brokers

### Alpaca — primary/paper, the only live-executing broker
- Files: `scripts/alpaca_paper_adapter.py`, `scripts/broker_confirm_alpaca.py`, `scripts/brokers/alpaca_{credentials,factory,read_client}.py`, `scripts/alpaca_paper_options_executor.py`.
- Ops: account/positions/open-orders reads; `submit_entry` (`alpaca_paper_adapter.py:386`), `submit_approved_paper_trade` (`:865`); confirmation by polling `/v2/orders/{id}`. Generic `submit_order` explicitly NOT wired (`:70-72`).
- Auth env slots (names only): `ALPACA_PAPER_API_KEY/SECRET_KEY` → paper; `ALPACA_TAXABLE_*` and `ALPACA_IRA_*` → live **read-only scaffolds, execution not built** (`alpaca_credentials.py:8-9`); legacy `ALPACA_API_KEY/SECRET_KEY` fallback for PAPER only. Host derived from slot name, never a URL. No alpaca SDK pin — raw HTTP (UNVERIFIED mechanism detail).

### Schwab — read transport live; ALL writes fenced
- Files: `scripts/schwab_adapter.py`, `scripts/schwab_transport.py`, `scripts/brokers/schwab_order_adapter.py` (dormant stub), `scripts/schwab_token_manager.py`, `scripts/schwab_auto_reauth.py`, ~20 support modules.
- Ops: account/positions/open-orders reads (`schwab_adapter.py:140-258`). Writes fail-closed: `_api_post` raises NOT_PROVEN (`:99`); `SchwabOrderAdapter.submit/replace/cancel` raise `ExecutionBlocked` unconditionally (`schwab_order_adapter.py:18-20`). Exception lane: protective SELL stops (Stage 2c) through the full live stack incl. per-order 2FA.
- Auth: OAuth2 refresh flow; key names `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_REFRESH_TOKEN`, per-account `SCHWAB_ACCT_<LABEL>`; refuses to guess when >1 account linked (`:129-135`). `schwab-py==1.5.1` (read-only boundary). Auto-reauth loads only from Bitwarden SM tmpfs render (`schwab_auto_reauth.py:13,377`).
- Environment: live-only; no Schwab paper exists. Capability default `LIVE_ENABLED_FUTURE`, fail-closed.

### SnapTrade — read live (Fidelity); write path built but master-gated OFF
- Files: `scripts/brokers/snaptrade_{read,trade,credentials,connect,transport,trade_pilot,protective_stop_pilot,protective_stop_policy}.py`, `scripts/snaptrade_pilot_arm.py`.
- Ops: list_accounts/holdings/balances/activities reads; two-step preview→place with `ENABLED=False` master gate (`snaptrade_trade.py:24`), cancel (`:199`). Fidelity connections are read-only (`allows_trading=False` checked live). Trade allowlist: `fidelity_rollover_ira` only.
- Auth names: `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_USER_ID`, `SNAPTRADE_USER_SECRET`. SDK `snaptrade-python-sdk>=11`.
- NOTE: `config/snaptrade_accounts.json` referenced by `snaptrade_trade.py:26` was NOT found on disk — UNVERIFIED whether runtime-generated or missing.

### Tastytrade — complete scaffold, untested, unregistered
- `scripts/tastytrade_adapter.py` implements submit/stop/cancel but header: "SCAFFOLDING — not yet tested with live credentials" (`:13`). Not in capability registry; no SDK dep; runtime wiring UNVERIFIED. **Not in the v3.3 canonical broker plane — operator scope decision needed** (litmus question Q5).

### Fidelity — monitored only, no write API
- Capability registry entry only (`capabilities.py:78-87`): stops/trailing = "monitored + 2FA + Active Trader ticket". Support: `scripts/lib/fidelity_stop_sync.py`, fund-map configs. Holdings via SnapTrade read sync.

### Moomoo / OpenD — DOES NOT EXIST in code
Verified precisely: NO SDK in requirements (zero futu/moomoo matches), NO adapter code, NO config, NO systemd unit, NO OpenD binary on the live host (`moomoo-opend.service` not found; no OpenD install dirs). References are documentation-only (architecture v3.0–v3.3, Codex prompts). **MOOMOO/OPEND STATE: NOT_INSTALLED / DOCUMENTATION_ONLY.**

## 3. Account registry
- Source of truth: `accounts` DB table + ATM config YAML (`broker_config.py:4`; `get_all_accounts()` at `:74`). Live-DB row contents not enumerated in this audit (UNVERIFIED).
- `assets/portfolio_accounts.yaml` (v1.2): 8 accounts with broker/type/account_id (masked)/taxable/read_only/active/execution_built flags. Active automated account: `tradeai_automated` (Alpaca Paper, active, not read-only). Env: `DEFAULT_PAPER_ACCOUNT=alpaca_paper` (live .env) — note `.env.example` documents `tradeai_automated`; discrepancy recorded (UNVERIFIED which label the accounts table resolves).
- Per-account capabilities: `config/account_capabilities.json` (short/options/inverse flags with operator-verification dates).
- Hardcoded-value policy enforced (`broker_config.py:22`, `broker_adapter.py:8`, `# hardcode-ok` annotations).

## 4. Capability & rejection handling (existing)
- `scripts/brokers/capabilities.py` — CAPS registry (alpaca/schwab/fidelity/snaptrade), grades `native|composed|degraded|blocked`, confidence `VERIFIED-LIVE|VERIFIED-SDK|UNVERIFIED`, fail-closed accessors.
- `scripts/brokers/capability_gate.py`, `pilot_caps.py` (lighter registries).
- DB: `broker_capability_checks` table exists (`migrate_broker_account_model.py:85`).
- Rejections: normalized status taxonomy in `brokers/order_lifecycle.py:55-126` FSM; `reconcile_orders.py:65-139` produces `rejected_orders` with "do not retry blindly" action. NO dedicated `broker_rejection_events` table yet; NO §16F.6 normalized rejection classifier yet.

## 5. BROKER ACCOUNTS DISCOVERED (Stage 0 evidence)
| Broker | Accounts (from repo config) | API-enabled | Tradeable via Trade AI today |
|---|---|---|---|
| Alpaca | paper (`tradeai_automated`), taxable (scaffold), IRA (scaffold) | paper: yes; live: keys named, execution not built | paper only (auto) |
| Schwab | per-account `SCHWAB_ACCT_<LABEL>` env convention; 3 accounts in `PILOT_ACCOUNT_ALLOWLIST` (`pilot_caps.py`) | yes (read + fenced pilot writes) | protective stops + pilot lane w/ 2FA only |
| Fidelity (SnapTrade) | rollover IRA + read-only connections | read-only | no (read-only; SnapTrade trade gate OFF) |
| Moomoo | none | none | no (not installed) |
| Tastytrade | scaffold adapter, sandbox default | UNVERIFIED | no (unregistered) |

Exact per-broker account IDs/counts from the live `accounts` DB table and broker APIs: **UNVERIFIED in Stage 0** (would require live broker API calls; deferred to Stage 2 capability probes per program).
