# Operator TODO — after Premarket Observation Harness build

**Run:** 20260722-01 · **Date:** 2026-07-23 · PR #150 (draft, do not merge)

The observation harness is **IMPLEMENTED** and GREEN_OBSERVATION_HARNESS_READY. Open actions:

1. **Issue an observation authorization marker + Session 1 prompt** (separate owner transaction). The
   marker (run_id, session_number, expected_git_sha, target_market_date, target_window, symbols_policy,
   created_at, expires_at, owner_authorization_version — no secret) unlocks the live path. Without it
   the launcher returns BLOCKED_OWNER_AUTHORIZATION_REQUIRED.
2. **Run the five qualifying RTH observation sessions** (0/5) during open sessions -> unblocks Stage 9
   acceptance / Stage 10 promotion.
3. **BF-1** — broker-resident protection proof still required before any Moomoo live canary.
4. **Stage 14** — separate exact-SHA authorization; do not merge PR #150 before then.

Stage 12 (CONDITIONAL_PASS) and Stage 13 (GREEN_CLOSED_PROMOTION_BLOCKED) remain unchanged.
