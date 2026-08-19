# Symbol Thesis ↔ Research Intelligence acquisition plane

**Status:** wired on PR #397 · `hermes_is_acquisition_source=false` · no second vector store · no universe crawl

## Contract

| Layer | Role |
|---|---|
| Symbol thesis (`symbol_<ticker>@vN`) | Structured versioned **belief** object |
| RAG (`content_embeddings` + governed tables) | **Evidence retrieval** layer |
| SearXNG / SEC / RSS / YouTube / FS / Finviz-yfinance-Alpaca-FRED | **Acquisition** plane (budgeted, gap-driven) |
| `rag_status` + `research_sources` | **Curation / admission** before embed |
| `rag_indexer.py` → `content_embeddings` | **Only** embed path (existing corpus) |
| Hermes / DeepSeek Flash | **Synthesis + challenge only** — never acquisition |

## Pipeline

1. Specific gap question  
2. RAG-first: supporting **and** contradictory queries via `rag_retrieval.get_rag_context`  
3. Structured corpus read (approved news, YT, SEC Form 4, registry)  
4. If insufficient → `SymbolThesisAcquisitionPlan` (capped SearXNG/SEC/RSS/YT/FS/structured)  
5. Catalog evidence (source / freshness / quality / provenance / polarity)  
6. Curate (`rag_status`, `research_sources`)  
7. Embed approved → existing `content_embeddings`  
8. Hermes/Flash synthesize → `reconcile_symbol_thesis`

## Live dry (read-only)

| Symbol | RAG support/counter | Gaps | Acquisition | Synthesis gate |
|---|---|---|---|---|
| SCHG | 8 / 8 | no_approved_primary_or_news | PLANNED (searx, sec, rss, yt, fs, structured) | BLOCKED_PENDING_ACQUISITION_AND_CURATION |
| CSCO | (retrieved) | no_approved_primary_or_news | PLANNED | BLOCKED_PENDING… |
| ANET | sufficient + primary | none | SKIP | READY_FOR_SYNTHESIS |

`hermes_is_acquisition_source=false` · `second_vector_store=false` · `universe_crawl=false`

## Modules

- `scripts/lib/symbol_thesis_evidence.py`
- `scripts/lib/symbol_thesis_acquisition.py`
- `scripts/lib/symbol_thesis_synthesis.py`
- `scripts/lib/symbol_thesis_research.py` (orchestrator; rewritten)
- API: `GET /api/v3/cio/thesis-ri-pipeline/{SYM}`

## Boundary

No merge/deploy. No production thesis backfill. No auto-embed of pending web hits. Acquisition execute / embed / LLM remain opt-in flags (default dry).
