# Learning Loop Audit — Pre-Session 28

**Date:** 2026-05-09

## Existing Learning Components

| Component | Table | Rows | Notes |
|-----------|-------|------|-------|
| Agent calibration | agent_calibration | 3 | Minimal data |
| Agent outcomes | agent_recommendation_outcomes | 1 | Single scored outcome |
| Agent feedback | agent_feedback_log | 5 | Manual feedback entries |
| Audit log | audit_log | 473 | System audit trail |
| Paper trades | paper_trades | 4 (3 closed) | Very low sample |
| Proposals | paper_trade_proposals | 43 | Decent funnel data |
| Scans | trade_ai_scans | 608 | Source quality data |
| Watchlist results | watchlist_agent_results | 4,148 | Good agent data |
| Config docs | config_documents | 38 | Config management exists |
| Pipeline runs | pipeline_runs | 6 | Pipeline tracking |
| Source health | data_source_health | 13 | Source monitoring |
| News articles | news_articles | 2,787 | Ingestion quality data |
| Topics | topic_monitor | 17 | Topic tracking |

## Gaps Identified

1. No formal learning governance tables
2. No hypothesis tracking
3. No experiment framework
4. No config change proposal flow
5. No source learning scores
6. No strategy learning scores
7. No agent calibration scores
8. No rollback tracking
9. No sample-size enforcement

## Risk of Overfitting

With only 3 closed paper trades, ANY strategy-level conclusion is unreliable. The system must enforce minimum sample sizes before recommending changes.

## Minimum Sample Size Recommendations

- Trade execution: 30 closed trades for insights, 100+ for promotion
- Ingestion sources: 50 signals for insights, 250+ for weight changes
- Agent calibration: 25 scored recommendations for insights, 100+ for weight changes
