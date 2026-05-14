# Phase 1 Final Closeout Report — LLM Fleet v4.1

**Date:** 2026-05-14
**Status:** COMPLETE — all 14 Phase 1 requirements met
**Next:** Phase 2A embedding A/B can begin after operator approval

---

## 1. Phase 1 Summary

Phase 1 established the deep overnight LLM processing window using gemma3-overnight
on the Intel Arc Pro B50 (16 GB GDDR6 VRAM). The system processes a prioritized queue
of high-value analytical jobs during a 23:00–03:00 ET window, then restores the
production models (qwen3:14b + nomic-embed-text) before market hours.

Key facts:
- **qwen3:14b** remains the default local model for STANDARD / REALTIME
- **nomic-embed-text** remains the production embedding model
- **gemma3-overnight** is used only through the controlled deep overnight wrapper
- **Anthropic** is degraded (credit balance low) — OpenAI (gpt-4o-mini) is the active cloud fallback
- All safety gates pass: paper mode, LLM live execution disabled, holdings >$1M

## 2. What Was Implemented

### Phase 0 — Foundation (2026-05-11)
- GPU lifecycle management (`gpu_lifecycle.py`)
- Provider verifier (`verify_llm_providers.py`)
- Audit logging (`llm_routing_audit` table)
- `/api/v2/gpu-status` endpoint
- `LLM_DISABLE_LIVE_EXECUTION=true` added to .env
- Process-type model map in `local_llm_config.py`

### Phase 1A–1D — Pilot & Expansion (2026-05-11 to 2026-05-12)
- gemma3-overnight Modelfile (keep_alive=0, num_ctx=8192)
- Manual pilot wrapper (`run_batch_overnight_gemma_pilot.sh`)
- Tested 1 → 2 → 5 symbols
- Confirmed ~91s/symbol, 25% CPU spillover (permanent constraint)
- Model-swap lock concept validated

### Phase 1H — Daily Deep Window (2026-05-12 to 2026-05-13)
- Deep overnight queue: `deep_overnight_llm_queue` + `deep_overnight_llm_results` tables
- Queue builder (`build_deep_overnight_llm_queue.py`): 14 job types, 5 priority tiers
- Queue runner (`run_deep_overnight_llm_queue.py`): checkpointed, time-budgeted, recoverable
- Wrapper (`run_deep_overnight_llm_window.sh`): safety gates, model swap, restore, lock
- Daily 23:00 cron enabled
- Friday 16:00 extended cron (operator-approved)
- Calibration loop: `gemma3_calibration_events` table + nightly scorer
- Observed throughput: ~40-43s/job (100 jobs in ~70 min)

### Phase 1J — Mixed Queue Enforcement (2026-05-14)
- `--force-job-types` passed to runner via wrapper
- `--allow-over-75` renamed to `--allow-over-hard-max`
- Friday extended cap reduced from 400 to 200
- HARD_MAX_JOBS updated from 100 to 125

### Phase 1K — Queue Quota Balancing (2026-05-14)
- `--quota-policy balanced` with per-type soft quotas
- DEFAULT_QUOTAS: risk_synthesis=1, recovery_watch=10, rag_curation=15, etc.
- Strategy classification fills remaining capacity
- Dry run confirms mixed selection (15 RAG + 1 journal + 34 strategy vs. all-RAG before)

### Phase 1L — Queue Status Reporting (2026-05-14)
- `report_deep_overnight_queue_status.py`: --summary, --json, --pending-top N
- Reports queue counts, job mix, failed jobs, model residency, lock, cron, risk synthesis

### Phase 1M — Health Checks & Alerting (2026-05-14)
- `check_deep_overnight_health.py`: 11 health checks, PASS/WARN/FAIL
- Integrates with `alert_dispatcher.py` for FAIL conditions
- Checks: lock stuck, gemma/qwen/nomic residency, risk synthesis, P0 pending, failed jobs, provider, safety gates, holdings
- All 11 checks currently PASS

### Overnight Intelligence Dashboard (2026-05-14)
- `/v2/overnight` page with v2 parsed gemma3 outputs
- `/api/v2/overnight-dashboard` with 15 sections
- Actionable signals, data quality alerts, per-ticker RAG, duplicate detection
- Telegram digest script

## 3. Current Cron Policy

```
# Daily deep overnight window (23:00–03:00 ET)
0 23 * * * cd /home/johnclaw/.../trade-ai-v12-rebuild && ./scripts/run_deep_overnight_llm_window.sh >> logs/deep_overnight_llm_window.log 2>&1

# Friday extended deep run (operator-approved, cap 200)
0 16 * * 5 cd /home/johnclaw/.../trade-ai-v12-rebuild && flock -n /tmp/tradeai_deep_llm_window.lock bash scripts/run_deep_overnight_llm_window.sh --force-window --max-jobs 200 --allow-over-hard-max >> logs/deep_llm_friday_extended.log 2>&1
```

Watchlist agent jobs (4 entries) respect the deep lock — skip processing when lock is active.

## 4. Current Model Routing

| Process Type | Model | Notes |
|-------------|-------|-------|
| STANDARD | qwen3:14b | Default for all daytime LLM calls |
| REALTIME | qwen3:14b | Same as standard |
| BATCH_OVERNIGHT | qwen3:14b | Default; wrapper overrides to gemma3-overnight via shell env |
| DEEP_OVERNIGHT | gemma3-overnight | Only through wrapper, never in .env |
| EMBEDDING | nomic-embed-text | Production embeddings, unchanged |
| MEDIA_CONTENT | Not yet production | Phase 3 future work |
| CRITICAL_CLOUD | qwen3:14b | Cloud fallback: gpt-4o-mini → claude-sonnet |

## 5. Queue Policy

| Setting | Daily (23:00) | Friday Extended (16:00) |
|---------|--------------|------------------------|
| Max jobs | 100 | 200 |
| Hard max | 125 | 200 (--allow-over-hard-max) |
| Time budget | 240 min | 240 min |
| Hard stop | 03:00 | 03:00 |
| Restore deadline | 03:15 | 03:15 |
| Quota policy | balanced | balanced |
| Forced job types | YES | YES |

### Per-Type Soft Quotas (daily):

| Job Type | Quota |
|----------|-------|
| risk_synthesis | 1 |
| recovery_watch_review | 10 |
| rag_content_curation | 15 |
| closed_trade_review | 15 |
| auto_journal_review | 15 |
| manual_journal_review | 15 |
| journal_pattern_review | 3 |
| proposal_review | 10 |
| strategy_classification | Remaining capacity |

### Priority Tiers:
- P0: Emergency (risk_synthesis when missing)
- P1: High (stale positions, pending news, active trades)
- P2: Medium (backlog, never-reviewed)
- P3: Low (watchlist, supplementary)
- P4: Background (weekly scans)

## 6. Safety Gates

All enforced by `run_deep_overnight_llm_window.sh`:

1. ALPACA_MODE=paper (read from .env via grep, not source)
2. LLM_DISABLE_LIVE_EXECUTION=true
3. Holdings guard > $1M
4. Ollama alive check
5. Window time check (23:00–03:00 unless --force-window)
6. Lock file (`/tmp/tradeai_deep_llm_window.lock`) with PID and stale detection
7. qwen3:14b restore with 3 retry attempts + emergency Ollama call
8. nomic-embed-text restore with verification
9. Provider verification after restore
10. No .env modification
11. No broker/holdings/execution writes

## 7. Rollback Instructions

### Disable overnight processing:
```bash
# Remove daily cron
crontab -l | grep -v "run_deep_overnight_llm_window" | crontab -

# If a deep run is active, wait for completion or:
kill $(cat /tmp/tradeai_deep_llm_window.lock)
rm -f /tmp/tradeai_deep_llm_window.lock
```

### Restore models manually:
```bash
# Unload gemma3-overnight
curl -s -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"gemma3-overnight","keep_alive":0,"prompt":""}' --max-time 15

# Restore qwen3:14b
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from gpu_lifecycle import warmup
print(warmup('qwen3:14b'))
"

# Restore nomic-embed-text
curl -s -X POST http://localhost:11434/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"nomic-embed-text:latest","prompt":"test"}' --max-time 30

# Verify
.venv/bin/python scripts/verify_llm_providers.py
```

### Restore previous crontab:
```bash
cat docs/v4_1_discovery/crontab_pre_phase1j.txt | crontab -
```

## 8. Phase 1 Remaining Observations

- Tonight's balanced mixed queue run should be monitored to confirm quota policy works in production
- Friday extended run at 200 jobs should be monitored before any increase
- 400-job extended run not approved — requires future Phase 1K+ evidence at 200
- 494 pending jobs (mostly strategy_classification) — will clear over ~5 nights
- Recovery watch verdicts are all template fallback (NEEDS_MORE_DATA) — investigate prompt quality

## 9. Phase 2 Readiness

Phase 2A (embedding A/B) can begin after:
- [x] Phase 1 validation passes (all 14 requirements met)
- [ ] Operator explicitly approves "Begin Phase 2"
- [ ] 7 consecutive clean nightly runs observed
- [ ] `scripts/embedding_ab_baseline.py` created (not yet)

No production embedding promotion until A/B retrieval baseline shows improvement.

## 10. Phase 3 Readiness

Phase 3 (media/content model) remains separate and optional:
- No prerequisites from Phase 2
- Small pilot can begin after Phase 1 closeout
- No trading or risk surface use
- Operator must explicitly approve "Begin Phase 3"
