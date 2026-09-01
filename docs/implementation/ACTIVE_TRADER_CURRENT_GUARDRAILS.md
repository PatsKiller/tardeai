# Active Trader — Current guardrails (Stage 0)

Status:      ACTIVE
as_of:       2026-07-27T12:13:37-04:00
Measured at: efcc51365 / not measured

These guardrails apply to Stage 0 work and remain binding until a later stage is
explicitly authorized by architecture + operator process.

## Architecture (v3.3)

1. Deterministic safety core remains sovereign for risk, eligibility, and broker truth.
2. Live momentum scalp requires a **signed session authorization envelope** (not built in Stage 0).
3. OpenD **trade unlock** is never sufficient authorization; Stage 0 does not unlock.
4. Unattended build must not enable live feature flags, request real 2FA, or submit real orders.

## Stage 0 hard denials

| Action | Status |
|--------|--------|
| Live place / modify / cancel order (**any** venue: Schwab, Moomoo, Alpaca) | **DENIED** |
| Session authorize / 2FA ceremony | **DENIED** |
| `live_canary: true` | **DENIED** |
| Multi-account live failover without session envelope | **DENIED** |
| Unattended discover-and-fire without operator opt-in | **DENIED** (product rule) |
| Runner promotion path | **DENIED** |
| Moomoo order path / OpenD trade unlock | **DENIED** (Moomoo Stage 0 is data-plane only) |
| Agent `OPERATIONAL` | **DENIED** (Packet E Phase 10 still prepare-only) |
| Enable agent timers / cron for AT | **DENIED** |
| Production schedule mutation via Packet G | **DENIED** |

## Product intent vs Stage 0 authority

| Intent (later stages) | Stage 0 |
|-----------------------|---------|
| Schwab primary; Moomoo/Alpaca augment on compliance block | Documented only; no routing |
| Moomoo L2 + tape for scalp | Documented; data plane remains Packet F scaffold |
| Operator opt-in size + allocation → managed entry/exit | Documented only |
| Near-ready / below-RVOL desk (not only scanner GO) | Documented only |

## Read API guardrails

- Methods other than GET on `/api/v3/active-trader/*` → **405**
- Response always includes `write: false` and `canary: false` at stage 0
- `venues.*.data` / `venues.*.execution` always **false** at stage 0
- No DSN or secret values logged by Packet G or AT Stage 0 modules
- Health/status work **without** live broker credentials

## Relation to existing desks

| Desk | May still operate as today | Does Stage 0 change it? |
|------|---------------------------|-------------------------|
| Broker Proposals (paper) | Yes, under existing gates | No |
| Journal | Yes | No |
| Broker Orders preview/drafts | Yes (existing gates) | No live enablement |
| TradingHub Scalp scanner | Yes (research) | No AT canary |
| Agent SHADOW acceptance | Yes (Packets D/E) | No |

## Operator packet G

- Default **PREPARE-ONLY**
- `--preflight` requires `--ack APPLY-AT-STAGE0`
- `--execute` + ack: register docs checksum + read-flag snapshot only
- Execute must fail closed if example config has `live_canary` or `order_routes` true

## Non-goals reminder

Stages 1–13, multi-account live, runner, 2FA order path, and Stage 14 canary are
**out of scope** for this baseline.
