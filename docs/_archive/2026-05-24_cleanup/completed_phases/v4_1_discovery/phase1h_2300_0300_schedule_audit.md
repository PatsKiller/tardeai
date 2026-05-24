# Phase 1H — Schedule Audit: 23:00–03:00 Window

**Date:** 2026-05-12
**Purpose:** Identify all jobs running between 23:00 and 03:00 local server time (EDT)

## Cron Jobs Active During 23:00–03:00

### 23:00–23:59 Window

| Schedule | Script | LLM? | Classification |
|----------|--------|------|----------------|
| `*/5 20-23 * * 1-5` | `process_watchlist_agent_jobs.py --limit 5` | YES (qwen3:14b) | **Deferred if deep lock active** |
| `0 21 * * 1-5` | `auto_research.py --check --telegram` | Possible | Allowed — runs at 21:00, finishes before 23:00 |
| `0 21 * * 0` | `generate_weekly_docx.py` (Sunday only) | No | Allowed — Sunday only, finishes before 23:00 |

### 00:00–02:59 Window

| Schedule | Script | LLM? | Classification |
|----------|--------|------|----------------|
| `*/5 0-5 * * 2-6` | `process_watchlist_agent_jobs.py --limit 5` | YES (qwen3:14b) | **Deferred if deep lock active** |
| `0 3 1 * *` | YouTube transcript purge (monthly) | No | Allowed — DB-only, no LLM |

### Systemd Timers Active During 23:00–03:00

| Timer | Fires | LLM? | Classification |
|-------|-------|------|----------------|
| `portfolio-backup.timer` | 02:00 | No | Allowed — DB/file backup only |
| `tradeai-continuous.timer` | 04:00 | Possible | **Outside window** — fires at 04:00 |
| `aegis-overnight.timer` | 20:00 | Possible | Allowed — runs at 20:00, finishes before 23:00 |
| `db-retention.timer` | Sunday 03:00 | No | Allowed — DB maintenance only |

## Conflict Analysis

### Jobs That Compete for Local LLM During 23:00–03:00

1. **`process_watchlist_agent_jobs.py`** — Runs every 5 min during 20-23 (Mon-Fri) and 0-5 (Tue-Sat)
   - Uses qwen3:14b via local_llm.py
   - Has flock guard + 12m timeout
   - **CONFLICT:** Cannot use qwen3:14b while gemma owns GPU
   - **Policy:** Should detect `/tmp/tradeai_deep_llm_window.lock` and skip

2. **`overnight_batch.py`** — Runs at 20:00
   - May use LLM for some tasks
   - **No conflict:** Starts at 20:00, should complete before 23:00

3. **`feedback_loop_processor.py`** — Runs at 20:30
   - May use LLM
   - **No conflict:** Starts at 20:30, should complete before 23:00

4. **RAG/embedding jobs** — No scheduled embedding jobs during 23:00–03:00
   - **No conflict**

5. **SEC/news/social** — `sec_data_ingest.py` at 20:00, `news_ingestion.py` at 18:30
   - **No conflict:** Complete well before 23:00

6. **Aegis jobs** — `aegis-overnight.timer` at 20:00
   - **No conflict:** Complete before 23:00

### Jobs That Are Safe During 23:00–03:00

- `portfolio-backup.timer` (02:00) — No LLM, DB/file only
- `db-retention.timer` (Sunday 03:00) — No LLM, DB maintenance
- YouTube transcript purge (monthly 03:00) — No LLM, DB only
- All paper execution/monitor jobs — Only run 9-16

## Conflict Policy Summary

| Job | During Deep Window | Action |
|-----|-------------------|--------|
| `process_watchlist_agent_jobs.py` | **DEFER** | Skip if `/tmp/tradeai_deep_llm_window.lock` exists |
| `overnight_batch.py` | Allowed | Runs at 20:00, completes before window |
| `feedback_loop_processor.py` | Allowed | Runs at 20:30, completes before window |
| `auto_research.py` | Allowed | Runs at 21:00, completes before window |
| `portfolio-backup.timer` | Allowed | No LLM dependency |
| `db-retention.timer` | Allowed | No LLM dependency |
| All paper execution jobs | N/A | Only run during market hours |
| All embedding jobs | N/A | No scheduled embedding during window |

## Lock File

**Path:** `/tmp/tradeai_deep_llm_window.lock`

During the 23:00–03:00 deep window:
- gemma3-overnight owns the local LLM
- qwen3:14b and nomic-embed-text are evicted
- Jobs detecting the lock should skip/defer their LLM calls
- Non-LLM safety jobs continue normally
- Broker/execution/holdings remain untouched
