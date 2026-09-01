# Phase 209G — TradeAI Enhancement Workflow Matrix (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:29:04-04:00
Measured at: efcc51365 / not measured

| Workflow | Owner | Trigger | Profile/Model | Writes to | v3 page | Safety | Health |
|----------|-------|---------|---------------|-----------|---------|--------|--------|
| Source discovery | hermes_scheduled_source_discovery_dryrun.py | timer | Ollama gemma3 | hermes_research_intelligence | /v3/hermes | staging only | success |
| Ticker thesis challenge | hermes_autonomous_loop.py | timer | Ollama gemma3 | hermes_research_intelligence | /v3/hermes | staging only | success |
| Librarian backlog | hermes_autonomous_librarian_backlog_loop.py | timer | Ollama | hermes_research_intelligence (status) | /v3/hermes | staging only | success |
| Embedding curation | hermes_embedding_promotion_reviewer.py | timer | Ollama/embed | hermes_embedding_queue (gated) | /v3/hermes | gated | success |
| Promotion review | hermes_embedding_promotion_reviewer.py | timer | Ollama | hermes_promotion_audit (advisory) | /v3/hermes | advisory | success |
| Advisory cache | hermes_advisory_cache_worker.py | timer | n/a | advisory cache | Intelligence/Hermes | read-cache | success |
| Self-learning overview | api endpoint /hermes/self-learning-overview | API | n/a | none (read) | /v3/hermes | read-only | live |
| Dual-opinion advisory | /hermes/dual-opinion | API | n/a | advisory choices | dual-opinion pages | advisory | live |
| Proposal sandbox advisory | /hermes/proposal-sandbox | API | n/a | ~/.hermes drafts (read) | Hermes | read-only | live |
| Journal/backtest learning | trade_close_llm_analyzer + backtest cron | cron | Ollama gemma3 | trade_llm_reviews | Journal/Backtesting | advisory | health-gated |
| Profit protection advisory | hermes_profit_protection_check.py | (script) | Ollama | hermes_alerts/advisory | Hermes/Risk | advisory | n/a |
| Momentum catalyst morning | hermes_momentum_catalyst_researcher.py | timer | Ollama | research/catalyst JSONL | Intelligence | research | success |
| High-LLM escalation | hermes_high_llm_enqueue.py | (enqueue) | queue | llm queue | Queue Tower | gated | live |
| SIEM alert normalization | siem_to_hermes_backlog.py / siem | cron | n/a | alert_events/backlog | SIEM | read/normalize | live |

All enhancement writes land in Hermes staging / advisory / review tables — never core trading. Operator
action: review in the listed v3 pages; nothing auto-executes against the broker.
