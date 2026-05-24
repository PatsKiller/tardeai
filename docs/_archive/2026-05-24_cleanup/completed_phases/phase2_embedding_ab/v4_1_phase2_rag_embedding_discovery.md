# Phase 2A — RAG & Embedding Architecture Discovery

**Date:** 2026-05-14
**Status:** Discovery complete, no production changes

---

## 1. Current Production Embedding Model

- **Model:** nomic-embed-text (via Ollama at localhost:11434)
- **Dimensions:** 768
- **VRAM:** 0.54 GB resident
- **Disk:** 274 MB

## 2. Embedding Storage

- **Table:** `content_embeddings`
- **Total embeddings:** 14,784
- **Storage format:** jsonb (NOT pgvector native vector type)
- **No SQL-level vector index** — all similarity computed in Python

### Schema

| Column | Type | Purpose |
|--------|------|---------|
| id | bigint | PK |
| source_type | text | Content category (news, youtube, agent_result, etc.) |
| source_id | bigint | FK to source table |
| title | text | Content preview (max ~300 chars) |
| tfidf_terms | jsonb | TF-IDF term weights |
| top_keywords | text[] | Extracted keywords |
| created_at | timestamptz | Embedding creation time |
| embedding | jsonb | 768-dim float vector as JSON array |
| embedding_model | text | Always 'nomic-embed-text' currently |
| embedding_dim | integer | Always 768 currently |

### Unique Constraint
`(source_type, source_id)` — one embedding per document per source type.

### Indexes
- btree on (source_type, source_id) — unique + lookup
- GIN on top_keywords

## 3. Source Type Distribution

| Source Type | Count | Source Table |
|------------|-------|-------------|
| agent_result | 4,820 | watchlist_agent_results |
| news | 3,339 | news_articles |
| social_post | 2,245 | social_posts |
| fused_signal | 1,264 | fused_signals |
| decision_outcome | 860 | decision_outcomes |
| youtube | 818 | youtube_transcripts |
| agent_synthesis | 780 | watchlist_final_synthesis |
| cio_decision | 446 | cio_decisions |
| sec_form4 | 166 | sec_form4 |
| fred_series | 28 | fred_economic_series |
| trade_review | 11 | (multi_tier_trade_reviewer) |
| trade_outcome | 6 | (agent_curation_hooks) |
| brave_cache | 1 | (intel_query) |

## 4. Embedding Scripts

### Writers
| Script | Source Types | Method |
|--------|-------------|--------|
| `rag_indexer.py` | news, youtube, social_post, sec_form4, fred_series, agent_result, agent_synthesis, cio_decision, fused_signal, decision_outcome, research_finding | ON CONFLICT DO NOTHING |
| `multi_tier_trade_reviewer.py` | trade_review, weekly_review | ON CONFLICT DO UPDATE |
| `agent_curation_hooks.py` | trade_outcome | ON CONFLICT DO UPDATE |

### Readers
| Script | Usage |
|--------|-------|
| `rag_retrieval.py` | Core retrieval — embed query, fetch 200 candidates, Python cosine sim |
| `api_v2.py` | Serves RAG context via /api/v2/ endpoints |
| `alex_retirement_advisor.py` | agent_name="alex", limit=5 |
| `proposal_intelligence_analyzer.py` | strategy_focus, limit=5 |
| `proposal_agent_review.py` | strategy_focus, limit=5 |
| `social_scalp_scanner.py` | limit=3 |
| `telegram_command_handler.py` | limit=7 |

## 5. Retrieval Scoring Formula

```
rag_score = cosine_similarity(query_vec, doc_vec) × recency_decay × source_boost
```

### Recency Decay
```python
recency = max(0.5, 1.0 - (age_days // 30) * 0.10)
# Loses 10% per 30-day chunk, floors at 0.5×
```

### Source Boosts
| Source Type | Boost |
|------------|-------|
| trade_outcome | 1.35× |
| decision_outcome | 1.30× |
| research_finding | 1.25× |
| agent_synthesis | 1.20× |
| cio_decision | 1.15× |
| fused_signal | 1.10× |
| agent_result | 1.05× |
| All others | 1.0× |

## 6. Retrieval Query Pattern

```sql
SELECT id, source_type, source_id, title, embedding, created_at
FROM content_embeddings
WHERE title ILIKE '%{symbol}%'
  AND created_at > NOW() - INTERVAL '365 days'
ORDER BY created_at DESC LIMIT 200
```

Then Python-side: compute cosine_sim for each, apply recency + source boost, sort, return top N.

**Fallback:** If embedding fails, keyword-based SQL queries across news_articles, watchlist_agent_results, cio_decisions, content_entity_links, user_research_topics.

## 7. Cron Schedule for Indexing

RAG indexer is configured in pipeline_controller but may not have dedicated crontab entries. Proposed schedule (from crontab files):
- `50 6 * * 1-5` — news, fred, social, sec_form4 (2-hour lookback)
- `20 19 * * 1-5` — youtube (3-hour lookback)
- `30 2 * * *` — agent_result, agent_synthesis, cio_decision, fused_signal, decision_outcome (8-hour lookback)

## 8. Model Coupling Issue

**rag_retrieval.py hardcodes `EMBED_MODEL = "nomic-embed-text"` at line 17.** It does NOT read from `local_llm_config.py` despite the EMBEDDING process type being defined there. This means Phase 2 model switch requires updating rag_retrieval.py directly, not just config.

## 9. Parallel Index Feasibility

**YES — `embedding_model` column already exists.** The schema supports multiple models per document. However, the unique constraint `(source_type, source_id)` prevents two models for the same doc in the same table. Options:
- Separate table (safest)
- ALTER constraint to include embedding_model (requires migration)
- Temporary table (for A/B only)

## 10. Phase 2B Recommendation

Use a separate test table `content_embeddings_qwen3_test` with identical schema but embedding_dim=4096. Index 500-2000 recent documents. Compare retrieval quality side-by-side without touching production embeddings.

## 11. Documentation Drift Discovered

- `APPENDIX_E_SCRIPT_ROUTING_MATRIX.md` lists qwen3-embedding:8b as Phase 2 target — accurate
- `LLM_DATA_DICTIONARY.md` does not list content_embeddings table — gap, should be added in Phase 2D
- Cron entries for rag_indexer may not be in active crontab — verify before Phase 2B
