# Safety Snapshot — ATM Lifecycle v1 Evidence Package

| Field | Value |
|-------|-------|
| **Git Branch** | main |
| **Git Commit** | 915876ff12f0988acccf1553f44dd50b0a75dd54 |
| **Timestamp** | 2026-05-26T19:47:17Z |
| **ALPACA_MODE** | paper |
| **LLM_DISABLE_LIVE_EXECUTION** | true |
| **manual_kill_switch_only** | true |
| **min_classifier_health** | 0.0 |
| **Portfolio Server PID** | 302082
303387 |
| **Open Paper Positions** | 29 |
| **Paper Proposals Today** | 2 |
| **ATM Decisions Today** | 1 |
| **safe_flock Events (1h)** | 38 |

## Open Positions

 33 | CMCSA  | dividend_growth_compounder |    120 |       24.97 |     23.61 | ALPACA_PAPER
 32 | CMCSA  | dividend_growth_compounder |    120 |       24.85 |     23.61 | TOS_PAPER
 31 | AGNC   | reit_income                |    293 |       10.22 |      9.71 | ALPACA_PAPER
 30 | AGNC   | reit_income                |    293 |       10.22 |      9.71 | TOS_PAPER
 28 | NWG    | dividend_growth_compounder |    189 |       15.84 |     15.05 | TOS_PAPER
 27 | ASPN   | swing_trade                |    553 |        5.52 |      5.15 | ALPACA_PAPER
 26 | ASPN   | swing_trade                |    553 |        5.42 |      5.15 | TOS_PAPER
 24 | FLYW   | dividend_growth_compounder |    171 |       16.29 |     15.48 | ALPACA_PAPER
 23 | GCTS   | momentum_scalp             |   1875 |        1.49 |           | ALPACA_PAPER
 22 | GCTS   | momentum_scalp             |   1875 |        1.49 |      1.42 | ALPACA_PAPER
 21 | INFU   | earnings_catalyst          |    357 |        8.61 |      7.97 | ALPACA_PAPER
 20 | GCTS   | momentum_scalp             |   1875 |        1.49 |      1.42 | ALPACA_PAPER
 19 | FLYW   | momentum_scalp             |    171 |       16.75 |           | ALPACA_PAPER
 18 | FLYW   | swing_breakout             |    171 |       17.51 |     16.63 | ALPACA_PAPER
 17 | FLYW   | swing_breakout             |    171 |       17.51 |     16.63 | TOS_PAPER
 16 | BLBD   | earnings_catalyst          |     37 |       68.48 |     76.23 | ALPACA_PAPER
 15 | BLBD   | earnings_catalyst          |     37 |       80.24 |     76.23 | TOS_PAPER
 12 | FLYW   | swing_trade                |    171 |       16.74 |     16.63 | ALPACA_PAPER
 11 | FLYW   | swing_trade                |    171 |       17.51 |     16.63 | ALPACA_PAPER
 10 | FLYW   | swing_trade                |    171 |       17.51 |     16.63 | ALPACA_PAPER


## Latest System Health Events

 news_ingestion              | ESCALATION_DEDUPED | CRITICAL | 2026-05-26 15:45:01.640886-04
 finviz_screener_runner      | ESCALATION_DEDUPED | CRITICAL | 2026-05-26 15:45:01.63311-04
 finviz_screener_runner      | RETRY_EXHAUSTED    | CRITICAL | 2026-05-26 15:45:01.630269-04
 incubator_proposal_promoter | ESCALATION_DEDUPED | CRITICAL | 2026-05-26 15:45:01.624641-04
 incubator_proposal_promoter | RETRY_EXHAUSTED    | CRITICAL | 2026-05-26 15:45:01.621744-04
 trade_ai_orchestrator       | ESCALATION_DEDUPED | CRITICAL | 2026-05-26 15:45:01.612515-04
 trade_ai_orchestrator       | RETRY_EXHAUSTED    | CRITICAL | 2026-05-26 15:45:01.607036-04
 news_ingestion              | ESCALATION_DEDUPED | CRITICAL | 2026-05-26 15:40:01.291852-04
 finviz_screener_runner      | ESCALATION_DEDUPED | CRITICAL | 2026-05-26 15:40:01.28711-04
 finviz_screener_runner      | RETRY_EXHAUSTED    | CRITICAL | 2026-05-26 15:40:01.284712-04


## Safety Confirmation

- Live trading: BLOCKED (ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true)
- ATM mode: NOT CHANGED
- Orders placed: NONE
- This is an export-only task
