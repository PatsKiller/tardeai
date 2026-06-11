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

## Worked example — the queue in action (2026-06-11 replay walkthrough)
The queue pointed at three trades that together map John's complete execution profile. Each was opened in the
replay chart (entry/exit markers + MFE/MAE + post-exit line) to verify the deterministic grade:

| Trade | Type | Leak | Evidence | Lesson |
|---|---|---|---|---|
| **CTXR** (srt:320) | scalp | **Entry** | Bought $1.54 at **RVOL 0.26** (¼ avg volume) into a dead tape; 35 min of chop before the real move; capture 48% | Wait for volume to confirm (RVOL >1) BEFORE entering |
| **AXTI #255** (srt:255) | swing | **Exit / during-hold** | +$15,945 (6.5×) but rode the $26.66 peak back to an $18.83 exit; capture 68%; MAE only $0.14 (clean entry) | Trail the stop once extended |
| **AXTI #257** (srt:257) | swing | **Exit / post-exit** | Sold $17.74 (+101%) on a pullback; AXTI then ran to $28.65 = **+62% missed** | Keep a runner; don't fully exit a live trend |

Take-away: outcomes are net-positive but edge leaks on **both** ends — entries before volume, exits too soon
or too late. This is precisely why the queue ranks *entry-without-volume ×45* (#1) and *premature-exit-on-
winners* (#2), while flagging that the backtested fixes do NOT yet pass evidence — so the directive is *replay
and study*, not *change the rules*. The walkthrough was read-only; no live behavior changed.

## Cross-references
- [`../architecture/EXECUTION_QUALITY.md`](../architecture/EXECUTION_QUALITY.md) — the grading engine feeding this queue.
- [`../architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](../architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md) — read-only foundation + write fence.
