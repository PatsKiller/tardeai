# Hermes Phase 2A Session Closeout

**Date:** 2026-05-30
**Status:** CLOSED — embedding architecture pilot complete

---

## Objective

Prove that Hermes staged research can be embedded into Trade AI's existing content_embeddings table and discovered via RAG retrieval, using the same model and dimensions.

## Architecture

```
hermes_research_intelligence → hermes_embedding_queue → hermes_embedding_worker.py → content_embeddings
```

- Queue-based: research rows manually queued, worker processes them
- Same model: nomic-embed-text (768-dim)
- Same table: content_embeddings with source_type='hermes_research'
- Worker: `scripts/hermes_embedding_worker.py` (--dry-run default, --apply required)

## Pilot Results

| Item | Value |
|------|-------|
| Rows queued | 2 |
| Rows embedded | 2 |
| Symbols | FLYW (research id=1), INFU (research id=5) |
| content_embeddings ids | 26858, 26859 |
| Embedding model | nomic-embed-text |
| Embedding dim | 768 |
| RAG retrieval test | PASS |
| RAG score | 0.741 (competitive with Trade AI content) |

## Rollback

`docs/hermes/HERMES_PHASE2A_EMBEDDING_PILOT_ROLLBACK.sql`

## Commit & Sync

| Item | Value |
|------|-------|
| Commit | `f826715` |
| Drive sync | Done — 3 uploaded |

---

## Current Allowed State

- Hermes sidecar installed with headless browser, gateway :18790
- 7 staged research rows in hermes_research_intelligence
- 2 pilot embeddings in content_embeddings (source_type='hermes_research')
- Pilot embeddings discoverable via RAG retrieval
- Hardened prompt + validator (9/9 tests)
- Controlled ingestion + embedding scripts with --dry-run defaults

## Current Prohibited State

- No bulk Hermes embeddings
- No ongoing Hermes embedding worker/cron
- No autonomous research cron
- No dashboard Hermes Challenger
- No production promotion
- No broker/proposal/trade/journal mutation
- No external APIs/Grok/xAI

## WARNING

Only 2 Hermes rows are embedded. This is a capped pilot only:
- Bulk Hermes embeddings are NOT approved
- Dashboard display is NOT approved
- Production promotion is NOT approved
- Cron/autonomous embedding is NOT approved
- Each expansion requires separate operator approval

---

## Open Risks

| Risk | Severity |
|------|----------|
| Hermes embeddings could pollute RAG if low quality | LOW (pilot only, 2 rows) |
| Backup schedule gap | MEDIUM |
| Ollama GPU OOM at high num_ctx | LOW (capped at 8K for chat) |

---

## Next Recommended Gate

**Phase 2B — retrieval quality audit of pilot embeddings.**

Scope: verify the 2 Hermes embeddings are retrieved appropriately, test unrelated queries for over-matching, confirm no RAG pollution. No new embeddings, no dashboard, no promotion.
