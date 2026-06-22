# SnapTrade / Fidelity Protective Stops — Spec (build-now, operator-approve)

**Status:** BUILT 2026-06-22 — **NOT armed** until operator runs typed-phrase approval.  
**Owner:** operator (John).

## Capability verdict (live check)

| Question | Answer |
|----------|--------|
| Can SnapTrade place stops on **Fidelity**? | **No** — Fidelity connection is `type=read`, `allows_trading=False` on SnapTrade. |
| SnapTrade equity order types | `Market`, `Limit`, `Stop`, `StopLimit` — **no native TrailingStop** in SDK. |
| Production path for Fidelity holdings | **Monitored stops** — software watch, **no 2FA**; alert + Fidelity Active Trader ticket on breach (manual). |
| Broker API path (`snaptrade_trade.place`) | Scaffold only; `ENABLED=False`, `BROKER_API_ENABLED=False` until a trade-capable brokerage connects. |

## Architecture (mirrors Schwab Stage 2c)

```
Open Trades card (fidelity_rollover_ira)
  → POST /api/v2/holdings/protective-stop          [ONE STEP]
       ├─ snaptrade_protective_stop_policy.evaluate()
       ├─ fidelity_stops_enabled standing unlock
       └─ fidelity_monitored_stop.arm() — DB level only (NO 2FA — no broker execution)
  → unified_stop_supervisor (~3 min RTH)
       └─ ratchet trailing → on breach: Telegram/alert + Active Trader ticket (still no auto-execution)
```

**2FA:** Required on **Schwab** (real broker submit). **Not** used on Fidelity monitor-only — arming is advisory DB state; breach is alert + manual ticket only.

**Trailing:** ratchet-only in `fidelity_monitored_stop.py`.

## Components

| File | Role |
|------|------|
| `scripts/brokers/snaptrade_protective_stop_policy.py` | Commit-only envelope; `MONITORED_ENABLED=True`, `BROKER_API_ENABLED=False` |
| `scripts/brokers/snaptrade_protective_stop_pilot.py` | Legacy intent helpers (broker-API path only) |
| `scripts/fidelity_monitored_stop.py` | DB table + ratchet + breach → alert/ticket |
| `scripts/snaptrade_pilot_arm.py` | Operator approval (`--approve` / `--revoke` / `--capability`) |
| `scripts/brokers/snaptrade_transport.py` | Future broker-API place (blocked for Fidelity) |
| `scripts/brokers/snaptrade_trade.py` | Low-level SnapTrade SDK (still `ENABLED=False`) |

## Operator approval (required before UI live route)

```bash
# 1. Verify SnapTrade capability (expect fidelity_read_only: true)
python3 scripts/snaptrade_pilot_arm.py --capability

# 2. Standing unlock (typed phrase — date must match today)
python3 scripts/snaptrade_pilot_arm.py --approve --confirm "APPROVE FIDELITY STOPS $(date +%Y-%m-%d)"

# 3. Status
python3 scripts/snaptrade_pilot_arm.py --status

# Revoke anytime
python3 scripts/snaptrade_pilot_arm.py --revoke --confirm "REVOKE FIDELITY STOPS"
```

After `--approve`, Open Trades cards on `fidelity_rollover_ira` arm **monitored stops in one step** (no 2FA).

## Safety invariants

- **Schwab** place/modify: per-order 2FA (`approval_service`, `REQUIRED_CHANNELS=1`). **Fidelity monitor:** none.
- No broker HTTP to Fidelity until SnapTrade reports `allows_trading=True` **and** operator commits `BROKER_API_ENABLED=True`.
- `fidelity_401k` excluded (employer plan — no exchange stops).
- Cancel monitored stop: `POST /api/v2/holdings/protective-stop/cancel` with `account=fidelity_rollover_ira` (no 2FA).

## One-share live test (no sandbox)

SnapTrade has no paper/sandbox — the first proof order is capped at **exactly 1 share**, **≤$50 notional**.

```bash
# Arm one-share test mode (typed phrase, today's date)
python3 scripts/snaptrade_pilot_arm.py --arm-test --confirm "ARM SNAPTRADE ONE SHARE TEST $(date +%Y-%m-%d)"

# API flow (after ENABLED=True commit + trade-capable broker connected)
POST /api/v2/snaptrade/trade/preflight  { "symbol": "XAR", "account": "fidelity_rollover_ira", "one_share_test": true }
POST /api/v2/snaptrade/trade/execute    { "intent_id": "...", "channel": "web", "code": "XAR" }
```

Requires: `snaptrade_trade.ENABLED=True` (commit) + `broker_allows_trading=True` + per-order 2FA.
Fidelity read-only today — test path activates when a tradable brokerage is linked.

## Related docs

- [`snaptrade-read-only-aggregation-spec.md`](snaptrade-read-only-aggregation-spec.md)
- [`stop-management-architecture.md`](stop-management-architecture.md)
- [`stage2c-protective-stops-spec.md`](stage2c-protective-stops-spec.md) (Schwab reference)