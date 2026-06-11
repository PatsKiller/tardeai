# Daily Execution Coaching Queue — governance

**Created:** 2026-06-11 · **Type:** read-only analytics / operator workflow · **Status:** advisory, live.

Turns the completed execution-quality system (graded trades + Grok reviews + hypothesis backtests) into a
ranked daily answer to: **"what should John study, fix, or test next?"** — without changing any live trading
behavior.

## 1. This is coaching and review ONLY
- Reads `trade_execution_quality`, `trade_execution_grok_reviews`, `trade_execution_hypothesis_results`.
- Writes ONLY its own additive tables (`daily_execution_coaching_runs`, `daily_execution_coaching_items`,
  `daily_execution_grok_digests`).
- Touches **no** live strategy YAML, GO/WAIT, screener, ATM, proposal approval, interlock, broker, or
  order-routing path. `validate_schwab_no_writes.py` remains **12/12** before and after.

## 2. No automatic live-strategy changes
Nothing here promotes a strategy, changes a threshold, or alters a config. The queue surfaces *evidence*; the
operator acts. The rebuild endpoint is **dry-run by default** and only writes the coaching tables on
`apply=true` (never any trading state).

## 3. Hypotheses must pass the full gate before any live use
A `hypothesis_candidate` in the queue is a **shadow-research candidate only**. Promotion path:
1. **Minimum sample-size gate** (current hypotheses below sample, or with negative avg Δ/sh, are marked
   unsupported — *do not graft*).
2. **Shadow test** (paper / replay, isolated from live).
3. **Operator review** (John approves explicitly).
4. **A1A documentation update** (architecture doc + changelog + consistency audit).
5. **Rollback plan** documented before any live wiring.

As of this run, all three execution hypotheses (volume-confirmed entry / hold-above-VWAP / MACD-rollover exit)
showed **negative average Δ/sh** — the evidence does NOT support grafting them. The queue says so explicitly.

## 4. Grok is interpretive, not authoritative
`grok_daily_execution_digest.py` summarizes the **already-computed** deterministic queue into strict JSON. A
parse failure is stored `parse_failed` and never fabricated. Grok's headline/lessons are framing for the
operator — they do not rank, gate, or authorize anything.

## 5. Deterministic metrics are the primary evidence
Ranking is computed from replay metrics (volume confirmation, during-hold capture, missed-runner %, hypothesis
Δ), not from Grok. Implausible microcap values (e.g., 900%+ post-exit moves from splits/data artifacts) are
filtered out of missed-runner items.

## Components
| Layer | Artifact |
|---|---|
| Schema | `migrations/2026-06-11_daily_execution_coaching.sql` (3 additive tables) |
| Builder | `scripts/build_daily_execution_coaching.py` (`--days N --source all --apply`; dry-run default) |
| Grok digest | `scripts/grok_daily_execution_digest.py` (strict JSON, advisory) |
| API (read-only) | `GET /api/v2/journal/daily-execution-coaching[/latest]`, `POST …/rebuild` (dry-run default) |
| UI | `ExecutionCoachPanel.tsx` in Journal → Trades (advisory banner; replay links) |
| Brief (manual) | `build_daily_execution_coaching.py --days 5 --brief` — **manual command only, NO cron enabled** |

## Item types & ranking
`repeated_mistake` · `premature_exit` (green-but-poorly-executed winners) · `missed_runner` · `symbol_review`
· `strategy_family_review` · `hypothesis_candidate`. Ranked by severity (critical→low) then sample size.
Repeated behaviors outrank one-off anecdotes by construction (min sample ≥2 for repeated/symbol items).

## What this run found (200-day window)
Top behavior: **entry without volume confirmation ×45**; **30 winning trades poorly executed**; **premature
exit before runner ×13**. Replay targets: AXTI, ANY, FUSE, PFE, ZSL. All hypotheses unsupported by evidence.

## Cross-references
- [`../architecture/EXECUTION_QUALITY.md`](../architecture/EXECUTION_QUALITY.md) — the grading engine feeding this queue.
- [`../architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](../architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md) — read-only foundation + write fence.
