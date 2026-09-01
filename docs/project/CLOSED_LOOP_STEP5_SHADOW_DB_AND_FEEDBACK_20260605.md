# Closed-Loop Step 5 — Shadow Scores → DB + Loop-Closure Flag (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T22:38:02-04:00
Measured at: efcc51365 / not measured

## Gaps fixed (from certification audit)
- Shadow scores were **file-based** (`data/learning/shadow_scores/*.json`), not DB-linked to candidates.
- `proposal_outcome_chain.outcome_fed_back` was set on only **5%** of chains — the loop rarely recorded
  that an outcome actually fed learning.

## Changes (additive, read-only w.r.t. trading)
1. **candidate_shadow_scores** table (UNIQUE symbol+strategy+run) keyed to the candidate:
   original_score, shadow_score, delta, decision, adjustment_count, learning_adjustments (JSONB),
   run_timestamp. Loaded from the existing shadow JSON files (57 rows / 55 symbols), and
   `strategy_learning_shadow_scorer` now calls `persist_shadow_scores.persist(output)` so every future
   shadow run writes to the DB.
2. **outcome_fed_back closure** (`persist_shadow_scores.py`): set TRUE + feedback_at for an outcome chain
   when its paper_trade has **derived learning** — a lesson (trade_lesson_memory), an edge-comparison
   (paper_trade_edge_comparison, Step 4), or a Hermes trade-reflection (hermes_research_intelligence
   related_trade_id, Step 2). 9 → **19** of 169.

## Result
- candidate_shadow_scores: 57 rows, 55 distinct symbols (was 0 in DB). Top deltas e.g. ALOY/BBCP/ABVX
  swing_trade −12 (learning would push WAIT). Shadow only — `not_live`, never alters production GO/WAIT.
- outcome_fed_back: 9 → 19 (the chains whose outcomes now demonstrably fed lessons/edge/Hermes).

## Safety
ALPACA_MODE=paper, LLM live disabled. No order/broker writes, no GO/WAIT mutation (shadow stays shadow),
no strategy/proposal-status changes, no Phase-205 changes. Additive table + flag update on the
learning-bookkeeping table only.

## Closed-loop status after Steps 1–5
Execution lineage ✓ · Hermes trade linkage ✓ · keyspace unification ✓ · edge comparison ✓ ·
shadow-DB + loop-closure flag ✓. Remaining audit item: **lessons → production scoring** must stay
shadow-first (candidate_shadow_scores is the shadow channel) and only graft after evidence — never
silently alter GO/WAIT.
