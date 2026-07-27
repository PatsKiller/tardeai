# Stage 12 — Conditional Gates (CONDITIONAL_PASS)

Verdict is **CONDITIONAL_PASS**. The following conditions must independently become green before any
promotion beyond this stage. None is satisfied yet.

| # | Condition | State | Unblocks |
|---|---|---|---|
| C1 | ≥30-minute continuous open-session capture PASS | PENDING (needs open RTH; observation launcher not yet checked in) | Stage 5 data validation |
| C2 | Five qualifying RTH observation sessions PASS | 0 of 5 — PENDING | Stage 9 acceptance / Stage 10 promotion |
| C3 | Premarket Level 2 strategy suitability — sufficient representative evidence | UNPROVEN | claim of momentum-scalp suitability |
| C4 | Stage 9 scored-fire corpus reaches required promotion evidence, incl. ≥60 scored fires where the controlling program requires it | BLOCKED | Stage 9 promotion |
| C5 | Stage 10 multi-broker simulation promotion review PASS (after C1–C4) | BLOCKED | Stage 10 promotion |
| C6 | BF-1 broker-resident, disconnect-surviving protection proven (affirmative OpenD-down trigger test) | UNPROVEN | Moomoo live canary only |
| C7 | Stage 14 live-canary NEW exact-SHA owner authorization | BLOCKED | Stage 14 |

## Current gate posture
- Stage 9 promotion: **BLOCKED**
- Stage 10 promotion: **BLOCKED**
- BF-1: **UNPROVEN** → live Moomoo scalping BLOCKED
- Stage 14: **BLOCKED** (live_canary flag OFF, unrepresentable)
- PR #150: **draft**, not merged

## Non-blocking follow-ups
- Documentation-precision item (D3): restate the "no real 2FA" invariant to scope it to order/trade 2FA
  vs one-time data-gateway device authorization.
- Prerequisite for C1/C2: build + check in the Stage 5 observation launcher (continuous 07:00–10:05
  runtime, P1–R2 windows, extended-hours K_1M/TICKER, full L2 metrics, WAL/Parquet/replay, three-verdict
  output) and an exchange-calendar source. Tracked in `STAGE5_RESUME_REQUIREMENTS.md` / OPERATOR_TODO.
