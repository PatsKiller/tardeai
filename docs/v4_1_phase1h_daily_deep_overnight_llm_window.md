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

## 2. Why 4 Hours Is Allowed — Capacity Policy

- gemma3-overnight processes ~1 item per 2–3 minutes (from Phase 1D testing)
- 240 minutes / 2.5 min avg = ~80–120 items theoretical max
- **Default nightly target: 100 jobs** (operational cap)
- Observed throughput: ~40-43 sec/job (100 jobs ≈ 72 min, well within 240-min budget)
- The 03:00 hard stop ensures qwen3:14b is restored before any 04:00+ jobs
- **Time cap always beats count cap** — if 03:00 arrives before all items finish, the window stops
- No market-hours risk: window is entirely after close and before pre-market

### Why 100 is the default (not 70, not 150)

Phase 1D estimated ~91 seconds per symbol, but observed nightly throughput is
~40-43 seconds per job. 100 jobs × 43s = ~72 minutes, leaving >160 minutes of
buffer for the restore cycle. The prior cap of 70 was too low — it caused new
Phase 1H expansion job types (risk_synthesis, rag_content_curation, etc.) to be
cut off despite having P0/P1 priority because 70 original-type jobs had higher
individual scores.

### Mixed queue budget sharing

If P0/P1 journal reviews or closed-trade reviews exist in the queue, they consume
part of the nightly budget. The queue runner processes in strict priority order, so
high-priority non-symbol jobs run first. Reserve roughly 30–45 minutes (15–20 jobs)
for these items. The remaining budget goes to strategy classification symbols.

If no high-priority journal/closed-trade jobs exist, strategy classification may
use the full 100-job target.

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
| `rag_content_curation` | `news_articles`, `youtube_transcripts` | Deep curation with 128K context — APPROVE_BOOST/STANDARD/LOW_QUALITY/SUPERSEDED. Nightly, up to 20 items |
| `risk_synthesis` | `holdings.json`, `paper_trades` | Single nightly P0 portfolio risk narrative for morning brief. Saved to `risk_synthesis_results` |
| `recovery_watch_review` | `stopped_out_watch` | Thesis validity for stopped-out positions. Tue/Thu only, up to 12 items |
| `covered_call_scoring` | `aegis_covered_call_candidates` | Strike/yield scoring for CC candidates. Sunday only, up to 15 items |
| `weekly_behavioral_review` | `paper_trades` | Cross-trade pattern analysis. Sunday only, gated at 20+ closed trades (currently inactive) |
| `rebalance_analysis` | `rebalance_analysis_results` | Monthly deep rebalance analysis. 1st of month or stale >35 days |
| `strategy_opportunity_scan` | `ticker_snapshot_daily` | Weekly Sunday P1: gemma3 evaluates top 40 watchlist symbols against 11 underutilized strategies to surface candidates momentum screeners miss |
| `income_strategy_scan` | `ticker_snapshot_daily`, `incubator_universe` | Monday nights P1: evaluates income universe against income_add, dividend_growth_compounder, high_yield_income_bdc, covered_call_income |
| `growth_strategy_scan` | `ticker_snapshot_daily`, `incubator_universe` | Wednesday nights P1: evaluates growth universe against core_growth_compounder, sector_rotation, defense_thesis |
| `reversion_strategy_scan` | `ticker_snapshot_daily`, `incubator_universe` | Saturday nights P1: evaluates oversold/bond/cash universe against swing_trade retracement, bond_income, cash_or_stable |

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

### Event-Driven Requeue Engine

Runs at the start of every build cycle (before scheduled queues) to detect
material changes since the last gemma3 analysis. Fills unused nightly slots
with the most urgent re-analyses instead of letting capacity go idle.

| Trigger | Job Type | Score Bonus | Condition |
|---------|----------|-------------|-----------|
| **Staleness** | strategy_classification | +0-10 | >14 days since last classification |
| **Price move** | strategy_classification | +10-20 | >5% week move |
| **RVOL spike** | strategy_classification | +15 | RVOL >5x (unusual activity) |
| **Earnings proximity** | strategy_classification | +25 | Earnings within 14 days |
| **Price recovery** | recovery_watch_review | score=95 | Price within 2% of exit price (any day) |
| **CC price move** | covered_call_scoring | score=85 | >3% week move on CC candidate (any day) |

Base requeue score for strategy_classification is 75 (P1), with bonuses stacking.
Recovery watch and covered call requeues bypass the Tue/Thu and Sunday schedule
gates when triggered by significant price events.

## 10. Nightly Budget Policy

- **Time budget:** 240 minutes (default)
- **Hard stop:** 03:00 local time
- **Default nightly target:** 100 jobs
- **Per-job timeout:** 180 seconds (3 minutes)
- **Restore deadline:** 03:15 (cleanup takes ~2-3 minutes)
- **Queue order:** Priority score descending, then queued_at ascending
- **Time cap beats count cap:** If 03:00 arrives before all jobs finish, the window stops
- **Mixed budget:** P0/P1 journal/closed-trade jobs reduce available symbol slots

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

# Run with custom job count
./scripts/run_deep_overnight_llm_window.sh --force-window --max-jobs 80

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

## 20. Calibration & Accuracy Tracking

gemma3 overnight predictions are graded against actual outcomes via the
`gemma3_calibration_events` table and `gemma3_accuracy_by_job_type` view.

### How it works
1. **Seeding**: Every completed gemma3 job gets a PENDING calibration event
2. **Grading**: `gemma3_calibration_scorer.py` runs nightly at 21:30 (weekdays)
3. **strategy_classification**: Graded when a paper trade closes within 14 days
   - CORRECT: strong fit + trade won, or weak fit + trade lost
   - WRONG: strong fit + trade lost, or weak fit + trade won
4. **recovery_watch_review**: Graded 14+ days after verdict
   - CORRECT: THESIS_INTACT + price recovered, or INVALIDATED + stayed down
   - WRONG: opposite of prediction
5. **rag_content_curation**: Graded by RAG retrieval count (future)

### Monitoring
```bash
# Current accuracy
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2) psql -h localhost -U trade_ai -d trade_ai -c "
SELECT * FROM gemma3_accuracy_by_job_type;"

# API endpoint
curl -s http://localhost:7777/api/v2/queue/calibration | python3 -m json.tool
```

### Cron schedule
```
30 21 * * 1-5  .venv/bin/python scripts/gemma3_calibration_scorer.py >> logs/gemma3_calibration.log 2>&1
```

## 21. Phase 2 and Phase 3 Gates

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

### Completed Phase 1H extensions
- risk_synthesis, rag_content_curation, recovery_watch_review, covered_call_scoring, weekly_behavioral_review, rebalance_analysis — all active
- strategy_opportunity_scan — Sunday nights, evaluates watchlist against 11 underutilized strategies
- Rotating strategy scans: income_strategy_scan (Mon), growth_strategy_scan (Wed), reversion_strategy_scan (Sat)
- Strategy-aware incubator grading (`incubator_llm_screener.py`): 4 prompt groups (income, growth, reversion, momentum). Income/reversion symbols no longer penalized for low RVOL or missing catalyst
- Event-driven requeue engine — price/staleness/earnings/recovery triggers
- gemma3 calibration loop — grades verdicts against actual outcomes
- 7 new Finviz screeners (27 total) + 16 static bond/BDC/cash symbols in watchlist
- Friday 4PM extended window (200 jobs — Phase 1J reduced from 400)
- Queue Manager UI page at /v2/ops (LLM Queue tab)
- Overnight Intelligence Dashboard at /v2/overnight (Phase 1J)

---

## 22. Phase 1J — Mixed Job Type Enforcement and Cron Cleanup

**Date:** 2026-05-14
**Status:** DEPLOYED

### Problem
The nightly wrapper (`run_deep_overnight_llm_window.sh`) did not pass `--force-job-types`
to the queue runner. Strategy classification jobs dominated the queue, starving
risk_synthesis, recovery_watch_review, rag_content_curation, closed_trade_review,
and journal review jobs.

A Friday 16:00 extended cron used `--max-jobs 400 --allow-over-75`, which was too
aggressive and used stale flag naming.

### Changes

**A. Wrapper forced mixed job types:**
The wrapper now passes `--force-job-types` to ensure these types run before
strategy_classification fills remaining capacity:
- risk_synthesis
- recovery_watch_review
- rag_content_curation
- closed_trade_review
- auto_journal_review
- manual_journal_review
- journal_pattern_review
- proposal_review

**B. Capacity policy:**
| Setting | Daily (23:00) | Friday Extended (16:00) |
|---------|--------------|------------------------|
| Max jobs | 100 | 200 |
| Hard max | 125 | 200 (with --allow-over-hard-max) |
| Hard stop | 03:00 | 03:00 |
| Restore deadline | 03:15 | 03:15 |
| Forced mixed types | YES | YES (via wrapper) |
| Safety gates | All | All |
| 400 jobs | NOT APPROVED | Requires Phase 1K |

**C. Flag naming cleanup:**
- `--allow-over-75` renamed to `--allow-over-hard-max`
- Backward compatibility preserved (both flags accepted)
- HARD_MAX_JOBS changed from 100 to 125

**D. Friday extended cron preserved with safe policy:**
- Reduced from `--max-jobs 400` to `--max-jobs 200`
- Uses `--allow-over-hard-max` (replaces stale `--allow-over-75`)
- Same safety gates, lock, restore behavior as daily run
- Operator-approved — documented as intentional
- 400 requires future Phase 1K approval after observing 200

**E. Crontab:**
```
# Daily 23:00
0 23 * * * cd /home/johnclaw/.../trade-ai-v12-rebuild && ./scripts/run_deep_overnight_llm_window.sh >> logs/deep_overnight_llm_window.log 2>&1

# Friday extended (operator-approved, cap 200)
0 16 * * 5 cd /home/johnclaw/.../trade-ai-v12-rebuild && flock -n /tmp/tradeai_deep_llm_window.lock bash scripts/run_deep_overnight_llm_window.sh --force-window --max-jobs 200 --allow-over-hard-max >> logs/deep_llm_friday_extended.log 2>&1
```

**F. Overnight Intelligence Dashboard:**
New page at `/v2/overnight` with API endpoint `/api/v2/overnight-dashboard`.
Single-shot morning briefing showing window stats, risk synthesis, recovery verdicts,
trade reviews, strategy classifications, covered calls, RAG curation, proposals,
failed jobs, and gemma3 calibration accuracy. Telegram digest script added.

### What Phase 1J does NOT change
- No Phase 2 or Phase 3 work
- No embedding changes
- No broker/holdings/execution changes
- No global model routing changes
- No queue/result data deleted

### Future Phase 1H extensions (not authorized)
- Expand queue sources to include SEC/news/social catalysts
- Add OpenAI tier-2 review for high-priority items gemma flagged
- RAG retrieval count grading for rag_content_curation calibration

---

## 23. Phase 1K — Queue Mix Balancing / Quotas

**Date:** 2026-05-14
**Status:** DEPLOYED

Added `--quota-policy balanced` to `run_deep_overnight_llm_queue.py`. Per-type soft
quotas prevent any single forced job type from consuming all queue slots:

| Job Type | Soft Quota |
|----------|-----------|
| risk_synthesis | 1 |
| recovery_watch_review | 10 |
| rag_content_curation | 15 |
| closed_trade_review | 15 |
| auto_journal_review | 15 |
| manual_journal_review | 15 |
| journal_pattern_review | 3 |
| proposal_review | 10 |
| strategy_classification | Remaining capacity |

Dry run confirmed: 15 RAG + 1 journal + 34 strategy (mixed) vs. all-RAG before quotas.

---

## 24. Phase 1L — Queue Status Reporting

**Date:** 2026-05-14
**Status:** DEPLOYED

`scripts/report_deep_overnight_queue_status.py` — standalone CLI reporter.

Reports: queue counts by status/type, done today, failed jobs, P0/P1 pending,
oldest pending, latest run, risk synthesis, recovery verdicts, journal reviews,
RAG curation, model residency, lock status, cron presence.

---

## 25. Phase 1M — Health Checks & Alerting

**Date:** 2026-05-14
**Status:** DEPLOYED

`scripts/check_deep_overnight_health.py` — 11 health checks with PASS/WARN/FAIL.

Checks: lock stuck, gemma/qwen/nomic residency, risk synthesis missing, P0 pending,
failed jobs high, deep run status, provider health, safety gates, holdings guard.

Integrates with `alert_dispatcher.py` for FAIL conditions. Exits nonzero on any FAIL.

---

## 26. Self-Healing Data Gap Orchestration

**Date:** 2026-05-14
**Status:** DEPLOYED

Closes the loop between gemma3 detection and automated resolution:

1. **Recovery watch prompt**: uses `llm_context_engine.build_context('recovery_watch')`
   for full data instead of sparse manual queries. Adds `data_gaps` output field.
2. **Queue dedup**: per-job-type cooldown prevents re-running same analysis too often.
3. **`data_gap_registry` table**: every gemma3 "needs more data" creates a structured gap.
4. **`_extract_and_register_gaps()`**: scans every response for 7 implicit gap patterns
   + explicit data_gaps arrays.
5. **`data_gap_resolver.py`**: dispatches enrichment/agent jobs via `watchlist_agent_jobs`,
   re-queues source jobs at elevated priority after resolution.
6. **Dashboard**: gap intelligence section with open/enriching/resolved counts.

Flow: gemma3 flags gap → registry → resolver dispatches agent → data enriched → job
re-queued → next overnight produces better answer → gap closed.

---

## 27. Phase 1 Closeout

**Date:** 2026-05-14
**Status:** COMPLETE

All 14 Phase 1 requirements met. See `docs/v4_1_phase1_final_closeout_report.md`
for full details including rollback instructions, model routing, queue policy,
and Phase 2/3 readiness assessment.
