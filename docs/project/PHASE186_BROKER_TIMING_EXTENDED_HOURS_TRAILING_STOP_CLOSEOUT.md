# Phase 186: Broker Timing, Extended Hours, and Trailing Stop Audit — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T01:02:56-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02
**Status**: COMPLETE

## Results

### Broker/Account Routing

| Check | Result |
|-------|--------|
| Broker/account routing correct | YES — broker=alpaca, mode=paper in accounts table |
| Hard-coded "paper as broker" | NO — 'alpaca_paper' is an account label, not broker name |
| Live Alpaca endpoint reachable | NO — blocked by RuntimeError |
| Paper endpoint used | YES — paper-api.alpaca.markets |

### Extended Hours

| Check | Result |
|-------|--------|
| Alpaca adapter supports extended_hours | **YES** — premarket 4AM, after-hours to 8PM |
| Extended-hours flag set on orders | **YES** — `extended_hours: True` |
| Limit orders enforced in extended hours | **YES** — market orders forced to limit |
| Bracket orders blocked in extended hours | **YES** — simple limit only |
| Current auto-approver start time | **07:00 ET** (config), **09:35 ET** (code fallback) |
| Recommended auto-approver start time | **04:00 ET** (match Alpaca premarket) |

### ELMT #160 Expiry Issue

| Check | Result |
|-------|--------|
| ELMT #160 manual approval needed | **NO** — auto-approver should handle it at 07:00+ ET |
| Premarket expiry issue confirmed | **YES** — 4-hour flat expiry kills overnight proposals |
| Proposal created | 00:13 ET |
| Proposal expires | 08:13 ET |
| First ATM eval | 07:00 ET (1h13m margin — tight but sufficient TODAY) |
| Root cause | 4-hour flat expiry + auto-approver starts after many proposals expire |

### Extended-Hours Policy (Designed, Not Yet Implemented)

| Policy | Decision |
|--------|----------|
| Extended-hours entry | ALLOW with stricter gates (spread max 1%, limit only, half size) |
| Extended-hours exit | ALLOW for stops and targets, defer trailing to market hours |
| Extended-hours strategies | Block momentum_scalp and gap_and_go (need regular hours liquidity) |

### Stop/Trailing Audit

| Metric | Value |
|--------|-------|
| Total stopped-out trades | 6 |
| Hard stop count | **6** |
| Trailing stop count | **0** |
| Hard-to-trailing converted | **0 (0%)** |
| Operator trailing switch | 1 (NVDA, via Telegram) |
| Trailing algorithm exists | **YES** — strategy_trailing_policy v2.3, R-multiple tiers |
| Trailing algorithm ever triggered | **NO** — no trade reached +1R threshold |
| Trailing shadow design ready | **YES** — parallel calculation without execution |

### Safety

| Check | Result |
|-------|--------|
| Live trading | ZERO |
| Live Alpaca endpoint | BLOCKED |
| Level 7 | PROHIBITED |

### Next Gate

1. Apply proposal expiry fix (Step 1 — prevents lost overnight proposals)
2. Extend auto-approver cron to 4-19 (Step 2 — matches Alpaca window)
3. Add extended_hours config section (Step 3)
4. Update _in_operating_hours() to use extended config (Step 4)
5. Accumulate more paper trades to test trailing stop algorithm
6. After 100+ trades: evaluate trailing shadow data

## Deliverables

- [x] Phase 186G: `docs/atm/PHASE186G_BROKER_ACCOUNT_ROUTING_CORRECTION_AUDIT.md`
- [x] Phase 186H: `docs/atm/PHASE186H_ALPACA_EXTENDED_HOURS_CAPABILITY_AUDIT.md`
- [x] Phase 186I: `docs/atm/PHASE186I_AUTO_APPROVER_TIMING_CORRECTION_DESIGN.md`
- [x] Phase 186J: `docs/atm/PHASE186J_EXTENDED_HOURS_RISK_GATES.md`
- [x] Phase 186K: `scripts/audit_stop_to_trailing_conversion.py` + `docs/paper_trading/PHASE186K_STOP_TO_TRAILING_CONVERSION_AUDIT.md`
- [x] Phase 186L: `docs/paper_trading/PHASE186L_TRAILING_STOP_ALGORITHM_SPECIFICATION.md`
- [x] Phase 186M: `docs/atm/PHASE186M_AUTO_APPROVER_TRAILING_STOP_IMPLEMENTATION_PLAN.md`
- [x] Phase 186N: This closeout document
