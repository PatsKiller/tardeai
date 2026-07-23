# Stage 13 — Dual-Operation Readiness (inactive)

**Run:** 20260722-01 · **HEAD:** 4e4176ba · **Terminal state:** GREEN_CLOSED_PROMOTION_BLOCKED

Classic /v3 and new /v3-next can coexist and be switched/rolled back operationally **without enabling any
production traffic or live authority**. No production deployment change is executed here.

## Proofs

| Requirement | Result | Evidence |
|---|---|---|
| /v3 source & behavior unchanged | PASS | 0 files changed vs origin/main under `apps/command-center-v3`; v3 build OK |
| /v3 build passes | PASS | vite build 1252 modules |
| /v3-next build passes | PASS | vite build 35 modules + 9 vitest |
| Separate bundle + base path | PASS | `/v3/` vs `/v3-next/`; separate `dist` dirs |
| No route collision | PASS | drill: v3-next → 404 on `/v3/`; sibling prefixes |
| No asset collision | PASS | distinct base + content-hashed names |
| No API contract collision | PASS | v3-next has no production API mount; read_api standalone |
| No service collision | PASS | no unit installed; moomoo units static/inactive |
| No port collision | PASS | 7789 vs 7790 loopback; 11112 lab |
| Switch plan documented | PASS | SWITCH_RUNBOOK.md |
| Rollback plan documented | PASS | ROLLBACK_RUNBOOK.md (motion proven in drill) |
| Fixture/replay parity documented | PASS | V3_V3NEXT_PARITY_MATRIX.md |
| Live Moomoo parity explicitly pending | PASS | matrix marks LIVE_DATA_PENDING / PREMARKET_VALIDATION_PENDING |
| All production live flags OFF | PASS | 22/22 OFF incl live_canary |
| All Active Trader units disabled | PASS | 5 moomoo units static + inactive |
| PR current & draft | PASS | PR #150 draft=true |
| GitHub commits complete | PASS | pushed through 4e4176ba (+ Stage 13 commit) |
| Drive artifacts complete | PASS | Stage 13 drive manifest |
| Operator email delivered | PASS | Stage 13 closeout email |

## Local dual-run drill
Both bundles served concurrently on loopback (7789/7790); v3-next isolated from /v3 routes; rollback
(kill v3-next) kept /v3 at 200; teardown left 0 processes / 0 listeners. See LOCAL_DUAL_RUN_REPORT.md.

## Posture
Ready to run dual **when authorized** (SWITCH_RUNBOOK), reversible (ROLLBACK_RUNBOOK), with all live
authority OFF. Promotion remains BLOCKED (PROMOTION_GATE_MATRIX.md, STAGE14_BLOCKERS.md).
