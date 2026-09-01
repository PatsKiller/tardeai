# Closed-Loop Step 6 — Lessons → Scoring (Shadow-First Evidence) (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T22:42:05-04:00
Measured at: efcc51365 / not measured

## Audit item
"Lessons appear not applied to production scoring." Plan: feed lesson rollups into a shadow channel,
compare vs production using realized outcomes, and **only graft after evidence — never silently alter
GO/WAIT.**

## Change (evidence layer ONLY — production scoring untouched)
`scripts/evaluate_shadow_efficacy.py` + `candidate_shadow_efficacy` table. For each lesson-adjusted
shadow score (candidate_shadow_scores, Step 5) whose candidate became a closed paper trade, it
classifies whether the shadow adjustment was directionally correct vs the realized outcome:
- shadow more cautious (Δ<0): correct if outcome non-WIN, wrong if WIN;
- shadow more bullish (Δ>0): correct if WIN, wrong if non-WIN.
Aggregates hit-rate and emits a **graft verdict** gated on a sample floor (≥20) and hit-rate (≥0.60).

## Result (run 2026-06-05)
- evaluable candidates: **3** (all the shadow loop has realized outcomes for yet).
- correct 3 / wrong 0 (shadow penalized 3 non-winners: ANY PHANTOM, NVDA PHANTOM, TMHC BREAKEVEN).
- hit_rate 1.0 BUT **graft_verdict = INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT** (n=3 ≪ 20 floor; and 2 of 3
  are PHANTOM = no real fill, so effectively ~1 real outcome). **Lessons are NOT grafted into production.**

## Why this is the correct closure
The shadow channel + evidence harness are in place; lessons demonstrably *would* nudge scoring (and so
far in the right direction), but the sample is far too small to justify changing production GO/WAIT.
Grafting remains an explicit operator-gated decision that fires only when this evaluator clears the
sample-size + hit-rate bar. As paper trades accumulate, the verdict updates automatically.

## Safety
ALPACA_MODE=paper, LLM live disabled. No order/broker writes, **no GO/WAIT mutation**, no strategy/
threshold/proposal changes, no Phase-205. Additive evidence table + read-only analysis only.

## Closed-loop certification — all 6 audit items implemented (shadow-safe)
1 execution lineage · 2 Hermes trade linkage · 3 keyspace unification · 4 edge comparison ·
5 shadow→DB + loop-closure flag · 6 lessons→scoring shadow-first (do-not-graft gate). The loop is wired
end-to-end; learning influence on production stays gated behind evidence + operator approval.
