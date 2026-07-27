# Stage 13 — Promotion Gate Matrix

**HEAD:** 4e4176ba · **Date:** 2026-07-23 · Terminal state: **GREEN_CLOSED_PROMOTION_BLOCKED**

| Gate | State |
|---|---|
| Stage 0–8, 11 | GREEN_CLOSED |
| Stage 9 | GREEN_IMPLEMENTED_DATA_VALIDATION_PENDING |
| Stage 10 | GREEN_IMPLEMENTED_PROMOTION_BLOCKED |
| Stage 5 credential/agreement gate | CLEARED (agreement complete; device trusted) |
| Stage 5 data-only smoke | PASS |
| Stage 12 litmus | CONDITIONAL_PASS |
| Stage 13 dual-operation readiness | GREEN_CLOSED_PROMOTION_BLOCKED |
| ≥30-min continuous open-session capture | PENDING (launcher not yet checked in) |
| Five-RTH observation | 0 of 5 — PENDING |
| Premarket Level 2 suitability | UNPROVEN |
| Stage 9 promotion | BLOCKED |
| Stage 10 promotion | BLOCKED |
| BF-1 | UNPROVEN |
| Stage 14 live canary | BLOCKED (separate exact-SHA authorization required) |

## Promotion blockers that MUST remain until independently green
1. Moomoo regulatory agreement — CLEARED (this one is now satisfied)
2. Stage 5 data smoke — PASS (satisfied)
3. ≥30-minute RTH capture — PENDING
4. Five-RTH observation — 0/5 PENDING
5. Stage 9 promotion evidence (incl. ≥60 scored fires where required) — BLOCKED
6. Stage 10 promotion review — BLOCKED
7. BF-1 (for Moomoo live canary) — UNPROVEN
8. Separate Stage 14 owner authorization — REQUIRED

Dual operation is **ready but inactive**: /v3 and /v3-next can coexist and be switched/rolled back
operationally, but no live traffic or live authority is enabled and PR #150 remains draft.
