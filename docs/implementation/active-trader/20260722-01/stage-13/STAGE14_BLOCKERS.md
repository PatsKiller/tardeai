# Stage 13 — Stage 14 Blockers

Stage 14 (live canary) is **BLOCKED**. It must not start without a new, exact-SHA owner authorization
AND all of the following independently green:

| # | Blocker | Current state |
|---|---|---|
| 1 | ≥30-minute continuous open-session capture PASS | PENDING |
| 2 | Five-RTH-session observation PASS | 0 of 5 |
| 3 | Premarket Level 2 suitability — sufficient representative evidence | UNPROVEN |
| 4 | Stage 9 scored-fire corpus (incl. ≥60 where required) | BLOCKED |
| 5 | Stage 10 promotion review PASS | BLOCKED |
| 6 | BF-1 broker-resident, disconnect-surviving protection PROVEN | UNPROVEN |
| 7 | `active_trader_live_canary_enabled` flag intentionally enabled under authorization | OFF (unrepresentable) |
| 8 | Separate Stage 14 exact-SHA owner authorization prompt | NOT ISSUED |

## Notes
- BF-1 is specifically a **Moomoo live-canary** blocker: without proven broker-resident protection that
  survives an OpenD/gateway disconnect, live Moomoo scalping stays disabled regardless of other gates.
- Prerequisite for blockers 1–3: the Stage 5 observation launcher + exchange-calendar source must be
  built and checked in (see `STAGE5_RESUME_REQUIREMENTS.md`).
- Nothing in Stages 12–13 advances any of these; they remain owner-gated.
