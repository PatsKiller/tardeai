# Critical design review — database health, RAG and embeddings, research retention, pruning, knowledge architecture

Principal-architect review requested 2026-10-07 after the n8n target-state blueprint. Evidence: a read-only census of the production Postgres (`trade_ai`, PG 17.11) at 11:38–11:50 ET and of the n8n lab Postgres (PG 16.15) at 11:40 ET, both on `ms01-openclaw`. Every number below was measured in those sessions unless marked **ESTIMATE** (planner or sample based) or **NOT VERIFIED** (not obtainable with the `trade_ai` role). Nothing was changed. The SQL used is kept in the session scratchpad and the census report is reproducible with the `trade_ai` role.

This review does not defend the blueprint. Where an earlier decision no longer holds, it says so.

---

## Area 1 — the "degraded" database

### What was actually degraded
The blueprint's "VERIFIED (degraded)" row describes the **n8n lab's Postgres container**, not production. Determination and metrics: the n8n 2.43 startup log prints "Postgres 16 is outside the supported range and receives compatibility support only. Upgrade to Postgres 17"; the application role `n8n` is a superuser (`pg_roles.rolsuper = t`); `data_checksums = off`; the n8n container has no healthcheck. Root cause: the lab was stood up on the `postgres:16.15-alpine` image with the official image's default superuser role. Risk if nothing is done: low. The lab is 18 MB (6.9 MB of table data, 132 of 157 tables empty, 417 executions at ≈3.7 KB each, about 0.5 GB per year at today's cadence). Remediation and target state: PG17 image on a fresh volume with a non-superuser `n8n_app` role, done via dump → new volume → restore (scripts exist and the first drill passed), 0.5 engineer-days plus one operator window. Expected improvement: supportability only; no performance change.

### The production database, measured for the first time
The word "degraded" should not be applied to production in the same sense. Production is **not broken**, it is **untuned, unpruned and unmeasured**. The evidence:

| Dimension | Measured | Verdict |
|---|---|---|
| Size | 23 GB; 749 tables (696 public + RLS-protected `intelligence.*`, `memory_r10_m2.*`, 36 `crash_*` test tables); 1,985 indexes = 3.5 GB | large for the host, dominated by one table |
| Largest table | `content_embeddings` **12 GB = 52 % of the database**, of which 11 GB is TOAST: 768-float vectors stored as JSON text (5.7–6.5 kB per row; the same vector as `vector(768)` is 3.1 kB) | the single biggest finding |
| Table growth | content_embeddings ≈23,000 rows/day (≈125 MB/day); scope_governor_audit ≈41,700/day; market_quotes ≈105,000 per trading day; schwab_stream ≈65,000/day; trade_ai_state ≈4,280 per run day | fast writers are the audit and quote tables, all with retention; the embedding table is the fast writer without a tight one |
| WAL | ≈12 GB/day (231.7 GB in 19 days); `wal_buffers_full` 4.6 M; checkpoints 5,473 timed / 18 requested | checkpointing is healthy; WAL volume is a symptom of the update-heavy tables below |
| Index health | 26 exact-duplicate index pairs ≈ **1 GB**; 564 never-scanned non-PK indexes ≈ **626 MB**; `hermes_score_history` carries 423 MB of indexes on 219 MB of data; 0 invalid indexes | immediate, safe savings |
| Bloat (ESTIMATE) | content_embeddings ≈3.5 GB (30 %), screener_symbol_membership 88 % (10.8 M updates on 67 k rows), trade_ai_state 37 %, scope_governor_audit 31 %, hermes_discovery_audit 30 %; analyst_consensus_history 46 % dead and never vacuumed; ticker_strategy_classifications 98 % dead | autovacuum at default thresholds cannot keep up with the update pattern |
| Query performance | no `pg_stat_statements`; `log_min_duration_statement = -1`; buffer hit ratio **65.5 %**; `temp_files` 84,920 / **726 GB** of temp spill since cluster init; `llm_consumption_log` read by 2.55 M sequential scans; `watchlist_items` 9.9 M seq scans | nobody can see slow queries, and the memory settings force spills |
| Connections | 20 of 100; two "idle in transaction" (one 19 h old from `motion_runtime.py`); 1,428 deadlocks lifetime; **41 % transaction rollback ratio** (23.9 M rollbacks) | the rollback ratio means a loop somewhere is failing or retrying constantly, NOT VERIFIED which |
| Vacuum strategy | autovacuum on, all defaults (scale 0.2, 3 workers, cost_delay 2 ms, naptime 60 s), three per-table overrides; `maintenance_work_mem` 64 MB | defaults sized for a 1 GB database |
| Retention | `db_retention.py` covers 85 policies and deleted 252,166 rows last night; **two schedulers** run it (cron from CURRENT at 04:10 and a Sunday systemd timer from the dev tree); no window at all for 25 tables including the unbounded growers | works where it exists; the gaps are the problem |
| Storage | root filesystem 85 % used, 70 GB free; data directory size NOT VERIFIED (permission) | the PG17 lab cutover and any index rebuild need headroom |
| Backup size | nightly `pg_dump` gz **2.8 GB**, 20.5 minutes, 1.8 GB peak RAM, local retention 1 copy; offsite weekly, last success 2026-10-01; `backup_verify` reports 1 FAIL because it checks a per-release path that does not exist | half of every backup is JSON vectors |
| Restore performance | **no restore drill receipt exists for the production database**; only the n8n lab has one | unknown restore time is the real DR risk |
| pgvector | 0.8.6 installed; the only `vector` columns are in RLS-protected schemas (`memory_r10_m2.memory_fact_version.embedding`, `intelligence.embedding.vec`); **no HNSW or IVFFlat index exists anywhere**; `intelligence.retrieval_receipt` has 0 rows ever | installed, not used for retrieval |
| Embedding storage impact | 11 GB TOAST, ≈3.5 GB bloat, daily deletes of ≈23 k rows at the 90-day edge keep the table churning | the storage cost is roughly 2× what the same data needs |

### Root cause
Three decisions, each reasonable alone: (1) embed everything that could ever be retrieved, including every `fused_signals` row (71.8 % of embeddings) even though 44 % of consecutive fused-signal rows are content-identical re-emits; (2) store vectors as `jsonb` because pgvector arrived later; (3) leave Postgres at distribution defaults (128 MB shared buffers, 4 MB work_mem) on a host that also runs Ollama, Docker and 480 cron jobs.

### Remediation options
A. Tune only (memory settings, statements extension, autovacuum per table): cheap, no data risk, buys headroom but not space.
B. Prune and dedupe (duplicate indexes, dead tables, retention windows, embedding TTLs): recovers ≈8–10 GB and halves the backup; needs maintenance windows for `VACUUM FULL`/`pg_repack` on the embedding table.
C. Restructure embeddings (`vector(768)` column + HNSW, stop embedding fused signals): halves the embedding footprint again and makes real ANN retrieval possible; only worth it if retrieval is redesigned (Area 2).
D. Leave as is: disk reaches the PG17 and backup limits within months at ≈125 MB/day of embedding growth plus WAL.

**Recommended approach:** A + B now (two weeks, ≈6 engineer-days plus two short maintenance windows), C only after Area 2's retrieval decision. Expected improvement: database 23 GB → ≈12 GB; backup 2.8 GB → ≈1.4 GB and ≈10 minutes; buffer hit ratio from 65 % toward 90 %; temp spills largely gone; nightly retention stable; a restore drill with a measured time.

---

## Area 2 — RAG and embeddings, re-examined

**What RAG means here today.** The only production retriever is `scripts/rag_retrieval.py:get_rag_context()`. It embeds the query with Ollama, then runs `SELECT … FROM content_embeddings WHERE title ILIKE '%SYMBOL%' AND created_at > now() - 365 days ORDER BY created_at DESC LIMIT 200` and computes cosine similarity **in Python over at most the 200 newest rows per symbol**. The database never does vector math. The corpus beyond the newest ≈200 rows per symbol is never scored. There are no retrieval receipts anywhere (`intelligence.retrieval_receipt` 0 rows, no logs), so retrieval frequency is **NOT VERIFIED**; the callers are known: watchlist agent jobs (870 jobs in 7 days), the nightly Aegis synthesis, the retirement advisor, the proposal analyzer, the symbol-thesis acquisition (weekdays 17:17), and on-demand desk commands.

1. **Why do we still need RAG?** The capability is real and used: agents get recent symbol context before they write. But what runs is "recent context lookup by title substring", not semantic retrieval. The 1.31 M stored vectors do not improve a 200-row recency scan. The decision to keep RAG as a capability stands; the decision to keep a 12 GB vector corpus for it does not.
2. **Do we need all stored embeddings?** No. 939,680 (72 %) embed `fused_signals`, of which ≈44 % are exact re-emits (sampled, ESTIMATE ≈400,000 duplicate vectors). Retrieval only ever touches the newest 200 per symbol. The useful corpus is news, Hermes research, CIO decisions and social posts under 90 days: ≈330,000 rows.
3. **How often are they used?** Writes are instrumented (≈23,000/day); reads are not. Order of magnitude from callers: hundreds of retrievals per day, each touching ≤200 rows. NOT VERIFIED beyond that, and that itself is a finding: add retrieval receipts before any further investment.
4. **What breaks if embeddings vanished tomorrow?** Agent context would lose semantic ranking of the newest 200 rows per symbol and fall back to recency only; the Hermes librarian promotion review and the Iris taxonomy agent would have nothing to tag; nothing financial, nothing operator-facing, no send and no decision gate depends on them. Degradation, not outage.
5. **Inactive share (ESTIMATE):** ≥70 % (all fused-signal vectors older than the newest 200 per symbol, plus duplicates) are never read.
6. **Storage cost of continuing as-is:** 12 GB now, ≈125 MB/day, 11 GB of it TOAST, 50 % of every backup, ≈3.5 GB bloat regrown continuously by the 90-day delete edge.
7. **Performance impact:** every nightly backup and retention pass drags 12 GB; TOAST reads for the 200-row scans are cheap, so query latency is not the cost; backup time, disk, WAL and vacuum pressure are.

**Verdict.** The architecture no longer serves its stated purpose. Recommendation: stop embedding `fused_signals` and `social_post` re-emits (dedupe on content hash before embedding); cut the TTL of fused-signal and social vectors to 30 days and keep 90 days for news, research and CIO decisions; add retrieval receipts (who asked, how many rows, top score) to `get_rag_context`; then decide, on four weeks of receipts, whether to move the remaining ≈300 k vectors to `vector(768)` with an HNSW index and real ANN search. Do not build the pgvector index before that evidence exists.

---

## Area 3 — financial research retention policy

Regulatory note: this is a private individual's platform, not a registered adviser. Tax and brokerage records (`trade_transactions`, `trade_closed`, tax lots, portfolio snapshots, dividend history) carry the IRS seven-year expectation; research and generated analysis carry no statutory retention. Where the operator has a personal compliance preference, the row says UNKNOWN.

| Category (tables) | Today | Value at 30 d | 90 d | 1 y | Regulatory | Historical / archival value | Classification | Recommended window |
|---|---|---|---|---|---|---|---|---|
| Analyst research (`analyst_consensus_history`, `analyst_*_history`) | 180 d policy; 46 % dead tuples, never vacuumed | High | Medium | Low (consensus drifts) | none | medium for backtests | KEEP HOT 180 d → ARCHIVE | 180 d hot, yearly parquet |
| Generated research (`hermes_external_research` 472 MB, 44 % > 90 d, 70 % repeated questions, 14,814 error rows) | **no window** | Medium | Low | None | none | low: questions repeat, answers age | SUMMARIZE THEN DELETE | 90 d hot; error/unavailable rows 14 d; summaries into `hermes_research_intelligence` |
| Research intelligence (`hermes_research_intelligence`, staged→archived→purged) | librarian 90/180 d | High | Medium | Low | none | the summary layer; keep | KEEP HOT | as is |
| SEC analysis (`sec_form4` 90 d, `sec_xbrl`, `sec_filing_documents`) | partial | High | High | Medium (filings are canonical, re-fetchable) | none | source is public; re-fetchable | KEEP HOT 180 d, DELETE after (re-fetch) | 180 d |
| Earnings analysis (`catalyst_events` 90 d, `decision_packets` 380 MB/20 k rows at 20 kB each, `decision_blueprints` 102 MB) | catalyst 90 d; packets and blueprints **no window** | High | Medium | Low | none | packets are regenerable from inputs | SUMMARIZE THEN DELETE (packets 90 d), KEEP blueprints 180 d | 90 / 180 d |
| News intelligence (`news_articles` 90 d, 94,801 of 125,567 `rag_status pending`; `document_mentions`) | 90 d | High | Low | None | none | none | DELETE at 90 d (already); stop embedding `pending` rows | 90 d |
| Watchlist research (`watch_directive_hits` 94 MB no window, `watch_decision_refresh_jobs` 65 MB, 79 % > 30 d) | none | High | Low | None | none | none | DELETE > 90 d (hits), > 30 d (jobs) | 90 / 30 d |
| Holdings research (`cio_decisions` 97,640 of which 94,166 `proposed`, 90 d) | 90 d | High | Medium | Low | none | outcomes matter, proposals do not | KEEP HOT 90 d; SUMMARIZE outcomes | 90 d |
| Thesis evolution (`symbol thesis`, `trade_lesson_memory` 288, `memory_fact_version` 3,969 RLS) | none, small | High | High | High (lineage) | none | this IS the historical value | KEEP HOT indefinitely (versioned, supersession) | forever |
| LLM artifacts (`llm_consumption_log` 88 MB no window, `llm_cost_reservations`, `inference_ensemble_jobs` 73 % expired) | none | High (cost audit) | Medium | Low | none (cost records: keep 1 y for own accounting) | yearly totals only | SUMMARIZE THEN DELETE | 180 d rows, monthly rollups forever |
| Research packets (`agent_recommendation_registry` 528 k rows, 43 % > 90 d, never vacuumed; `agent_calibration_events`) | none | High | Medium (calibration) | Low | none | calibration curves need history, rows do not | SUMMARIZE THEN DELETE | 180 d rows; calibration aggregates forever |
| Intermediate outputs (`scope_governor_audit` 30 d, `hermes_score_event_queue` 159 k no window, `hermes_embedding_queue` completed rows kept forever, `trade_integrity_audit` 143 MB no window, `health_agent_snapshots` 126 MB toast no window, `system_rollup_daily` 78 MB orphaned toast on 0 rows) | mixed | Medium | None | None | none | none | DELETE | 14–30 d |
| Prices and bars (`market_quotes` 90 d, `ticker_prices` 365 d, `market_ohlcv_bars` 21 % > 1 y no window, `daily_close_cache` rows back to 2020 no window) | mixed | High | High | High (backtests) | none | high, but belongs in parquet not in the hot DB | KEEP HOT 1 y; ARCHIVE older to parquet | 365 d hot |
| Communications (`communication_*` 335 MB since 09-05, `telegram_outbox` 77 % > 90 d) | none | High (dedupe, audit) | Low | None | none | the suppression ledger is the audit trail; keep 180 d | DELETE > 180 d | 180 d |
| Brokerage and tax (`trade_transactions`, `trade_closed`, `portfolio_snapshots`, `dividend_history`, tax lots) | 180 d in db_retention | High | High | High | **7 years** | required | KEEP HOT 1 y, ARCHIVE 7 y (never delete) — **the 180-day policy on these is wrong** | fix immediately |
| DOF (`dof_ticket_events` 118 k, 73 % > 90 d) | none | Medium | Low | Low | none | auction history | ARCHIVE > 1 y | 365 d |
| Options history (`options_*` 52 tables, 84 MB) | none | High | Medium | Medium | none | thesis outcomes | KEEP HOT 1 y | 365 d |

---

## Area 4 — pruning strategy

| Rank | Item | Size | Growth | Business value | Removal risk | Class |
|---|---|---|---|---|---|---|
| 1 | 26 exact-duplicate index pairs (`hermes_score_history` 345 MB, `market_ohlcv_bars` 258 MB, `content_embeddings` 205 MB, `ticker_prices` 125 MB, …) | ≈1 GB | with tables | none (second copy) | none (`DROP INDEX CONCURRENTLY` on the non-unique twin) | **Safe to remove** |
| 2 | 382 empty tables incl. `bak_*`, `_bak_*`, `*_backup_*`, `*_legacy`, 6 `crash_*` schemas, `system_rollup_daily` (78 MB orphaned TOAST on 0 rows) | ≈130 MB + catalog noise | none | none | none for 0-row tables; `analyst_consensus_history_quarantine_20260913` (37 MB) needs a look | **Safe to remove** (after a schema-only dump) |
| 3 | Dead queues: `deep_overnight_llm_queue` (1,928 pending since May, lane retired), `inference_ensemble_jobs` expired 3,779, `watch_decision_refresh_jobs` > 30 d (35,126), `proposal_llm_review_queue` 119 stuck PROCESSING + 364 expired, `alert_digest_queue` 827 expired never consumed, `hermes_embedding_queue` completed > 30 d (27,680) | ≈120 MB | slow | none | none | **Safe to remove** |
| 4 | 564 never-scanned indexes (626 MB) | 626 MB | with tables | unknown until a 30-day `idx_scan` observation after a stats reset | low; recreate if a query regresses | **Needs review** (30-day watch, then remove) |
| 5 | `content_embeddings` fused-signal and social rows older than 30 d, and content-duplicate vectors | ≈7–8 GB incl. bloat | 125 MB/day | low (never retrieved) | low (retrieval touches newest 200/symbol) | **Safe to remove** after the TTL change; then `pg_repack`/`VACUUM FULL` in a window |
| 6 | `hermes_external_research` rows > 90 d and all error/unavailable/skipped rows | ≈300 MB | 418/day | low | low (summaries live in research_intelligence) | **Safe to archive** (jsonl.gz to persistent-state/archive, then delete) |
| 7 | `agent_recommendation_registry` > 180 d, `trade_integrity_audit` > 90 d, `hermes_outcome_ledger` > 180 d, `hermes_score_event_queue` processed > 30 d | ≈350 MB | 9 k/day | calibration aggregates only | low | **Safe to archive** |
| 8 | `market_ohlcv_bars` bars older than 1 y, `daily_close_cache` before 2024, `market_quote_snapshots` > 90 d | ≈400 MB | steady | high for backtests | medium (backtests read them) | **Safe to archive** to parquet with a loader |
| 9 | `communication_*` > 180 d, `telegram_outbox` > 90 d, `llm_consumption_log` > 180 d (after monthly rollups) | ≈200 MB | 2.5 k/day | audit | low | **Safe to archive** |
| 10 | `decision_packets` > 90 d (372 MB TOAST), `health_agent_snapshots` > 30 d (126 MB) | ≈450 MB | 177/day at 20 kB | regenerable | low | **Safe to archive** |
| 11 | Prices ≤ 1 y, cio_decisions ≤ 90 d, memory facts, journal, trade and tax records, options history, Hermes research intelligence | ≈3 GB | — | core | high | **Keep online** |
| 12 | `intelligence.gir_*` (598 MB, 106 M index scans — the busiest tables in the database) and `memory_r10_m2.*` | 600 MB | NOT VERIFIED (RLS) | high | unknown | **Needs review** with a reader role that can see them |
| 13 | `screener_symbol_membership` (88 % bloat from 10.8 M updates on 67 k rows), `trade_ai_state` (37 %), `scope_governor_audit` (31 %) | ≈500 MB reclaimable | — | high | none (repack, not delete) | **Keep online, repack** |

Orphans: sampled joins found 0 orphan embeddings and 0 duplicate (source, model) pairs. Duplicates by content: `hermes_external_research` 70 % repeated (symbol, question) pairs; `research_insights` 85 % share a source row; `fused_signals` 44 % identical consecutive re-emits (ESTIMATE, sampled).

---

## Area 5 — clean house before expanding n8n?

**B. Perform targeted cleanup, now, and let n8n Phase 1 continue in parallel.** Not A: the disk is at 85 % with the PG17 lab cutover, index rebuilds and a 2.8 GB nightly dump all needing headroom, and backups are getting slower while never being restore-tested. Not C: a "major pruning" of research history without the retention table above would destroy calibration and thesis lineage for no space gain worth the risk; the gains are concentrated in one table, duplicate indexes and dead queues. Not D: the research and memory architecture (staged → promoted → archived in Hermes research intelligence, versioned memory facts) is sound; what is broken is that the raw layers underneath it have no windows and the embedding layer stores the wrong rows in the wrong format. n8n itself is irrelevant to the database question: Phase 1 adds 48 rows to a 135 kB SQLite file. The reason to clean first is operational safety, not n8n.

---

## Area 6 — future-state knowledge architecture

| Store | Belongs there | Lifetime | Moves when | Deleted when |
|---|---|---|---|---|
| PostgreSQL hot (`trade_ai`) | operational facts ≤ 90 d (quotes 90 d, decisions 90 d, research 90 d, comms 180 d, audits 14–30 d), prices ≤ 1 y, brokerage and tax ≤ 1 y, memory facts (versioned, forever), research intelligence (promoted layer), options ≤ 1 y | per table, enforced by one `db_retention.py` scheduler | nightly archive job writes jsonl.gz / parquet to the archive store before the delete edge | at the window; never for tax, memory facts, journal |
| pgvector (`vector(768)` + HNSW) | **only after retrieval receipts justify it**: news, Hermes research, CIO decisions, social ≤ 90 d, deduped (≈300 k rows, ≈1 GB) | 90 d | written by the indexer with a content hash; never for fused signals | at 90 d |
| Object storage (`persistent-state/archive/`, parquet / jsonl.gz, monthly files) | prices > 1 y, bars, external research > 90 d, recommendation and calibration rows > 180 d, decision packets > 90 d, comms > 180 d, DOF > 1 y | 7 y for anything financial, 2 y otherwise | nightly before deletion | by yearly policy |
| Archive storage (Drive, the existing weekly offsite sync) | the archive store plus the nightly DB dump | 7 y financial | weekly | never for tax |
| Memory system (`memory_r10_m2`, `trade_lesson_memory`) | facts, lessons, supersession chains | forever | — | never; superseded, not deleted |
| Research system (Hermes research intelligence) | staged 90 d → promoted (kept) → archived 180 d → purged | as policy | librarian | archived at 180 d |
| n8n coordination records (SQLite ledger) | event receipts, acks, refusals | 90 d | weekly report snapshots to docs/ledgers | 90 d |

---

## Executive answers

1. **Why "degraded"?** The label was about the n8n lab Postgres (PG16 compatibility-only, superuser role, no checksums). Production was never assessed; now it has been: not broken, but untuned (128 MB shared buffers, 4 MB work_mem, 726 GB of temp spills, 65 % hit ratio, 41 % rollback ratio), bloated (≈5 GB), carrying 1.6 GB of useless indexes and 25 tables with no retention.
2. **How do we fix it?** Tune (memory, `pg_stat_statements`, slow-query log, per-table autovacuum), drop duplicate indexes, add the missing retention windows, change the embedding TTL and sources, repack the four bloated tables, run and time a restore drill, fix `backup_verify`, remove the second retention scheduler. Two weeks.
3. **Do we still need RAG?** As a capability, yes. As implemented, it is a 200-row recency scan with Python cosine; the vector corpus does not serve it. Keep the capability, instrument it, shrink what feeds it.
4. **Do we still need pgvector?** Not today. Keep the extension installed (free); build a `vector` column and HNSW index only after retrieval receipts show semantic ranking over more than the newest 200 rows is worth it.
5. **Do we still need 1.31 M embeddings?** No. About 300 k (news, research, decisions, social under 90 days, deduped) are the useful set. Stop embedding fused signals.
6. **Safely removable today:** 26 duplicate indexes (≈1 GB), 382 empty and backup-named tables plus the 6 `crash_*` schemas and the 78 MB orphaned TOAST, dead queue rows (deep-overnight, expired ensemble jobs, stale refresh jobs, stuck proposal reviews, expired digest queue, completed embedding-queue rows), fused-signal and social embeddings older than 30 days.
7. **Archive:** external research > 90 d, recommendation registry and calibration rows > 180 d, integrity audit > 90 d, outcome ledger > 180 d, bars > 1 y, close cache before 2024, decision packets > 90 d, comms > 180 d, DOF > 1 y.
8. **Retain:** prices ≤ 1 y, decisions ≤ 90 d, memory facts and lessons forever, Hermes research intelligence (promoted), journal, options ≤ 1 y, and brokerage/tax records for 7 years, which means the current 180-day policy on `trade_transactions`, `trade_closed`, `portfolio_snapshots` and `dividend_history` must be changed to archive-not-delete before the next retention run.
9. **Prune before expanding n8n?** Yes, targeted (option B), in parallel; n8n's own footprint is negligible and already live.
10. **As CTO, the exact project:** "Trim 2026-10", two weeks, one owner, no new infrastructure.
   - Day 1: fix the tax-record retention policy (archive, never delete); install `pg_stat_statements` and `log_min_duration_statement = 2s`; raise `shared_buffers` to 2 GB, `work_mem` 32 MB, `maintenance_work_mem` 512 MB, `effective_cache_size` to half of RAM (RAM NOT VERIFIED; set after `free -g`); restart in a window; reset stats.
   - Days 2–3: `DROP INDEX CONCURRENTLY` the 26 duplicates; drop the 382 empty tables and `crash_*` schemas after a schema-only dump; truncate the dead queues listed above; remove the dev-tree `db-retention.timer` so one scheduler remains.
   - Days 4–6: add retention windows for the 25 uncovered tables per Area 3; add the nightly archive step (jsonl.gz / parquet to `persistent-state/archive`) that runs before each delete edge; add a per-table autovacuum override for the four high-churn tables.
   - Days 7–8: embeddings: content-hash dedupe in `rag_indexer.py`, stop `fused_signal` and `social_post` re-emits, 30-day TTL for those sources, 90-day for the rest; retrieval receipts in `get_rag_context`; then `pg_repack` (or `VACUUM FULL` in a window) on `content_embeddings`, `screener_symbol_membership`, `trade_ai_state`, `scope_governor_audit`.
   - Days 9–10: production restore drill into a scratch database with a measured time and a receipt; fix `backup_verify`'s path; confirm the offsite weekly copy; measure again (size, backup size and time, hit ratio, temp files, WAL/day).
   - Decision gate at day 10: with retrieval receipts in hand, decide on `vector(768)` + HNSW for the ≈300 k useful rows, or keep the recency scan and leave pgvector idle.
   - Expected result: 23 GB → ≈12 GB, backup 2.8 GB → ≈1.4 GB in ≈10 minutes, measured restore time, hit ratio toward 90 %, temp spills near zero, one retention scheduler, no unbounded table.

What still needs an operator decision: a reader role that can see the RLS-protected `intelligence.*` and `memory_r10_m2.*` schemas for measurement (the busiest tables in the database are invisible to this review); the maintenance windows; the tax-record retention correction, which should be the first change made.
