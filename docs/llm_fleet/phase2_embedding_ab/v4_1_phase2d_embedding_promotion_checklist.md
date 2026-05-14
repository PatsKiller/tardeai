# Phase 2D: Embedding Promotion Checklist

**Version:** v4.1  
**Status:** DESIGN ONLY  
**Date:** 2026-05-14  
**Scope:** Gate checklist required before promoting qwen3-embedding:8b to production  

---

## Do not promote production embeddings without separate operator command: "Begin Phase 2D production embedding promotion."

---

## Promotion Checklist

All 14 items must pass before production embedding promotion can proceed. Each item requires explicit operator verification.

---

### 1. Phase 2A Candidate Quality Pass

- [ ] Phase 2A evaluation completed and documented
- [ ] qwen3-embedding:8b produces valid 4096-dimension embeddings consistently
- [ ] Embedding quality assessed on representative sample (coherence, cluster separation)
- [ ] No dimension mismatches, null embeddings, or malformed outputs observed
- **Evidence:** Phase 2A evaluation log with pass/fail summary

---

### 2. Phase 2B Parallel Index Pass

- [ ] `content_embeddings_qwen3_test` table populated with 500-2000 documents
- [ ] Source type distribution covers: news, agent_result, youtube, decision_outcome, trade_review
- [ ] All validation queries from Phase 2B design pass (row count, dimension consistency, null check)
- [ ] A/B comparison against nomic-embed-text completed on test query set
- **Evidence:** Phase 2B population log and A/B comparison results

---

### 3. Retrieval Quality >= Baseline

- [ ] Hybrid retrieval (or qwen3-only) returns results at least as relevant as nomic-embed-text baseline
- [ ] Tested on minimum 10 representative queries spanning all hybrid query contexts
- [ ] Top-10 overlap analysis shows improvement or parity
- [ ] Manual spot-check of 5+ queries confirms relevance improvement or no degradation
- **Evidence:** Retrieval comparison spreadsheet or log with per-query scores

---

### 4. Latency Acceptable

- [ ] Median qwen3 embedding latency measured and documented
- [ ] Median hybrid retrieval end-to-end latency measured
- [ ] Latency is within acceptable bounds for each query context:
  - Journal review / overnight / proposals: < 3 seconds acceptable
  - Risk synthesis: < 2 seconds preferred
- [ ] No timeouts observed in test runs
- **Evidence:** Latency measurements log (p50, p95, p99)

---

### 5. Storage Impact Known

- [ ] Measured actual table size of `content_embeddings_qwen3_test` at test population
- [ ] Projected full index size (all 14,784+ documents at 4096d) calculated
- [ ] Disk space available confirmed sufficient for dual tables during transition
- [ ] Storage growth rate estimated for ongoing ingestion
- **Evidence:** `pg_total_relation_size` output and projection calculation

---

### 6. Old Nomic Embeddings Preserved

- [ ] Production `content_embeddings` table is NOT modified or dropped during promotion
- [ ] Nomic embeddings remain available for fallback retrieval
- [ ] Plan documented for nomic table retention period (minimum 30 days post-promotion)
- [ ] No queries modified to bypass nomic table until promotion is confirmed stable
- **Evidence:** Confirmation that production table is untouched

---

### 7. Rollback Path Tested

- [ ] Rollback procedure documented and tested:
  - Disable hybrid config flag
  - All queries revert to nomic-only
  - qwen3 table remains but is unused
- [ ] Rollback executed in test/staging and verified
- [ ] Rollback completes in under 1 minute (config change only)
- **Evidence:** Rollback test log showing successful revert

---

### 8. Backup Verified

- [ ] Full database backup taken before any promotion steps
- [ ] Backup includes `content_embeddings` table (nomic data)
- [ ] Backup restore tested or verified restorable
- [ ] Backup timestamp and location documented
- **Evidence:** Backup file path and verification output

---

### 9. No Active Deep Window

- [ ] No deep overnight synthesis currently running
- [ ] No deep journal review currently running
- [ ] Promotion window is outside market hours (preferred: weekend or post-close)
- [ ] No pending proposal generation that depends on current retrieval
- **Evidence:** Operator confirmation of quiet window

---

### 10. No Deep LLM Lock

- [ ] GPU is not locked by active LLM inference (qwen3:14b or other)
- [ ] Ollama model list confirms qwen3-embedding:8b is loaded and responsive
- [ ] Toll gate queue is empty or paused
- [ ] Embedding pipeline can run without contention
- **Evidence:** `ollama list` output and toll gate status

---

### 11. Phase 1 Nightly Health Clean

- [ ] Nightly health check cron has run successfully in last 24 hours
- [ ] No stale embeddings flagged
- [ ] No orphaned rows in content_embeddings
- [ ] Embedding ingestion pipeline is green (no failures in last 24h)
- **Evidence:** Health check log from most recent run

---

### 12. Production Query Validation

- [ ] Run 5 production-representative queries through the new retrieval path
- [ ] Verify results are sensible and complete
- [ ] Compare against same queries on nomic-only path
- [ ] No errors, timeouts, or empty result sets
- [ ] Recency decay and source boost behave correctly with new scores
- **Evidence:** Query validation log with side-by-side results

---

### 13. A1A Doc Update Ready

- [ ] A1A documentation updated to reflect:
  - New table schema (if separate table) or schema changes (if composite key)
  - Hybrid retrieval routing policy
  - New embedding model and dimensions
  - Updated data dictionary entries
  - Storage and latency characteristics
- [ ] MASTER_SYSTEM_DOCUMENTATION updated
- [ ] LLM_DATA_DICTIONARY updated
- [ ] ARCHITECTURE_OVERVIEW updated if applicable
- **Evidence:** Doc diff or commit reference ready (not yet pushed)

---

### 14. Operator Explicit Approval

- [ ] Operator has reviewed all 13 items above
- [ ] Operator has confirmed readiness
- [ ] Operator issues the promotion command

---

## Promotion Command

```
Do not promote production embeddings without separate operator command:
"Begin Phase 2D production embedding promotion."
```

No automated process, cron, or agent may initiate promotion. This is a manual operator gate.

---

## Promotion Steps (executed only after all 14 items pass)

1. Take database backup
2. Enable hybrid retrieval config flag
3. Monitor first 10 queries through hybrid path
4. Verify no errors or degraded results
5. If issues detected: execute rollback immediately
6. If stable after 24 hours: confirm promotion successful
7. Schedule nomic table archival (retain minimum 30 days)
8. Update A1A docs and commit

---

## Post-Promotion Monitoring

- Monitor retrieval latency for 72 hours
- Monitor GPU utilization for embedding calls
- Check for any retrieval quality complaints from downstream consumers
- Verify nightly embedding ingestion works with new model
- Weekly storage check for first month
