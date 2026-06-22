# SnapTrade / Fidelity Protective Stops — Spec (build-now, operator-approve)

**Status:** BUILT 2026-06-22 — **NOT armed** until operator runs typed-phrase approval.  
**Owner:** operator (John).

## Capability verdict (live check)

| Question | Answer |
|----------|--------|
| Can SnapTrade place stops on **Fidelity**? | **No** — Fidelity connection is `type=read`, `allows_trading=False` on SnapTrade. |
| SnapTrade equity order types | `Market`, `Limit`, `Stop`, `StopLimit` — **no native TrailingStop** in SDK. |
| Production path for Fidelity holdings | **Monitored stops** — software watch + same 2FA as Schwab + Fidelity Active Trader ticket on breach. |
| Broker API path (`snaptrade_trade.place`) | Scaffold only; `ENABLED=False`, `BROKER_API_ENABLED=False` until a trade-capable brokerage connects. |

## Architecture (mirrors Schwab Stage 2c)

```
Open Trades card (fidelity_rollover_ira)
  → POST /api/v2/holdings/protective-stop          [REQUEST]
       ├─ snaptrade_protective_stop_policy.evaluate()
       ├─ execution_guard (FIDELITY_MONITORED_STOP marker + fidelity_stops_enabled DB flag)
       └─ request_2fa() — web typed-ticker OR telegram/email code
  → POST /api/v2/holdings/protective-stop/confirm   [CONFIRM]
       └─ fidelity_monitored_stop.arm() — DB-monitored level (no broker HTTP)
  → unified_stop_supervisor (~3 min RTH)
       └─ ratchet trailing (high-water × trail%) → on breach request 2FA + ticket
```

**Trailing:** ratchet-only in `fidelity_monitored_stop.py` (same discipline as paper Alpaca degraded trailing).

## Components

| File | Role |
|------|------|
| `scripts/brokers/snaptrade_protective_stop_policy.py` | Commit-only envelope; `MONITORED_ENABLED=True`, `BROKER_API_ENABLED=False` |
| `scripts/brokers/snaptrade_protective_stop_pilot.py` | Intent + 2FA + route_after_2fa |
| `scripts/fidelity_monitored_stop.py` | DB table + ratchet + breach → 2FA |
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

After `--approve`, Open Trades cards on `fidelity_rollover_ira` use the **monitored + 2FA** route instead of ticket-only.

## Safety invariants

- Per-order 2FA unchanged (`approval_service`, `REQUIRED_CHANNELS=1`).
- No broker HTTP to Fidelity until SnapTrade reports `allows_trading=True` **and** operator commits `BROKER_API_ENABLED=True`.
- `fidelity_401k` excluded (employer plan — no exchange stops).
- Cancel monitored stop: `POST /api/v2/holdings/protective-stop/cancel` with `account=fidelity_rollover_ira` (no 2FA).

## Related docs

- [`snaptrade-read-only-aggregation-spec.md`](snaptrade-read-only-aggregation-spec.md)
- [`stop-management-architecture.md`](stop-management-architecture.md)
- [`stage2c-protective-stops-spec.md`](stage2c-protective-stops-spec.md) (Schwab reference)