# Closed-Loop Learning Certification Audit (2026-06-05)

Status:      HISTORICAL
as_of:       2026-06-05T17:40:32-04:00
Measured at: efcc51365 / not measured

Read-only evidence audit of the chain: signal → proposal → paper execution → monitoring → exit →
journal → Hermes reflection → backtest comparison → lesson → shadow score → future-candidate lineage.
No trading behaviour, GO/WAIT, strategy YAML, proposals, orders, or broker state were changed (SELECT-only).

## Closed-loop status: **PARTIAL** (forward execution chain real; learning/reflection loop NOT closed)

The forward path (signal→proposal→paper-trade→exit→post-exit review) is partially wired. The learning
back-half — the actual point of "closed-loop learning" — is effectively open: Hermes 0% trade-linked,
backtest-vs-outcome comparison weak, lessons not applied to scoring, shadow scores file-based, candidate
lineage absent, news not outcome-linked, loop-closure flag set on 5% of chains.

## Per-stage coverage matrix (denominator: 43 closed paper trades / 172 proposals)
| Stage | Link | Coverage | Status |
|-------|------|----------|--------|
| Signal → Proposal | proposal.source_signal_id | 44% (75/172) | PARTIAL |
| | proposal.source_strategy_card_id | 0% | BROKEN |
| Proposal → Paper trade | paper_trades.proposal_id | 84% (43/51) | OK (fwd) |
| | proposal.paper_trade_id (back-link) | 16% | BROKEN back-ptr |
| Signal lineage at execution | paper_trades.signal_id / source_signal_id | **0%** | BROKEN |
| Execution → Monitoring | paper_trades.post_trade_analyzed | 100% | OK |
| Exit verdict | paper_trades.outcome_verdict | 75% | OK |
| Post-exit review | paper_trade_multi_reviews | 70% | PARTIAL |
| | paper_trade_lifecycle_outcomes | 53% | PARTIAL |
| | trade_thesis_outcomes / outcome_analytics | 37% | PARTIAL |
| Journal | journal_trade_reviews ↔ paper trades | ~0% (keyed to Schwab trades) | BROKEN |
| Hermes reflection | hermes_research_intelligence.related_trade_id | **0% (0/1170)** | FAIL |
| | hermes_v_trade_reflection_context | symbol-only (no trade_id) | FAIL |
| | hermes_promotion_audit | no trade-link column | FAIL |
| Backtest comparison | closed trade ↔ backtest snapshot (via proposal) | 40% (17/43) | PARTIAL |
| | post-exit outcome vs backtest cohort | none (trade_backtest_results keyed to Schwab) | FAIL |
| | paper_trades.backtest_quality | 0% | BROKEN |
| Lesson capture | trade_lesson_memory ↔ paper_trade.id | 23% (10/43) | PARTIAL |
| Lesson → production scoring | scoring.py / signal_fusion.py reference lessons | **none** | FAIL |
| Loop closure | proposal_outcome_chain.outcome_fed_back=true | 5% (8/167) | FAIL |
| Shadow score | DB (agent_weight_shadow_proposals) | 0 rows (file-based: data/learning/shadow_scores) | FAIL (not DB-linked) |
| Future-candidate lineage | candidate_discovery_events / discovery_candidates_history | 0 rows | FAIL |
| News correlation | news_articles → trade/proposal FK | none (symbol+date only) | FAIL |

## Broken joins / missing lineage IDs
1. **paper_trades.signal_id & source_signal_id = 0%** — signal identity is lost at execution; outcomes can't
   be attributed back to the originating signal.
2. **hermes_research_intelligence.related_trade_id / related_proposal_id = 0%** (1170 rows) — all Hermes
   research/reflection is orphaned from trades and proposals.
3. **Two disconnected keyspaces**: journal_trade_reviews + trade_backtest_results use `SYMBOL:account:date`
   keys (the imported **Schwab** ledger); paper_trades use a numeric `id`. Only 3 symbols overlap → the
   journal/backtest review system does not cover the paper-trade learning loop.
4. **proposal.paper_trade_id = 16%** while paper_trades.proposal_id = 84% — the forward link is fine but
   the reverse pointer (and proposal.outcome_* at 6%) is under-populated.
5. **proposal_outcome_chain.outcome_fed_back = 5%** — the explicit "fed back into learning" flag is rarely set.

## 5 failed/missing lineage examples
- pt#51 MRVL: proposal_id=NULL, source_signal_id=NULL, verdict=PHANTOM, hermes/lesson/backtest/journal=0.
- pt#48 ANY: proposal_id=NULL, signal=NULL, PHANTOM.
- pt#55 INFU: proposal=183 present but source_signal_id=NULL; hermes/lesson/journal/backtest=0.
- hermes_research_intelligence: 1170 rows, related_trade_id NULL on 100% → research never tied to a trade.
- journal_trade_reviews row `PFE:schwab_rollover_ira:2026-04-21` — a Schwab import review, not a paper trade.

## Data-quality blockers
- Many recent paper trades are `PHANTOM` (proposal recorded but no real fill) → no outcome to learn from.
- Signal IDs not persisted onto paper_trades; strategy_card link 0%.
- Hermes context is built by symbol/RAG, never stamped with the related trade/proposal id.
- Backtest results for the live/imported book are not joined to paper-trade outcomes.

## News / backtest correlation status
- **News:** correlation only possible by symbol+date; no structured news→trade/outcome link. Entry/exit
  catalyst is free-text (`catalyst_at_entry`, 53%), not joined to `news_articles`.
- **Backtest:** proposal-time snapshot exists for 40% of closed trades; there is **no** post-exit comparison
  of realized outcome vs the matched backtest cohort.

## Learning-to-scoring status
Lessons are **captured** (trade_lesson_memory, strategy_lesson_rollup, learning_evidence) and surfaced in
agent/journal **prompt context**, but the production scoring path (`scoring.py`, `signal_fusion.py`,
`scalp_outcome_scorer.py`) contains **no reference** to lessons or lesson rollups → lessons are NOT applied
to production scoring. Shadow scoring is **file-based** (`data/learning/shadow_scores`, `marl_shadow_logger`,
`strategy_learning_shadow_scorer`), not persisted to a DB table joined to future candidates.

## Safety proof (no live trading / no strategy mutation)
- ALPACA_MODE=paper · LLM_DISABLE_LIVE_EXECUTION=true · paper_validation_policy.live_trading_allowed=False.
- Audit executed SELECT queries only — no INSERT/UPDATE/DELETE, no proposal/order/broker writes, no GO/WAIT
  or strategy-YAML edits. (The `config/strategies/*.yaml` shown in git status are the unrelated daily
  `performance_context.last_updated` timestamp bumps from a runtime job, not this audit.)

## Safe next implementation plan (read/write-additive, no trading-behaviour change)
1. **Stamp lineage IDs at execution** (highest value): persist `source_signal_id`/`signal_id` and
   `source_strategy_card_id` onto paper_trades at submit; backfill proposal.paper_trade_id / outcome_trade_id.
2. **Link Hermes reflection by ID**: when Hermes writes trade-reflection research, set related_trade_id /
   related_proposal_id; backfill from symbol+window where unambiguous.
3. **Unify the keyspace**: add paper_trade_id to journal_trade_reviews + trade_backtest_results (or a
   `trade_key` on paper_trades) so journal/backtest cover the paper loop, not only the Schwab import.
4. **Post-exit backtest comparison**: on close, join the realized outcome to its proposal_backtest_snapshot
   and record edge-realized vs edge-expected (new column / table).
5. **Persist shadow scores to DB** (e.g. `agent_weight_shadow_proposals` / a candidate_shadow_scores table)
   keyed to the candidate, and set proposal_outcome_chain.outcome_fed_back when a lesson/score is derived.
6. **Lessons → scoring (shadow first)**: feed lesson rollups into a shadow score channel, compare vs
   production, and only graft after evidence — never silently alter GO/WAIT.
All steps are additive lineage/learning plumbing; none change strategy scoring, GO/WAIT, or enable live.
