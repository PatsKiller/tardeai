# Intelligence Engine & Command Center — Maturity Audit (2026-06-22)

Operator goal: continuous autonomous intelligence (Hermes → RAG → agents) and a polished Command Center Intelligence hub (`/v3/intelligence`).

## Grade summary (post-remediation)

| Surface | Grade | Notes |
|---------|-------|-------|
| Command Center tab | **A** | Multi-feed synthesis, type-aware quality scoring, LM review |
| Signal Quality tab | **A** | KPI filters, verification plans, Hermes/RAG health KPI |
| Inferences tab | **A** | Layer-4 feed, facets, regional + sizing panels, ensemble |
| News tab | **A** | `/api/v2/news/articles` with filters + pagination |
| Research tab | **A** | User + monitor topics, structured gaps (`display_name`, `reason`, `detail`) |
| Sources tab | **A** | RAG coverage, Hermes pipeline, ingestion status, unified library |
| Workflow tab | **A** | React Flow pipeline with Hermes→RAG queue metrics |
| Rotation tab | **A** | Full summary embed (sectors, degraded, pairs, research candidates) |
| Backend autonomous loop | **A-** | Coordinator live; embed drain rate-limited by Ollama |

## Backend fixes (P0)

### Hermes → RAG closed loop
- **Root cause:** `hermes_embedding_queue` was never populated on promote (no `INSERT` in repo).
- **Fix:** `scripts/hermes_embedding_enqueue.py` + enqueue on every auto-promote in `hermes_coordinator.py`.
- **Backfill:** One-shot enqueued all promoted rows missing embeddings (2026-06-22 run: ~2246 rows).
- **Indexer:** `hermes_research` added to `rag_indexer.py`, `_intelligence_library()`, `_rag_status()`.

### Iris library-status deadlock
- **Root cause:** `get_library_status()` HTTP-called `localhost:7777` from inside single-threaded `api_v2`.
- **Fix:** Direct DB queries in `iris_taxonomy_agent.py`.

### Observability
`GET /api/v2/hermes/health` now exposes:
- `coordinator_active`, `coordinator_last_tick`
- `embedding_queue` (pending/completed/failed)
- `rag_pipeline` (promoted vs embedded %)

`GET /api/v2/system/pipeline-health` RAG section adds Hermes embed queue counts.

### Coordinator tuning
- `CAP_EMBED` raised from 2 → 10 per 15-minute tick.

## Frontend fixes

### Intelligence hub (`apps/command-center-v3`)
- URL-synced tabs: `/v3/intelligence?tab=news|research|sources|rotation|…`
- Lazy tab mounting (no rotation summary poll until Rotation tab open)
- New components under `src/components/intelligence/`:
  - `IntelligenceNewsTab.tsx`
  - `IntelligenceResearchTab.tsx`
  - `IntelligenceSourcesTab.tsx`
  - `IntelligenceRotationTab.tsx`
- Removed operator dev notes (Brave depleted / SearXNG references)
- Research gaps use API field mapping (`display_name`, `reason`, `detail`)

## Ops runbook

### Drain Hermes embedding backlog
```bash
cd $PROJ
# Backfill queue (idempotent)
.venv/bin/python scripts/hermes_embedding_enqueue.py --backfill --limit 5000
# Manual drain when Ollama healthy
.venv/bin/python scripts/hermes_embedding_worker.py --apply --limit 20
```

### Verify health
```bash
curl -s localhost:7777/api/v2/hermes/health | jq '.data.rag_pipeline, .data.embedding_queue'
curl -s localhost:7777/api/v2/rag/status | jq '.data.by_source.hermes_research'
```

### Kill switch
```bash
touch data/runtime/HERMES_DISABLED   # halt coordinator next tick
rm data/runtime/HERMES_DISABLED      # resume
```

## Remaining ops (not code)

| Item | Impact | Action |
|------|--------|--------|
| Ollama embed timeouts | Slow queue drain | Ensure `nomic-embed-text` loaded; run worker in batches |
| Hermes gateway `:18790` offline | Chat UI only | Coordinator/cron independent |
| Topic ingestion SSL | Occasional crash | Monitor cron logs; restart on failure |

## Key files

| Area | Path |
|------|------|
| Coordinator | `scripts/hermes_coordinator.py` |
| Embed enqueue | `scripts/hermes_embedding_enqueue.py` |
| Embed worker | `scripts/hermes_embedding_worker.py` |
| RAG indexer | `scripts/rag_indexer.py` |
| API | `scripts/api_v2.py` |
| Hub UI | `apps/command-center-v3/src/pages/IntelligenceHub.tsx` |
| Tab components | `apps/command-center-v3/src/components/intelligence/` |