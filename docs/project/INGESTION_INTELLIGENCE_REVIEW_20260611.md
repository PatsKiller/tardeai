# Ingestion & Intelligence Due-Diligence Review (Finviz / Trade AI / Hermes) — 2026-06-11

Status:      ACTIVE
as_of:       2026-06-11T13:23:28-04:00
Measured at: efcc51365 / not measured

**Method:** two code-tracing audits (Finviz list machinery; Hermes learning loops) + direct DB quantification
(30-day windows). Confirmed findings carry file:line or query evidence; assumptions are labeled. Builds on the
same-day SYSTEM_DEEP_REVIEW (proposal pipeline + backtesting audits).

---

## A. Finviz audit

**List inventory (assets/screeners.yaml v12.3):** 18 screeners defined, 17 scheduled across 9 run windows
(0400–1730). **"Momentum scout" = `prime_setups`** (RVOL>5×, gap>10%, $2–20, float<50M, day_scalp) — it and
`watchlist_setups` (RVOL>3× variant) run **6×/day**; everything else runs 1–3×/day. `covered_call_candidates`
is defined but **never scheduled**.

**Signal volume:** measurable only in aggregate — 30d: **23,940 scan rows, 2,931 distinct symbols, 119 GO**.
**Per-list volume is UNMEASURABLE**: `trade_ai_scans.screener_label` is NULL on all 23,940 rows. Root cause
traced: `finviz_ingestion.py:326-335` tags every row with `screener_name`/`source_lists`, but
`trade_ai_orchestrator.py:631` **drops it at INSERT** (hardcodes `source='screener'`); the weekly incubator
then records `source_first_seen='full'` (run_type, not list), so `report_finviz_screener_quality.py:70-96`
reports on a field that never contains a screener name.

**Noise vs signal:** the list *designs* are mostly complementary, not duplicative (momentum RVOL spectrum
5×/3×/1.5×; quality vs dividend vs defensive; pre- vs post-earnings; small- vs large-cap growth). The noise
problem is not list overlap — it's (a) **unattributable flow** (no list-level hit-rates possible), (b) **44%
of scans missing sector**, (c) income/ETF lists feeding a momentum-scoring pipeline that structurally NOGOes
them (they exist to seed watchlist/income context, but nothing measures that contribution either).

**Is momentum scout outperforming?** **Unknowable today** — and that is the finding. The operator's most-run
list has no attribution trail to GOs, proposals, or trades.

**Recommendation: REFINE, don't rebuild.**
1. **Restore attribution** (the unlock): pass `screener_name` through orchestrator INSERT → `screener_label`;
   carry it to incubator + proposals. ~1 hour of code; after 2–4 weeks the keep/kill question answers itself
   from data.
2. Then prune by evidence: any list with <X candidates reaching GO/incubator per month gets demoted to weekly.
3. Schedule-or-delete `covered_call_candidates` (options are parked anyway → archive it).
4. Sync stale `config/candidate_sources.yaml` with screeners.yaml.

## B. Trade AI ingestion engine audit

**Optimization level: structurally sound, statistically blind.** The funnel is volume-sane (23,940 → 119 GO
(0.5%) → 136 proposals → 38 trades; repeat-GOs modest, max 5/symbol/30d). Hardening is real (micro-float RVOL
caps, reverse-split disqualifiers, catalyst-relevance validation, fail-closed risk gate).

**Signal-quality weaknesses (confirmed):**
1. **No outcome feedback** — scoring.py never sees live win-rates, execution quality, or runner_type; a 33%-WR
   pattern scores identically to a 100% one (same finding as the morning review; still the #1 gap).
2. **Sector enters scoring as cliff-edged buckets** (5/3/1/0) and silently zeroes when market context fails;
   GO concentration (Tech 37 + Healthcare 27 of ~111 tagged GOs) is a *scoring-layer* artifact — intake is
   actually diverse (Financials 2,711 scans > Industrials 1,811 > Tech 1,757).
3. **Metadata holes poison everything downstream:** sector NULL on 44% of scans; screener_label NULL on 100%;
   `source_tier` NULL on 3,167/3,184 watchlist rows. The "trade desk" columns exist; nothing writes them.
4. Catalyst keyword tiers structurally favor tech/biotech narrative density (FDA/AI/chip headlines out-tier
   industrial catalysts) — a plausible (labeled: hypothesis) contributor to GO tech-tilt.

**Finviz vs Trade AI:** not duplicative — Finviz is the candidate feed, Trade AI is enrichment+decision. The
weakness is the *seam*: attribution and sector metadata die crossing it.

**Downstream integration:** tight mechanically (GO → 11-gate proposal chain), weak informationally (no pillar
breakdown surfaced; funnel statuses lossy — both from the morning audit, unchanged).

## C. Hermes audit

**Learning/adaptability: dynamic, NOT adaptive (confirmed).** Scores recompute every 30 min
(`hermes_watchlist_scorer.py:160-185`, 7 weighted factors, coverage-confidence penalty, snapshots to
`hermes_score_history`) — so outputs *move* with the data. But **nothing learns**: the H-4 calibration job
(`hermes_score_calibration.py:46-51`) pairs price snapshots (not trade outcomes) and is advisory-only;
**zero feedback from realized P&L into factor weights, discovery, or source credibility**. The external
feedback loop scores Grok/ChatGPT lane usefulness only; source curation tracks promotion yield, not edge.

**Degenerate loop (my DB finding):** `research_backlog` produced **2,478 rows/30d — 2,475 with NULL symbol,
100% auto-'promoted'** (~225 junk rows/day). The dashboard's "Research staged: 3,540" is inflated by this
loop. Real research output: ticker_thesis_challenge 520 rows/124 symbols, momentum_catalyst 517/56,
youtube_discovery 44/19.

**Sector awareness: passive only.** `_f_sector()` = same-day sector-ETF-vs-SPY at 12% weight; **no VIX/regime
conditioning, no rotation detector, no sector caps in top-N**. YouTube discovery is **circular** (queries only
symbols already on the watchlist; `hermes_youtube_discovery.py:56`) and SearXNG-rank-driven (engagement bias →
growth/tech content). So: structural bias confirmed — but note the nuance: **Hermes' current top-50 ranked
watchlist is NOT tech-heavy** (Consumer Cyclical 15, Industrials 11, Tech 1 of joinable rows). The tech
dominance the operator sees comes from the **GO/decision layer and discovery narratives**, not hermes_rank.

**Influence: advisory-only, near-zero coupling.** `proposal_strategy_fit.py` and `scoring.py` contain **no
hermes references**; influence is limited to watchlist ordering, top-20 external-LLM review selection, and
RAG context for agents. Hermes is currently an *ornament* on the decision path.

**Recommendations (ranked):** (1) outcome-weighted calibration — feed closed-trade P&L into the per-factor
predictiveness job; (2) fix the NULL-symbol backlog loop (it's burning cycles and faking throughput);
(3) sector-diversity constraint on top-N rank (soft penalty above 25% single-sector); (4) VIX/regime-
conditioned weights; (5) non-circular discovery (let discovery propose NEW symbols, not re-research the
watchlist); (6) give Hermes a real (still-advisory) seat downstream: show hermes score + dissent on the
proposal card the way L2 pressure now is.

## D. Cross-system findings

**Complementary by design, unarbitrated in practice.** Three genuinely different sources (Finviz = quantitative
candidate flow; Trade AI = enrichment/decision; Hermes = research/context) — but:
- **No weighting/arbitration layer exists in execution.** The schema for one exists (`source_tier`,
  `screener_label`, credibility scores) and is unpopulated/dropped.
- **Signals don't cross-pollinate:** scoring ignores Hermes; Hermes ignores outcomes; proposals ignore both
  beyond gate mechanics. Three monologues, not a desk conversation.
- **Better signals can't get lost — they can't even be identified:** without attribution, a high-hit-rate
  list and a noise list look identical.
- Verdict: today it behaves as a **pipeline that aggregates ideas with strong safety control but weak
  intelligence control**. The safety half of a trade desk is built; the prioritization half is schema-only.

## E. Highest-impact fixes (ranked)

| # | Fix | Effort | Impact |
|---|---|---|---|
| 1 | **Screener attribution end-to-end** (orchestrator INSERT line 631 → trade_ai_scans.screener_label → incubator → proposals) | ~1h | Unlocks every per-list question incl. "is momentum scout worth it"; prerequisite for pruning |
| 2 | **Outcome feedback into both scorers** (Trade AI scar-factor from live WR; Hermes calibration on realized P&L) | ~1d | Turns both engines from reactive to adaptive — the single biggest intelligence upgrade |
| 3 | **Kill the NULL-symbol backlog loop** (hermes librarian) | ~1-2h | Stops ~225 junk rows/day + restores honest throughput metrics |
| 4 | **Sector metadata backfill + propagation** (44% of scans NULL; reuse the fallback map + Schwab fundamentals now wired) | ~2-3h | Prerequisite for any sector-aware logic anywhere |
| 5 | **Sector-diversity + regime conditioning** (top-N caps in Hermes; smooth sector pillar in scoring; VIX-conditioned weights) | ~1d | Directly addresses the rotation/diversification concern |
| 6 | **Surface Hermes on the decision path (advisory)** — hermes score/dissent chip on proposal cards (pattern proven today with the L2 chip) | ~1h | Makes the intelligence layer visible where decisions happen |
| 7 | Non-circular discovery (new-symbol lanes; channel-level credibility from outcomes) | ~1d | Diversifies the idea pool at its source |

**Unmeasurable today (explicit):** per-list signal counts and hit-rates (attribution dropped); per-channel
YouTube efficacy; what fraction of GO tech-tilt is catalyst-keyword bias vs market reality (needs #1+#4 first).


---

## Implementation status (same day, operator: "fix 1-4 now, investigate 5-6")

- **#1 Attribution ✓** (c4836c8e): orchestrator INSERT now writes screener_label + source_detail; incubator
  prefers screener_label. Per-list hit-rates measurable from the next run forward.
- **#2 Outcome feedback ✓** (dfa5f44a): scoring.py strategy-family scar from live 30d paper WR (bounded
  0.85-1.10, min n=5 — correctly neutral today); hermes calibration consumes realized-trade P&L pairs at 2x
  weight (advisory output unchanged; weekly-cron runtime note: pairing query is heavy).
- **#4 Sector ✓** (6d696ecf): insert-time self-heal from latest known sector + one-time backfill of 2,744
  rows (44% -> 33% empty; remainder = symbols never seen with a sector).
- **#5 Backlog loop: INVESTIGATED -> FIXED ✓** (dfa5f44a): loop purpose legitimate (stale-research
  housekeeping) but had no dedup and a per-invocation cap invoked repeatedly by the coordinator. Now dedups
  vs 14-day topic history + true daily cap; 2,474 junk rows archived (reversible); double-apply test inserts 0.
- **#6 Tech-tilt: EXPERIMENT RUN — verdict:** at matched RVOL>=3, Healthcare's GO lead (16.3%) is
  structurally justified (highest RVOL 87.7, 59% small float, big gaps). **Technology's is NOT** — 12.3% GO
  rate with the WEAKEST measurable inputs (RVOL 16.8, floats 371M, 28% sweet-price, gaps 8.9) vs Industrials
  9.6% with better inputs. The residual driver is the unstored catalyst-tier pillar (keyword/LLM impact tiers
  favor tech narratives). **Recommended next:** persist per-scan pillar breakdown (one column) to prove it
  conclusively, then sector-neutralize catalyst tiering (score impact by price-reaction, not topic keywords).
