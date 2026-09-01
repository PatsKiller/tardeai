# Phase 68A — Telegram Alert Taxonomy

Status:      HISTORICAL
as_of:       2026-06-01T11:52:54-04:00
Measured at: efcc51365 / not measured

| Alert Type | Severity | Description |
|-----------|----------|-------------|
| credential_expired | CRITICAL | Cookie/token invalid, ingestion blocked |
| ingestion_failed | DEGRADED | Screener/feed returned zero rows |
| agent_stale | DEGRADED | Agent output older than threshold |
| escalation_analyzed | INFO | LLM analyzed the issue |
| escalation_fixed | WATCH | LLM claims fixed (needs verification) |
| false_fixed | CRITICAL | "Fixed" but stale alert repeats |
| data_feed_degraded | DEGRADED | Partial ingestion, some sources down |
| model_execution_failed | DEGRADED | Ollama 500/timeout |
| queue_backlog | WATCH | Event queue growing without processing |
| source_discovery_failed | INFO | SearXNG query returned no results |
