# LLM Backtesting Source of Truth

## Inputs
| Source | Table/Endpoint |
|--------|---------------|
| Paper trade | paper_trades |
| Lifecycle trace | lifecycle_trace + lifecycle_trace_events |
| Proposal | paper_trade_proposals |
| Execution quality | paper_execution_quality |
| Stop-change audit | lifecycle_events stage=stop_change |
| Journal | /api/v2/automated-journal |
| Backtest results | backtest tables (if linked) |
| Missed proposals | paper_trade_proposals (no linked trade) |
| Market data | local price cache |

## Outputs
| Output | Proposed Table |
|--------|---------------|
| Close analysis | trade_llm_reviews (stage=close_analysis) |
| Delayed review | trade_llm_reviews (stage=delayed_review) |
| Monthly meta | monthly_llm_meta_reviews |
| Strategy flags | trade_llm_reviews.lessons |
| Quality warnings | trade_llm_reviews.data_quality_gaps |
