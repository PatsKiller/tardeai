# Operator TODO — after Stage 13 (GREEN_CLOSED_PROMOTION_BLOCKED)

**Run:** 20260722-01 · **Date:** 2026-07-23 · PR #150 (draft, do not merge)

Stages 12–13 complete. Dual operation is **ready but inactive**. Open operator actions:

1. **Build + check in the Stage 5 observation launcher + exchange-calendar source** (prerequisite for the
   capture/observation gates). See `STAGE5_RESUME_REQUIREMENTS.md` and stage-12 `CONDITIONAL_GATES.md`.
2. **Run the ≥30-min continuous open-session capture**, then the **five-RTH observation** (0/5), then judge
   **premarket Level 2 suitability**.
3. **Stage 9 scored-fire corpus** (incl. ≥60 where required) → **Stage 10 promotion review**.
4. **BF-1** — obtain the affirmative broker-resident-protection (OpenD-down) proof before any Moomoo canary.
5. **Stage 14** — issue a NEW exact-SHA owner authorization only when all above are green. Do not merge
   PR #150 before then.

## When ready to run dual in production (separately authorized)
- Follow `SWITCH_RUNBOOK.md` (adds an isolated `/v3-next/` reverse-proxy location; leaves `/v3` untouched;
  all live flags stay OFF).
- Rollback via `ROLLBACK_RUNBOOK.md` (remove the `/v3-next/` location; `/v3` returns immediately).

## Non-blocking
- Doc-precision item (D3): scope the "no real 2FA" invariant to order/trade 2FA vs one-time data-gateway
  device authorization.

Prior operator items retained in the run-level and stage-12 OPERATOR_TODO files.
