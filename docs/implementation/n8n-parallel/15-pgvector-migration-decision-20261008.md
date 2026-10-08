# pgvector migration of `content_embeddings` — decision packet (2026-10-08)

Phase 2 item "pgvector (Trade AI side)" from `14-execution-week-20261008.md`. This packet measures the table, ships the tooling (`scripts/migrate_content_embeddings_pgvector.py`, `scripts/lib/embedding_reader.py`) and states what the operator must approve. **Nothing on the production database changed**: every number below is a read-only measurement, the plan mode prints DDL it did not run, and the apply mode refused (`not_authorized`, then `disk_headroom`).

## Measurement (read-only, 2026-10-08 01:50Z)

| fact | value |
|---|---|
| rows | 1,308,244 (oldest 2026-07-09; latest 2026-10-07 20:47 ET) |
| total size | 12.37 GB — heap 230 MB, **TOAST 11.81 GB** (the jsonb arrays), indexes 156 MB |
| embedding | jsonb array, all `nomic-embed-text`, **768 dimensions on every row** (sample 1,000/1,000; `embedding_dim` = 768 on all rows); avg 7,150 bytes per value; 0 NULLs |
| write rate | ~16,900 rows/day over the last 14 days (72 % `fused_signal`, then news, cio_decision, social_post, hermes_research) |
| readers | `scripts/rag_retrieval.py` (≤200 candidates by title/source, Python cosine), `hybrid_rag_context_adapter.py`, `hybrid_rag_retrieval_pilot.py`, `multi_tier_trade_reviewer.py`, `agent_curation_hooks.py`, `telegram_command_handler.py`, `api_v2.py` corpus counters (`/api/v2/...` RAG health: `corpus_total`, `corpus_7d`, latest model); writers: `rag_indexer.py`, `hermes_embedding_enqueue.py`/worker, `ingest_canon_source.py`, `transcript_slow_processor.py` |
| extension | `vector` **0.8.6** installed on PostgreSQL 17.11; already used by `intelligence.embedding` (`vec` column, `<=>`) — this table never adopted it |
| disk | `/` 468 GB, used 377 GB, **free 67 GB = 14.3 %** (`SHOW data_directory` not permitted to the app role; the DB lives on `/`) |

## Plan (what `--apply` would run, in this order)

```sql
ALTER TABLE content_embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector(768);
-- backfill, keyset batches of N (resumable: WHERE embedding_vec IS NULL AND id > last_id ORDER BY id LIMIT N),
-- each row cast from its jsonb array; rows whose array length ≠ 768 are skipped, never guessed
CREATE INDEX CONCURRENTLY IF NOT EXISTS content_embeddings_embedding_vec_hnsw
  ON content_embeddings USING hnsw (embedding_vec vector_cosine_ops);
```

| estimate | value | basis |
|---|---|---|
| vector column | 4.03 GB | 1,308,244 × (768 × 4 B + 8 B) |
| HNSW index | ~5.4 GB | 1.35 × vectors (pgvector HNSW m=16 on 768-d, observed range 1.2–1.5×) |
| **peak extra during migration** | **~9.5 GB** | column + index while jsonb still exists |
| after the jsonb column is dropped (separate operator decision) | **−2.3 GB net** vs today | 9.5 GB − 11.8 GB TOAST |
| backfill time | ~9 min | 2,500 rows/s keyset UPDATE (TOAST reads dominate) |
| index build | ~25 min, CONCURRENTLY | ~900 rows/s |
| ongoing | +52 MB/day column+index at 16,900 rows/day | — |

## Guards (every write path, typed refusals, exit 2)

`--apply` **and** `TRADEAI_PGVECTOR_MIGRATION_AUTHORIZED=1`; `vector` extension present; one dimension across all rows; disk free ≥ `TRADEAI_PGVECTOR_MIN_FREE_PCT` (default **25 %**). Today the disk guard refuses: 14.3 % free. The migration needs ~9.5 GB of the 67 GB free, so it fits in absolute terms; the 25 % floor is the platform's own rule (the host has run at 84–85 % for weeks). Options: free disk first (the 11.8 GB TOAST is the prize, but only after the dual-read period), or the operator lowers the floor explicitly for this run (`TRADEAI_PGVECTOR_MIN_FREE_PCT=12`), which the receipt records.

## Reader switch

`scripts/lib/embedding_reader.py` owns the candidate SQL. `TRADEAI_EMBEDDINGS_BACKEND=jsonb` (default) is byte-for-byte the SQL that lived in `rag_retrieval.py`; `pgvector` lets Postgres rank by `embedding_vec <=> query` (cosine) over the same predicate and returns `cosine_sim`, so the recency and source boosts apply unchanged. Cutover = one env flip in the rendered env + restart of the importing units; rollback = unset the flag. `--cutover-plan` prints the sequence; dual-read ≥ 7 days; `rag_indexer.py` keeps writing jsonb until a separate PR changes the writer.

## Rollback

`DROP INDEX CONCURRENTLY content_embeddings_embedding_vec_hnsw; ALTER TABLE content_embeddings DROP COLUMN embedding_vec;` — jsonb is never touched by this tooling, so the readers' default path is unaffected at every step.

## What the operator must approve

1. The apply itself (db-write grant naming `content_embeddings`), with the disk decision above.
2. The maintenance window: ~35 min total; backfill batches commit every 2,000 rows and `CREATE INDEX CONCURRENTLY` does not block writers, but the HNSW build competes for I/O with the 16:05–17:35 after-close pipelines — run it after 18:00 ET or before 05:30 ET.
3. Later, separately: switch the writer and drop the jsonb column (that is what clears the `SIZE_BUDGET` hygiene finding: 24.4 GB → ~22 GB database, and `content_embeddings` 12.4 GB → ~9.5 GB; the table budget finding needs the budget raised or the `fused_signal` rows given a retention row — 72 % of the table).

## Verification after apply

`scripts/migrate_content_embeddings_pgvector.py --verify`: samples rows and compares jsonb vs vector element-wise (float4 storage → ≤1e-7 diffs), counts NULL vectors (must be 0 after the backfill), checks `pg_index.indisvalid` for the HNSW index. Then `tests/test_pgvector_migration_plan_20261008.py` stays green and the hygiene report on the next night shows the new sizes.
