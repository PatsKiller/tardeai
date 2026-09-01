> **Canonical model note:** Paper trades are the first executable source and first backfilled source. The canonical learning loop is all-trades, broker/account neutral (`trade_instances`). `paper_trade_id` is a compatibility key; `trade_instance_id` is the canonical key going forward. See `CLOSED_LOOP_ALL_TRADES_ABSTRACTION_20260606.md`.

# Closed-Loop Learning Certification — RE-AUDIT (2026-06-05, after Steps 1–6)

Status:      ACTIVE
as_of:       2026-06-05T23:46:56-04:00
Measured at: efcc51365 / not measured

Read-only re-run of the certification audit following the six closed-loop fixes. SELECT-only; no trading,
GO/WAIT, strategy, proposal, order, broker, or live changes.

## Verdict: STRUCTURE = PASS · DATA DENSITY = PARTIAL
Every broken join from the original audit now has a working mechanism (joins exist and flow forward).
Remaining low percentages are **data accumulation** (small paper-trade sample, upstream signal-capture
rate, NO_DATA backtests, conservative 1:1 backfill) — not missing plumbing. Learning→production influence
is wired but **gated behind evidence + operator approval** (lessons NOT grafted).

## Was → now (43 closed paper trades / 169 outcome chains / 1170 Hermes rows)
| Join / signal | Original | Re-audit | Step |
|---|---|---|---|
| paper_trade.signal_id / source_signal_id | 0% | **27%** (capped by 44% upstream proposal capture) | 1 |
| paper_trade.execution_account/broker/env | 0% | **84%** | 1 |
| paper_trade.candidate_id | 0% | **84%** | 1 |
| paper_trade.trade_key | absent | **100%** | 3 |
| hermes_research_intelligence.related_trade_id | 0% (0/1170) | write-path wired; **2** backfilled (1:1) | 2 |
| backtest results linked → paper_trade | 0 | **34** (backtest engine run; 32 full + 2 insufficient; 8 of 42 lacked history) | 3 |
| post-exit edge comparison | none | **43** trades; 2 proposal-edge + **32 per-trade backtest** comparisons | 4 |
| shadow scores in DB | 0 (file-based) | **57** (candidate_shadow_scores; scorer persists each run) | 5 |
| proposal_outcome_chain.outcome_fed_back | 5% | **11%** (19/169) | 5 |
| lessons → production scoring | not applied | shadow-first evidence layer + **do-not-graft gate** | 6 |

## Per-stage status (vs original FAIL items)
- Hermes reflection linkage: FAIL → **wired** (forward stamping; 2 historical backfilled). Grows as paper-loop reflection runs.
- Backtest comparison: FAIL → **wired** (edge comparison table + paper trades in backtest scope). Populates on next backtest cron.
- Shadow score DB-linkage: FAIL → **FIXED** (57 rows, DB-keyed to candidate).
- Loop-closure flag: FAIL → **improving** (5%→11%; rises as lessons/edge/Hermes accrue).
- Lessons→scoring: FAIL → **shadow-first, gated** (evidence: 3/3 correct so far, but n=3 ≪ 20 → DO NOT GRAFT).
- Post-exit review coverage: unchanged (multi_reviews 70% / lifecycle 53% / thesis 37%) — pre-existing, not in scope of Steps 1–6.

## Remaining (data density, not structure)
1. signal_id stuck at 27% until upstream proposals capture source_signal_id more often (>44%).
2. backtest-linked now **34/42** after running the engine (8 lacked sufficient price history) — refreshes on each scheduled run.
3. Hermes backfill conservative (1:1 only); forward write-path covers new paper-loop reflection.
4. Shadow graft remains blocked (n<20) — by design; the evaluator opens it automatically when evidence clears.

## Safety
SELECT-only audit. ALPACA_MODE=paper, live disabled. No order/GO-WAIT/strategy/proposal/Phase-205 changes.

## Re-audit snapshot v2 (2026-06-05, after backtest run + edge enrichment)
Verdict unchanged: **STRUCTURE = PASS · DATA DENSITY = PARTIAL (improving)**. All six mechanisms in
place and flowing; remaining low percentages are data accumulation, learning→production stays gated.

| Stage | Coverage now |
|---|---|
| 1 execution lineage — signal_id / broker / candidate | 27% / 84% / 84% |
| 3 trade_key | 100% |
| 2 hermes related_trade_id | **4** (Step 7 added closed_paper_trade targeting tier; 6/6 targets linked; cron works through ~40 remaining) |
| 3 backtest results → paper_trade | 34 linked (32 full) |
| 4 edge comparison | 43 trades · 2 proposal-edge · **32 per-trade backtest** |
| 5 candidate_shadow_scores (DB) | 57 |
| 5 outcome_fed_back | 11% (19/169) |
| 6 shadow efficacy / graft | 3 evaluable → INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT (gated) |

**Weakest remaining link = Hermes trade linkage** (2/1256): the stamping is correct, but Hermes is
currently researching live Schwab holdings (no paper_trade to link). It rises automatically when the
challenger researches paper-loop symbols. Everything else is structurally closed; the loop now produces
real per-trade learning signal (e.g. 27 of 32 graded paper trades show a better entry existed / early exit).

## Re-audit snapshot v3 (2026-06-05, after Step 7 Hermes targeting fix)
Verdict unchanged: **STRUCTURE = PASS · DATA DENSITY = PARTIAL (improving on its own)**.

| Stage | v2 | v3 |
|---|---|---|
| 1 signal_id / broker / candidate | 27% / 84% / 84% | 27% / 84% / 84% |
| 3 trade_key | 100% | 100% |
| 2/7 hermes related_trade_id | 2 (targets were live Schwab) | **6 and climbing** (closed_paper_trade tier draining 38 remaining) |
| 3 backtest → paper_trade | 34 | 34 |
| 4 edge comparison | 43 · 2 · 32 | 43 · 2 · 32 |
| 5 candidate_shadow_scores | 57 | 57 |
| 5 outcome_fed_back | 11% (19/169) | **15% (25/169)** — new Hermes links fed the loop-closure flag |
| 6 shadow efficacy / graft | 3, GATED | 3, GATED |

Step 7 closed the last structural gap (Hermes targeting). Hermes linkage now self-drains via the
challenger cron (2→4→6 across runs), and each new trade-linked reflection lifts outcome_fed_back through
the Step 5 backfill — the two compound automatically. All learning→production influence remains gated.
