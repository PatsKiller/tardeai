# Phase 181A: Paper Trade Closed-Loop Field Map

Status:      HISTORICAL
as_of:       2026-06-01T23:29:18-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY

## Full Loop Stages

```
trade opened → plan captured → stop/target captured → trade closed
→ journal complete → Hermes audit → backtest comparison
→ post-exit review → lesson queued → shadow score → future candidate lineage
```

## Field Map Per Stage

### Stage 1: Trade Opened
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| trade_id | paper_trades | id | PRESENT |
| symbol | paper_trades | symbol | PRESENT |
| strategy_id | paper_trades | strategy_id | PRESENT (100%) |
| entry_price | paper_trades | entry_price | PRESENT (100%) |
| entry_time | paper_trades | entry_time | PRESENT |
| shares | paper_trades | shares | PRESENT |
| dollar_size | paper_trades | dollar_size | PRESENT (100%) |
| broker_order_id | paper_trades | broker_order_id | 50% populated |
| proposal_id | paper_trades | proposal_id | 88% populated |

### Stage 2: Plan Captured
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| stop_loss | paper_trades | stop_loss | 96% populated |
| target_1 | paper_trades | target_1 | 96% populated |
| target_2 | paper_trades | target_2 | SPARSE |
| dollar_risk | paper_trades | dollar_risk | 96% populated |
| entry_reason | paper_trades | catalyst_at_entry | 54% populated |
| market_regime | paper_trades | market_regime | 88% populated |
| vix_at_entry | paper_trades | vix_at_entry | 88% populated |
| trade_plan_id | paper_trades | trade_plan_id | SPARSE |

### Stage 3: Trade Closed
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| exit_price | paper_trades | exit_price | 75% populated |
| exit_time | paper_trades | exit_time / closed_at | PRESENT |
| exit_reason | paper_trades | exit_reason | 100% populated |
| close_reason | paper_trades | close_reason | 38% populated |
| pnl | paper_trades | pnl | 75% populated |
| pnl_pct | paper_trades | pnl_pct | SPARSE |
| hold_time_min | paper_trades | hold_time_min | **8% — CRITICAL** |
| r_multiple | paper_trades | r_multiple | 67% populated |
| max_adverse_excursion | paper_trades | max_adverse_excursion | 62% |
| max_favorable_excursion | paper_trades | max_favorable_excursion | 62% |

### Stage 4: Journal Entry
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| thesis_outcome_id | trade_thesis_outcomes | id | 88% linked |
| thesis_result | trade_thesis_outcomes | thesis_result | PRESENT |
| thesis_followed | trade_thesis_outcomes | thesis_followed | PRESENT |
| actual_r | trade_thesis_outcomes | actual_r | PRESENT |

### Stage 5: Outcome Analytics
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| outcome_id | paper_trade_outcome_analytics | id | 67% linked |
| outcome_verdict | paper_trade_outcome_analytics | outcome_verdict | PRESENT |
| followed_plan | paper_trade_outcome_analytics | followed_plan | PRESENT |
| lessons | paper_trade_outcome_analytics | lessons (JSONB) | PRESENT |

### Stage 6: Hermes Audit
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| hermes_opinion_id | hermes_research_intelligence | id | **0% — MISSING** |
| related_trade_id | hermes_research_intelligence | related_trade_id | **0% linked** |
| hermes_confidence | hermes_research_intelligence | confidence_score | N/A |
| hermes_verdict | hermes_research_intelligence | summary | N/A |

### Stage 7: Backtest Comparison
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| backtest_quality | paper_trades | backtest_quality | **0% — MISSING** |
| strategy_backtest ref | strategy_backtest_trades | — | 8,998 rows but no linkage |
| backtest_win_rate | paper_performance_governance | win_rate | 161 rows |
| backtest_profit_factor | paper_performance_governance | profit_factor | PRESENT |

### Stage 8: Post-Exit Review
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| post_trade_analyzed | paper_trades | post_trade_analyzed | **17% — LOW** |
| paper_trade_analysis | paper_trade_analysis | — | 6 rows |
| multi_reviews | paper_trade_multi_reviews | — | 28 rows |

### Stage 9: Learning Queue
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| lesson_id | trade_lesson_memory | id | 10 total |
| lesson_category | trade_lesson_memory | lesson_category | PRESENT |
| strategy_id | trade_lesson_memory | strategy_id | PRESENT |
| review_status | trade_lesson_memory | operator_review_status | PRESENT |

### Stage 10: Shadow Score
| Field | Table | Column | Status |
|-------|-------|--------|--------|
| shadow_score | strategy_shadow_scores / files | — | 27 scored (file-based) |
| lineage ref | candidate_decision_lineage / files | — | File-based |

## Loop Completeness Summary

| Stage | Coverage | Status |
|-------|----------|--------|
| Trade opened | 100% | COMPLETE |
| Plan captured | ~90% | GOOD (catalyst gap) |
| Trade closed | ~70% | PARTIAL (hold_time, pnl gaps) |
| Journal (thesis) | 88% | GOOD |
| Outcome analytics | 67% | PARTIAL |
| Hermes audit | 0% | **MISSING** |
| Backtest comparison | 0% | **MISSING** |
| Post-exit review | 17% | **LOW** |
| Learning queue | ~42% (10/24) | PARTIAL |
| Shadow score | File-based | NOT DB-LINKED |

## Critical Broken Links

1. **hold_time_min**: 8% → Most close paths don't compute it
2. **Hermes audit**: 0% → No integration exists for paper trades
3. **Backtest comparison**: 0% → No paper-vs-backtest linkage
4. **Post-exit review**: 17% → Overnight LLM analysis inconsistent
5. **pnl/exit_price**: 75% → Some close paths don't set these
