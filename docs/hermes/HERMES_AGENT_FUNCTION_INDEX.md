# Hermes/TradeAI Agent → Function Index (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T12:50:46-04:00
Measured at: efcc51365 / not measured

Quick "who handles X" reference. All agents are advisory/staging-only; none touch broker/trading.

| Function | Owning agent | Script | Trigger |
|----------|--------------|--------|---------|
| **Plan/route what to research (new research ideas)** | Chief Hermes Coordinator | `hermes_coordinator.py` | cron */15 |
| **Generate thesis-challenge research ideas** | Autonomous Research Manager | `hermes_autonomous_loop.py` (loop ticker_challenger) | timer |
| **Find new data sources** | Source Discovery | `hermes_scheduled_source_discovery_dryrun.py` (via SearXNG) | timer |
| **Librarian: review/route/classify staged findings** | Hermes Librarian | `hermes_autonomous_librarian_backlog_loop.py` | hermes-librarian-backlog-loop.timer |
| **Taxonomy classification** | IRIS Taxonomy Agent (TradeAI) | `iris_taxonomy_agent.py` | tradeai-iris-taxonomy.timer |
| **Embedding curation (RAG candidates)** | Embedding Curator | `hermes_embedding_promotion_reviewer.py` | hermes-embedding-promotion-review.timer |
| **Promotion review (advisory)** | Promotion Review | `hermes_embedding_promotion_reviewer.py` | same timer |
| **Research backlog health** | Research Backlog Manager | `hermes_backlog_health_check.py` | hermes-backlog-health-check.timer |
| **Momentum/catalyst research** | Momentum Catalyst Researcher | `hermes_momentum_catalyst_researcher.py` | hermes-momentum-catalyst-morning.timer |
| **Advisory opinion caching** | Advisory Cache Worker | `hermes_advisory_cache_worker.py` | hermes-advisory-cache-worker.timer |
| **Strategy shadow scoring (learning)** | Shadow Scorer | `strategy_learning_shadow_scorer.py` | hermes-shadow-scorer.timer |
| **Internal deep research (designed)** | Hermes Deep Research — Local | gemma3:27b/overnight | BATCH_OVERNIGHT (design) |
| **External high-stakes / second-opinion / market-narrative (designed)** | Claude / ChatGPT / Grok researchers | external lanes | manual/escalation (design) |

## Direct answers
- **New research ideas:** Coordinator plans/routes; Autonomous Research Manager generates thesis challenges.
- **New data sources:** Source Discovery (SearXNG-based).
- **Librarian + taxonomy:** Hermes Librarian routes/classifies findings; the dedicated **taxonomy** classifier
  is the **IRIS Taxonomy Agent** (`iris_taxonomy_agent.py`).
