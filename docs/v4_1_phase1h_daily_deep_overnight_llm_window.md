# Phase 1H — Daily Deep Overnight LLM Window (23:00–03:00)

**Date:** 2026-05-12
**Status:** ENABLED
**Schedule:** Daily at 23:00 local server time (EDT)
**Window:** 23:00–03:00 (4 hours, hard stop at 03:00)

---

## 1. Summary

Phase 1H enables a daily 23:00–03:00 deep overnight LLM processing window using
`gemma3-overnight` to perform queue-based, prioritized reviews of:

- Strategy classifications for held and watchlist positions
- Closed trade post-mortems
- Automated and manual trade journal entries
- Pending trade proposals
- (Future: recovery/re-entry, risk synthesis, weekly behavioral reviews)

The window is queue-based, time-budgeted (240 minutes), checkpointed after every
item, and fail-closed: qwen3:14b and nomic-embed-text are always restored by 03:15
regardless of success or failure.

## 2. Why 4 Hours Is Allowed

- gemma3-overnight processes ~1 item per 90 seconds (from Phase 1D testing)
- 240 minutes / 90 seconds = ~160 items theoretical max
- Default cap is 120 items per night
- 4 hours provides margin for cold start, queue building, and model swap overhead
- The 03:00 hard stop ensures qwen3:14b is restored before any 04:00+ jobs
- No market-hours risk: window is entirely after close and before pre-market

## 3. Schedule Audit

Full audit: `docs/v4_1_discovery/phase1h_2300_0300_schedule_audit.md`

### Conflicting jobs during 23:00–03:00:
- `process_watchlist_agent_jobs.py` (*/5 20-23 and */5 0-5) — **DEFERRED** via lock check
- `portfolio-backup.timer` (02:00) — **ALLOWED** (no LLM dependency)

### No conflicts:
- All paper execution jobs (9-16 only)
- All embedding jobs (no scheduled during window)
- overnight_batch.py (20:00, finishes before 23:00)
- feedback_loop_processor.py (20:30, finishes before 23:00)

## 4. Conflict List

| Job | Classification | Policy |
|-----|---------------|--------|
| `process_watchlist_agent_jobs.py` | **DEFERRED** | Checks for `/tmp/tradeai_deep_llm_window.lock`, skips if present |
| `overnight_batch.py` | Allowed | Runs at 20:00, completes before window |
| `portfolio-backup.timer` | Allowed | No LLM dependency |
| `auto_research.py` | Allowed | Runs at 21:00, completes before window |
| All paper execution | N/A | Market hours only |

## 5. Queue Architecture

### Table: `deep_overnight_llm_queue`

Central queue tracking all jobs for deep overnight review.

**Key fields:**
- `id`, `job_type`, `symbol`, `trade_id`, `journal_id`, `account`
- `priority_tier` (P0–P4), `priority_score` (numeric)
- `reason_codes` (text array), `status` (pending/running/done/failed/skipped/deferred)
- `input_hash` (dedup), `result_table`, `result_id`
- Checkpointing: `started_at`, `completed_at`, `attempt_count`, `last_error`

### Table: `deep_overnight_llm_results`

Stores gemma3-overnight analysis outputs.

**Key fields:**
- `queue_id` (FK), `job_type`, `symbol`, `trade_id`, `journal_id`
- `model`, `prompt_version`, `summary`
- `findings_json`, `recommendations_json`, `risk_flags_json`

## 6. Job Types

| Job Type | Source Table | Description |
|----------|-------------|-------------|
| `strategy_classification` | `ticker_strategy_classifications` | Deep review of strategy assignments |
| `closed_trade_review` | `trade_closed` | Post-trade analysis of closed positions |
| `auto_journal_review` | `journal_trade_reviews` | Review of automated journal entries |
| `manual_journal_review` | `journal_trade_reviews` | Review of manual journal entries |
| `proposal_review` | `paper_trade_proposals` | Deep review of pending proposals |
| `journal_pattern_review` | (future) | Cross-trade behavioral patterns |
| `recovery_watch_review` | (future) | Recovery/re-entry decisions |
| `risk_synthesis` | (future) | Portfolio-level risk assessment |
| `weekly_behavioral_review` | (future) | Weekly pattern analysis |

## 7. Journal/Closed Trade Integration

- **Closed trades**: All 119 trades in `trade_closed` are candidates
- **Journal reviews**: All 19 entries in `journal_trade_reviews` are candidates
- **Automated journal**: No separate automated journal table exists; journal entries with `auto_` trade_key prefix are classified as `auto_journal_review`
- **Proposals**: Active proposals from `paper_trade_proposals` where status is pending/approved/ready

## 8. Priority Tiers and Scoring

### Tiers
| Tier | Meaning | Examples |
|------|---------|---------|
| P0 | Must review tonight | Held positions, large losses, stop triggers, rule violations |
| P1 | High value | Large gains, new candidates, pending proposals, recent closed trades |
| P2 | Changed evidence | Low confidence, qwen disagreement, new catalysts |
| P3 | Stale/never reviewed | Aging classifications, never reviewed items |
| P4 | Backlog sweep | Low-priority universe sweep |

### Score Formula
| Condition | Points |
|-----------|--------|
| Held/portfolio-critical position | +100 |
| Large realized loss / rule violation | +95 |
| Stop/recovery/danger-zone item | +90 |
| Recent closed trade needing review | +85 |
| Pending proposal | +80 |
| Poorly executed trade (journal) | +80 |
| Active GO/WAIT candidate | +75 |
| New catalyst | +70 |
| Recent journal entry (≤7d) | +60 |
| Stale gemma review | +50 |
| Low confidence classification | +15 |
| Never classified | +30 |
| Stale >14 days | +20 |
| Backlog sweep | +10 |

## 9. Requeue Triggers

Items are requeued when:
- Input hash changes (new evidence, updated classification)
- Priority score increases (higher-priority evidence found)
- Previous attempt failed (up to 3 attempts)
- Stale running jobs recovered (>30 min stuck)

Items are NOT requeued when:
- Already pending with same input hash
- Already completed with same input hash
- Marked as skipped/deferred

## 10. Nightly Budget Policy

- **Time budget:** 240 minutes (default)
- **Hard stop:** 03:00 local time
- **Max jobs:** 120 per night (default)
- **Per-job timeout:** 180 seconds (3 minutes)
- **Restore deadline:** 03:15 (cleanup takes ~2-3 minutes)
- **Queue order:** Priority score descending, then queued_at ascending

## 11. Safety Gates

Before every run:
1. ALPACA_MODE=paper (from .env)
2. LLM_DISABLE_LIVE_EXECUTION=true (from .env)
3. Holdings guard > $1,000,000
4. Ollama alive
5. Window check (23:00–03:00 unless --force-window)
6. Lock file check (no overlapping runs)

## 12. Lock Policy

- **Lock file:** `/tmp/tradeai_deep_llm_window.lock`
- Created at window start, contains PID
- Removed on EXIT/INT/TERM via trap
- Stale locks (PID not running) are auto-removed
- Watchlist agent jobs check this lock and skip if present
- Non-LLM jobs ignore the lock

## 13. Restore Policy

After every run (success or failure):
1. Unload gemma3-overnight (keep_alive=0)
2. Restore qwen3:14b via gpu_lifecycle.warmup()
3. Restore nomic-embed-text via /api/embeddings
4. Verify both models are resident
5. Run verify_llm_providers.py
6. If restore fails: retry twice, then exit nonzero and log CRITICAL

## 14. Logging Paths

| Log | Path |
|-----|------|
| Deep window wrapper | `logs/deep_overnight_llm_window.log` |
| Queue runner | stdout appended to wrapper log |
| LLM audit | `logs/llm_routing_audit.jsonl` |
| Watchlist skip | `logs/watchlist_agent_jobs.log` (`[deep-llm-lock]` prefix) |

## 15. Manual Run Command

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Dry run (shows queue, no model changes)
./scripts/run_deep_overnight_llm_window.sh --dry-run --force-window

# Live run (outside window, must force)
./scripts/run_deep_overnight_llm_window.sh --force-window --max-jobs 10

# Individual components
.venv/bin/python scripts/build_deep_overnight_llm_queue.py --dry-run --limit 50
.venv/bin/python scripts/run_deep_overnight_llm_queue.py --dry-run --limit 5
```

## 16. Scheduled Run Command

```
0 23 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && ./scripts/run_deep_overnight_llm_window.sh >> logs/deep_overnight_llm_window.log 2>&1
```

## 17. Rollback Instructions

### Disable nightly schedule
```bash
# Remove the 23:00 cron entry
crontab -l | grep -v "run_deep_overnight_llm_window" | crontab -
# Or restore from backup:
crontab docs/v4_1_discovery/crontab_pre_phase1h.txt
```

### Stop a running deep window
```bash
pkill -f run_deep_overnight_llm_window.sh
pkill -f run_deep_overnight_llm_queue.py
```

### Emergency model restore
```bash
curl -s http://localhost:11434/api/generate -d '{"model":"gemma3-overnight","keep_alive":0}'
curl -s http://localhost:11434/api/generate -d '{"model":"qwen3:14b","prompt":"ok","stream":false,"options":{"num_predict":1}}'
curl -s http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"restore"}'
```

### Verify after rollback
```bash
curl -s http://localhost:7777/api/v2/gpu-status | python3 -m json.tool
.venv/bin/python scripts/verify_llm_providers.py
```

## 18. How to Pause the Nightly Job

```bash
# Temporary pause (remove cron entry)
crontab -l | grep -v "run_deep_overnight_llm_window" | crontab -

# Re-enable
(crontab -l; echo "0 23 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && ./scripts/run_deep_overnight_llm_window.sh >> logs/deep_overnight_llm_window.log 2>&1") | crontab -
```

## 19. How to Inspect Queue Health

```bash
# Pending jobs by tier
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "
SELECT priority_tier, job_type, count(*), avg(priority_score)::int
FROM deep_overnight_llm_queue WHERE status='pending'
GROUP BY 1,2 ORDER BY 1,2;"

# Recent completions
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "
SELECT id, job_type, symbol, priority_score, last_gemma_runtime_sec, completed_at
FROM deep_overnight_llm_queue WHERE status='done'
ORDER BY completed_at DESC LIMIT 20;"

# Failed jobs
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "
SELECT id, job_type, symbol, attempt_count, last_error
FROM deep_overnight_llm_queue WHERE status='failed';"

# Results summary
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "
SELECT job_type, count(*), avg(length(summary))::int as avg_summary_len
FROM deep_overnight_llm_results
GROUP BY 1;"
```

## 20. Phase 2 and Phase 3 Gates

### Phase 2 readiness (NOT YET)
Before Phase 2 (embedding upgrade):
- Phase 1H must run successfully for ≥7 consecutive nights
- Queue completion rate must be >80%
- No restore failures
- Operator explicitly says "Begin Phase 2"

### Phase 3 readiness (NOT YET)
Before Phase 3 (media/content model):
- Phase 2 must pass with A/B retrieval baseline
- Or Phase 1H stable and operator skips to Phase 3
- Operator explicitly says "Begin Phase 3"

### Future Phase 1H extensions (not authorized)
- Add risk_synthesis, weekly_behavioral_review job types
- Add recovery_watch_review when recovery_outcome_log has data
- Expand queue sources to include SEC/news/social catalysts
- Add OpenAI tier-2 review for high-priority items gemma flagged
