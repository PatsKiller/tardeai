# Hermes Phase 3A — Autonomous Research Loop Architecture

**Date:** 2026-05-31
**Status:** ARCHITECTURE ONLY — not activated

---

## 1. Purpose

Hermes becomes a periodic research and challenge layer that runs automatically on a schedule, producing staged advisory intelligence. Trade AI remains the system of record and execution authority. Hermes remains advisory only.

---

## 2. Non-Negotiable Boundaries

| Boundary | Enforcement |
|----------|-------------|
| No broker access | hermes_readonly role, no broker credentials |
| No proposal mutation | DB role restriction, validator rejection |
| No trade mutation | DB role restriction |
| No journal mutation | DB role restriction |
| No production promotion | No promotion script in autonomous loop |
| No external APIs | No API keys in hermes .env unless separately approved |
| No live trading authority | ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true |

---

## 3. Loop Types

### A. Daily Ticker Challenger Loop

| Parameter | Value |
|-----------|-------|
| Schedule | Once daily, after market close (17:00 ET) |
| Reads | hermes_v_ticker_context, hermes_v_trade_reflection_context, hermes_v_proposal_context |
| Writes | hermes_research_intelligence (status=staged) |
| Max rows/run | 5 |
| Model | gemma3:12b |
| Purpose | Challenge top-held or recently-traded ticker theses |

### B. Overnight Portfolio Reflection Loop

| Parameter | Value |
|-----------|-------|
| Schedule | Once daily, overnight (22:00 ET) |
| Reads | hermes_v_trade_reflection_context, hermes_v_portfolio_context, hermes_v_ticker_context |
| Writes | hermes_research_intelligence (status=staged) |
| Max rows/run | 3 |
| Model | gemma3:12b |
| Purpose | Review closed trades, extract lessons, identify patterns |

### C. Pipeline Data Quality Loop

| Parameter | Value |
|-----------|-------|
| Schedule | Twice daily (08:00, 16:00 ET) |
| Reads | hermes_v_pipeline_health_context, system_health_checks, daily_system_metrics |
| Writes | hermes_validation_findings, hermes_alerts |
| Max rows/run | 5 |
| Model | gemma3:4b (lightweight) |
| Purpose | Detect stale data, pipeline failures, scoring drift |

### D. Source Discovery Loop (future)

| Parameter | Value |
|-----------|-------|
| Schedule | Weekly (Sunday) |
| Reads | Internal sources only initially |
| Writes | hermes_research_sources (when table exists) |
| External | Requires separate Phase 3 external source approval |

---

## 4. Scheduling Design

### Manual first → Timer later

| Stage | Method | Status |
|-------|--------|--------|
| 3B | Manual CLI invocation | First |
| 3C | Manual with --apply | After 3B passes |
| 3F | systemd timer | After observation |

### Proposed runner script: `scripts/hermes_autonomous_loop.py`

```
Usage:
  python scripts/hermes_autonomous_loop.py --loop ticker_challenger [--dry-run|--apply] [--max-rows 5]
  python scripts/hermes_autonomous_loop.py --loop portfolio_reflection [--dry-run|--apply]
  python scripts/hermes_autonomous_loop.py --loop pipeline_quality [--dry-run|--apply]
```

### Safety controls

| Control | Implementation |
|---------|---------------|
| Lockfile | `/tmp/hermes_autonomous_loop.lock` (flock) |
| Single-instance | flock prevents concurrent runs |
| Max runtime | 10 minutes per loop |
| Daily row cap | 10 total across all loops |
| Model call cap | 15 Ollama calls per day |
| Failure backoff | Skip loop if previous run failed; require manual reset |
| Kill file | `hermes_sidecar/.hermes/DISABLED` — if exists, all loops abort |

---

## 5. Read Permissions

| Source | Allowed |
|--------|---------|
| hermes_v_* safe views (8) | YES |
| 37 approved direct-SELECT tables | YES |
| RAG retrieval via rag_retrieval.py | YES |
| Denied tables (14) | NO |
| .env secrets | NO |
| Broker credentials | NO |
| Personal situation tables | NO |

---

## 6. Write Permissions

| Table | Allowed | Gate |
|-------|---------|------|
| hermes_research_intelligence | YES | Via validated ingestion script |
| hermes_validation_findings | YES | Via validated ingestion script |
| hermes_alerts | YES | Via validated ingestion script |
| hermes_memory_events | YES | Lifecycle logging only |
| hermes_embedding_queue | SEPARATE GATE | Only if embedding auto-approval exists |
| content_embeddings | NO | Never in autonomous loop |
| All production tables | NO | Never |

---

## 7. Model Policy

| Model | Use | Autonomous? |
|-------|-----|-------------|
| gemma3:12b | Primary research | YES |
| gemma3:4b | Quick validation, pipeline checks | YES |
| Gemma4 31B | Deep analysis | NO — offline only, separate approval |
| Grok/xAI | External challenger | NO — requires separate approval |
| Cloud LLMs | — | NO |

---

## 8. Quality Controls

- Hardened prompt from `scripts/hermes_research_prompt.py`
- Hardened validator from `scripts/hermes_staging_ingest.py`
- Dry-run before apply (enforced)
- Row cap per run
- Reject question-style challenge_points
- Reject unsupported external claims
- Reject high confidence without evidence
- Require limitations and source_views
- Record run_id for every autonomous batch

---

## 9. Embedding Policy

Research ingestion and embedding are **separate gates**:
- Autonomous loop may stage research rows
- Embedding happens only through separate approved embedding batch
- No auto-embedding in autonomous loop unless Phase 3+ embedding gate approved
- When approved, uses hermes_embedding_queue → hermes_embedding_worker.py

---

## 10. Dashboard Policy

- Shows staged/advisory findings
- No approve/reject/promote/trade buttons
- Must label "Hermes Advisory / Challenger"
- Show run history, row counts, last run time, errors
- No mutation controls

---

## 11. Kill Switch

| Method | Command |
|--------|---------|
| Kill file | `touch hermes_sidecar/.hermes/DISABLED` |
| Timer disable | `systemctl --user stop hermes-autonomous-loop.timer` |
| Service stop | `systemctl --user stop hermes-autonomous-loop.service` |
| Process kill | `pkill -f hermes_autonomous_loop` |
| Remove all | `systemctl --user disable hermes-autonomous-loop.timer` |

**Dashboard health indicator** should show autonomous loop status (active/disabled/errored/last_run).

---

## 12. Monitoring

| Metric | Source |
|--------|--------|
| Last run time | hermes_memory_events |
| Rows produced | hermes_research_intelligence count by date |
| Validation rejects | Log file |
| Model used | Per-row model_used field |
| Duration | hermes_memory_events metadata |
| Errors | Log file + hermes_memory_events |
| Safety violations | Validator rejection count |

---

## 13. Rollback/Disable

1. Disable timer/service
2. Touch DISABLED file
3. Remove staged rows by run_id if needed
4. Rollback embeddings only if separate embedding gate was approved
5. Keep audit logs in hermes_memory_events

---

## 14. Phase 3 Approval Gates

| Gate | Scope | Status |
|------|-------|--------|
| **3A** | Architecture design (this doc) | COMPLETE |
| **3B** | Manual dry-run loop, no DB writes | NOT STARTED |
| **3C** | Manual apply, max 3 rows | NOT STARTED |
| **3D** | Dashboard monitoring additions | NOT STARTED |
| **3E** | Timer/service draft only | NOT STARTED |
| **3F** | Timer activation, low-frequency, row-capped | NOT STARTED |
| **3G** | Observation review after several runs | NOT STARTED |

Each gate requires explicit operator approval.

---

## 15. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Model drift / noisy research | MEDIUM | Row cap, quality gate, validator |
| RAG pollution from auto-embedding | LOW | Embedding is separate gate |
| Over-triggered alerts | MEDIUM | Alert cap per run, severity filtering |
| False confidence | LOW | Confidence explanation required |
| Service runaway | LOW | Lockfile, timeout, kill switch |
| Duplicated research | LOW | run_id tracking, dedup check |
| Resource contention with Trade AI | MEDIUM | Schedule outside enrichment windows |
| Dashboard misunderstanding | LOW | Advisory badges, no mutation controls |

---

## 16. Recommended Next Gate

**Phase 3B — manual dry-run of ticker challenger loop (no DB writes)**
