# Pipeline Truth Audit  2026-05-20

**Summary:** 13/29 nominal, 5 waiting. Issues: 6 not started, 5 stale.

| Metric | Count |
|--------|-------|
| Total stages | 29 |
| Completed today | 13 |
| Waiting for schedule | 5 |
| Not started today | 6 |
| Stale | 5 |
| No data produced | 0 |
| Cron entries | 130 |


## Data Collection
| Stage | Status | Last Run | Data Today |
|-------|--------|----------|------------|
| Market Regime Snapshot | STALE | 2026-05-11T07:45:01 | n/a |
| Finviz Screener Runner | NOMINAL | never | 7 |
| News Ingestion | NOT_STARTED_TODAY | never | n/a |
| Indicator Cache Refresh | NOMINAL | never | 196 |
| SEC Data Ingest | NOMINAL | never | 424 |

## Enrichment
| Stage | Status | Last Run | Data Today |
|-------|--------|----------|------------|
| Finviz 5-View Enrichment | NOT_STARTED_TODAY | never | n/a |
| Catalyst Enrichment (7 sources) | NOT_STARTED_TODAY | never | 0 |
| Price DB Sync | NOMINAL | never | 135544 |
| RAG Indexer | NOMINAL | never | 16314 |

## Scoring
| Stage | Status | Last Run | Data Today |
|-------|--------|----------|------------|
| Trade AI Orchestrator (55-pt) | NOMINAL | never | 7 |
| Multi-Strategy Classifier | NOMINAL | never | 7639 |

## Intelligence
| Stage | Status | Last Run | Data Today |
|-------|--------|----------|------------|
| CIO Decision Engine | NOMINAL | never | 2 |
| Agent Context Refresh | NOT_STARTED_TODAY | never | 0 |
| Strategy Rotation Signals | STALE | 2026-05-11T07:45:01 | 0 |
| Topic Curator | NOMINAL | never | 17 |
| Pipeline Watchdog | STALE | 2026-05-09T17:11:26 | n/a |

## Proposal Pipeline
| Stage | Status | Last Run | Data Today |
|-------|--------|----------|------------|
| Daily Incubator Refresh | NOT_STARTED_TODAY | never | 0 |
| Incubator Proposal Promoter | NOMINAL | never | 1 |
| Proposal Enrichment Loop | NOMINAL | never | 1 |

## Execution
| Stage | Status | Last Run | Data Today |
|-------|--------|----------|------------|
| Risk Gate | NOMINAL | never | 12 |
| Live Trading Gate (paper mode) | NOT_STARTED_TODAY | never | n/a |
| Execution Quality Analyzer | NOMINAL | never | 2 |
| Paper Execution Revalidation | STALE | 2026-05-09T17:11:24 | 36 |
| Execution Readiness Check | STALE | 2026-05-09T17:11:25 | 318 |

## Overnight
| Stage | Status | Last Run | Data Today |
|-------|--------|----------|------------|
| Overnight Batch | WAITING_FOR_SCHEDULE | never | 1414 |
| Agent Outcome Scorer | WAITING_FOR_SCHEDULE | never | 3 |
| Generate System Facts | WAITING_FOR_SCHEDULE | 2026-05-11T07:15:01 | 50 |
| Ingestion Learning Analysis | WAITING_FOR_SCHEDULE | 2026-05-11T07:45:01 | 21 |
| Trade Learning Analysis | WAITING_FOR_SCHEDULE | 2026-05-11T07:45:01 | 10 |