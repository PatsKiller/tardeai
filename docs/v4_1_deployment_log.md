# LLM Fleet v4.1 — Deployment Log

## Gate Results — 2026-05-11 17:50 ET

### Gate 0 — Live Environment Discovery: PASSED (with notes)
- pwd: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`
- git HEAD: `30dce44` — Update Trade Supervision Methodology
- Discovery artifacts saved to `docs/v4_1_discovery/`

### Gate 1 — Documentation Read: PASSED
All three docs read in full.

### Gate 2 — Clean Working Tree: DISCREPANCY
Working tree has modified files (tsconfig build info, youtube_cookies, docs updates) and untracked files (archive dirs, v4.1 docs themselves, DOF xlsx). **None are LLM scripts or config files.** Proceeding — these are pre-existing non-LLM changes.

### Gate 3 — Holdings Integrity: PASSED
Holdings: $1,191,456 across 47 positions.

### Gate 4 — Paper Mode: PASSED (with deviation)
- `ALPACA_MODE=paper` — present
- `LIVE_TRADING` — NOT in .env (paper mode enforced by code, not env var)
- `LLM_DISABLE_LIVE_EXECUTION` — NOT in .env (will add during Phase 0.6)

**Deviation:** The prompt expects all three vars. The system is paper-only by hardcoded design. Will add `LLM_DISABLE_LIVE_EXECUTION=true` as an additive .env change in Phase 0.6.

### Gate 5 — Backup Verification: PASSED
- Full backup: `docs/backups/trade_ai_backup_20260511.zip` (143MB, today)
- DB dump: `/home/johnclaw/db_backups/trade_ai_20260511_020003.sql.gz` (91MB, today 2AM)
- Backup script supports `--dry-run` only, NOT `--tag` or `--include-*` flags

**Deviation from plan:** `full_system_backup.py` does not support `--tag`, `--include-state`, `--include-rag-index`, `--include-env`, or `--include-crontab`. Output path is `docs/backups/trade_ai_backup_YYYYMMDD.zip`. The plan's backup command must use the simpler form: `.venv/bin/python scripts/full_system_backup.py`

### Gate 6 — Ollama Health: PASSED
Ollama alive at localhost:11434. Running models: qwen3:14b (9624MB), nomic-embed-text (551MB).

### Gate 7 — Database Connectivity: PASSED

### Gate 8 — Provider Map: RECONCILED
**Live .env providers:**
- `ANTHROPIC_API_KEY` — set (Claude)
- `OPENAI_API_KEY` — set (OpenAI)
- `XAI_API_KEY` — set (xAI/Grok)
- No `LLM_*` process-type vars exist yet

**Live Ollama models:**
- `qwen3:14b` — resident, 9624MB
- `nomic-embed-text` — resident, 551MB

**Deviation:** The plan references `grok-4.3`, `gpt-5-mini` — these are NOT in .env. Live cloud model IDs are:
- OpenAI fallback: `gpt-4o-mini` (hardcoded in local_llm.py line 27)
- Anthropic fallback: `claude-sonnet-4-6` (hardcoded in local_llm.py line 28)
- xAI: API key present but no model ID hardcoded in local_llm.py

### Gate 9 — Config Hub Decision: RESOLVED
**`scripts/local_llm_config.py`** is the config hub. It:
- Centralizes model selection via `get_local_llm_model()`
- Reads from `.env` (`LOCAL_LLM_MODEL`, default `qwen3:14b`)
- Provides Ollama runtime env setup

**`scripts/local_llm.py`** is the execution path. It:
- Imports from `local_llm_config.py`
- Uses file-based toll gate (`fcntl` lock)
- Has hardcoded fallback model names: `gpt-4o-mini`, `claude-sonnet-4-6`
- All callers use `generate()` function
- Does NOT have `execute()` method — it has `generate()`

**`scripts/llm_router.py`** also exists (21KB). Needs inspection to determine if it routes production calls.

**Decision:** Extend `local_llm_config.py` with process-type constants. Create `llm_config.py` only as a thin wrapper that imports from it. Do NOT replace `local_llm_config.py`.

### Gate 10 — Operator Authorization: PASSED
Operator said "Begin Phase 0 only."

## Detected Service Units

**User units:**
- `openclaw-gateway.service` (active)
- `tradeai-continuous.timer` (active)
- Multiple portfolio/aegis timers

**System units:**
- `ollama.service` (active)
- `tradeai-portfolio-server.service` (active)
- `tradeai-continuous.timer` (active)
- `tradeai-reprice.timer` (active)

**Rollback restart targets (verified):**
- `sudo systemctl restart ollama.service`
- `systemctl --user restart tradeai-continuous.timer`
- Kill/restart `portfolio_server.py` (runs as process, not always via systemd)

## LLM Reference Scan Summary
- 524 total references found across scripts/apps/config
- Primary config: `scripts/local_llm_config.py` (source of truth)
- Primary execution: `scripts/local_llm.py` (generate() function)
- Router: `scripts/llm_router.py` (exists, needs classification)
- Direct Ollama callers: need full inventory (Phase 0 deliverable)

## Direct Ollama Callers (Migration List)
To be populated during Phase 0 implementation.

## Phase 0 Follow-Up — 2026-05-11 20:15 ET

### A. Audit Log Validation: PROVEN
- Path: `logs/llm_routing_audit.jsonl`
- `_log_audit()` in `scripts/local_llm.py:43-62` writes JSONL entries
- File auto-created on first audited call (directory auto-created via `mkdir(parents=True)`)
- Fields: ts, caller, process_type, model, provider, latency_ms, status, fallback, phase
- No prompts, secrets, holdings, or account details are logged
- Failures are logged (status=local_failed, all_failed)
- Validation command:
  ```bash
  ls -lh logs/llm_routing_audit.jsonl && tail -5 logs/llm_routing_audit.jsonl | python3 -m json.tool --no-ensure-ascii
  ```

### B. System-Health local.available Fix: FIXED
- **Root cause:** `health_check()` in `llm_router.py` called `_call_local()` with a generate probe.
  Two bugs: (1) success threshold required >20 chars but probe asked for 1-word answer;
  (2) qwen3:14b with thinking takes 50-120s, far exceeding the 30s effective HTTP timeout.
- **Fix:** Replaced generate-based probe with `/api/ps` model residency check (~50ms).
  If qwen3:14b is resident in VRAM, `local.available=true`. This matches how `gpu-status` works.
- **Trade-off:** Residency check confirms model is loaded, not that generation works.
  Generation latency issues are surfaced separately by `verify_llm_providers.py` live probes.

### C. Provider Verification Upgrade: DONE
- `scripts/verify_llm_providers.py` now reports four-level status per provider:
  - **configured** — key/env present
  - **reachable** — endpoint/network responds
  - **usable** — tiny live test succeeds (Ollama generate, OpenAI/Anthropic chat)
  - **degraded** — quota/billing/rate-limit/auth error
- Anthropic is NOT marked usable if API returns billing/credit/auth errors
- No secrets printed (keys redacted to first 8 + last 4 chars)
- Summary table at bottom shows all four dimensions per provider
- Validation command:
  ```bash
  .venv/bin/python scripts/verify_llm_providers.py
  ```

### D. qwen3:14b Generation Latency — OBSERVATION (superseded by Phase 0B)

See Phase 0B below for full diagnosis.

## Phase 0B — Local LLM Diagnostics — 2026-05-11 20:47 ET

### Root Cause: Queue Saturation, NOT Model Failure

**qwen3:14b is healthy.** The observed 83-120s latency was caused entirely by
**Ollama request queue saturation** from concurrent cron processes.

### Evidence — Clean Queue Direct Tests

| Test | think:false | num_predict | eval_count | eval_time | total_time | tok/s |
|------|------------|-------------|------------|-----------|------------|-------|
| Tiny (/no_think ok) | yes | 3 | 3 | 0.19s | 12.2s | 15.8 |
| 2-sentence | yes | 100 | 35 | 3.3s | 5.6s | 10.5 |
| Agent-sized (w/ /no_think) | yes | 300 | 114 | 11.5s | 14.6s | 9.9 |
| Agent-sized (no prefix) | yes | 300 | 125 | 12.6s | 16.2s | 9.9 |
| **Thinking ENABLED** | **no** | 800 | **460** | **48.0s** | **57.0s** | 9.6 |

Key findings:
- **9.6-15.8 tok/s** — normal for qwen3:14b Q4_K_M on Intel Arc B50 Vulkan
- **`think:false` works correctly** — reduces token count from 460 to ~120 for same prompt
- **No `<think>` tags** in any output (DB confirmed across 8 recent results)
- **`/no_think` prefix has no measurable effect** — `think:false` API param is sufficient
- **local_llm.generate() works**: 11.9s on clean queue, audit logged as `status=ok`

### Queue Saturation Mechanism

```
Cron: */5 20-23 * * 1-5  process_watchlist_agent_jobs.py --limit 25
```

- Fires every 5 minutes → ~25 LLM calls per invocation
- Each call takes ~15s with think:false, ~57s with thinking enabled
- Processes accumulate because they can't finish before the next cron fires
- **Peak observed: 10 concurrent processes** (from 20:00-20:45, none finished)
- Ollama serializes generation → queue depth × 15s per request = catastrophic wait
- Fallback chain catches this: local timeout → Claude (billing fail) → Grok (succeeds in 13-28s)

### Diagnostic Fields Added to llm_router.py

`_call_local()` now captures Ollama internals on success:
- `eval_count`, `prompt_eval_count`, `eval_duration_s`, `prompt_eval_duration_s`
- `total_duration_s`, `tok_per_s`
- Written to `logs/llm_router.log` as `ollama_*` fields when provider=local

### Provider Status (at time of testing)

| Provider | Status | Detail |
|----------|--------|--------|
| Local (qwen3:14b) | **USABLE** (when queue is clear) | 9.9 tok/s, ~15s per agent call |
| OpenAI | USABLE | 1.84s probe response |
| Anthropic | DEGRADED | Credit balance too low (HTTP 400) |
| xAI/Grok | CONFIGURED | Actively handling fallback traffic (~$0.0002/call) |

### Recommendations for Phase 1

1. ~~**Add flock guard to watchlist cron**~~ — Done in Phase 0C
2. **Reduce cron frequency** during evening hours (*/15 instead of */5) — optional, flock handles it
3. **No model changes needed** — qwen3:14b performance is normal at 9.9 tok/s
4. **`think:false` is working** — no `/no_think` prefix needed in prompts
5. **Anthropic billing** should be resolved before relying on Claude as fallback
6. **Grok fallback is functioning** and keeping the system operational during queue saturation

## Phase 0C — Cron Concurrency Guard — 2026-05-11 21:01 ET

### Change: flock guard on all process_watchlist_agent_jobs.py cron entries

**Lock file:** `/tmp/tradeai_watchlist_agent_jobs.lock`
**Mechanism:** `flock -n -E 99` (non-blocking, exit 99 on conflict)
**Skip logging:** On conflict, writes timestamped `[flock] skipped` to `logs/watchlist_agent_jobs.log`

### Cron entries modified (4 of 4)

| Schedule | Hours | Limit | Status |
|----------|-------|-------|--------|
| `*/15 6-19 * * 1-5` | Market hours | --limit 10 | flock guarded |
| `*/5 20-23 * * 1-5` | Evening | --limit 25 | flock guarded |
| `*/5 0-5 * * 2-6` | Overnight | --limit 25 | flock guarded |
| `*/10 * * * 0,6` | Weekend | --limit 15 | flock guarded |

### Crontab backup
- Pre-change backup: `docs/v4_1_discovery/crontab_pre_phase0c.txt`
- Also at: `/tmp/crontab_backup_20260511_phase0c.txt`

### Flock contention test: PASSED
- First lock acquired → second flock correctly returned exit code 99
- Skip logging confirmed functional

### Validation
- `crontab -l | grep process_watchlist_agent` — all 4 entries show `flock -n -E 99`
- No overlapping agent processes observed after installation
- `system-health`: `local.available=true`, `latency=0.001s`
- `gpu-status`: qwen3:14b resident, 9.94 GB VRAM used
- Safety: `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, holdings $1,191,456

### What was NOT changed
- No model routing changes
- No model pulls
- No cron frequency changes (still */5 evening, */15 market hours)
- No --limit reductions
- No broker, holdings, or execution changes

## Phase 0D — Runtime Cap and Batch-Size Control — 2026-05-11 21:25 ET

### Evidence prompting this change
- Phase 0C flock is working: `[flock] skipped` logged at 21:10 and 21:15
- But the 21:05 process ran for 14+ minutes, monopolizing Ollama for one batch
- Single-job runtime remains too long for other callers to get queue time

### Changes applied

**1. Runtime cap:** `timeout 12m` added inside flock, outside the Python process.
- flock acquires lock → timeout caps the job at 12 minutes → Python runs inside both
- If job exceeds 12m, timeout sends SIGTERM (exit 124) and logs `[timeout]` entry
- flock is outside timeout so lock-skip detection (exit 99) still works independently

**2. Batch size reduced to --limit 10 across all schedules:**

| Schedule | Hours | Old limit | New limit |
|----------|-------|-----------|-----------|
| `*/15 6-19 * * 1-5` | Market hours | 10 | 10 (unchanged) |
| `*/5 20-23 * * 1-5` | Evening | 25 | **10** |
| `*/5 0-5 * * 2-6` | Overnight | 25 | **10** |
| `*/10 * * * 0,6` | Weekend | 15 | **10** |

**3. Exit code handling:** `rc=$?` captured once, checked for both 99 (flock skip) and 124 (timeout).

### Crontab backup
- Pre-change: `docs/v4_1_discovery/crontab_pre_phase0d.txt`

### Validation
- `crontab -l | grep process_watchlist_agent` — all 4 entries show `flock`, `timeout 12m`, `--limit 10`
- `timeout 2s bash -lc 'sleep 5'` → exit 124 confirmed
- Safety: `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, holdings $1,191,456

### Monitoring commands
```bash
# Check for timeout kills
grep '\[timeout\]' logs/watchlist_agent_jobs.log

# Check for flock skips
grep '\[flock\]' logs/watchlist_agent_jobs.log

# Confirm single-process at any time
ps -ef | grep process_watchlist_agent_jobs.py | grep -v grep | wc -l
```

### What was NOT changed
- No model routing or model pull changes
- No cron frequency changes (still */5 evening, */15 market hours)
- No broker, holdings, or execution changes

## Phase 1 Pilot — gemma3:27b BATCH_OVERNIGHT Test — 2026-05-11 22:00 ET

### Result: CONDITIONAL GO

gemma3:27b was tested as a BATCH_OVERNIGHT model. Full report: `docs/v4_1_phase1_pilot_report.md`

### Key metrics
- **VRAM**: 13.75 GB allocated (75.3% GPU), 4.51 GB CPU spillover
- **Throughput**: 5.3 tok/s (vs qwen3:14b at 9.9 tok/s) — ~53% throughput
- **Pilot script**: `multi_strategy_classifier.py --batch --llm --limit 1` — classified ACH in 99s
- **Restore**: qwen3:14b + nomic-embed-text fully restored (9.94 GB, matching pre-pilot state)

### Method
- Model override via `LOCAL_LLM_MODEL=gemma3:27b` in shell only (not persisted to .env)
- BATCH_OVERNIGHT was NOT changed persistently
- GPU lifecycle: cooldown(qwen) → smoke test(gemma) → pilot run → cooldown(gemma) → warmup(qwen+nomic)

### Next steps for Phase 1 expansion (NOT started)
1. ~~Create `gemma3-overnight` Modelfile~~ — Done in Phase 1B
2. Set `LLM_BATCH_OVERNIGHT=gemma3-overnight` in `.env` (when operator approves)
3. ~~Create lifecycle wrapper script~~ — Done in Phase 1B
4. Run one controlled overnight test with wrapper before expanding

## Phase 1B — Overnight Model Preparation — 2026-05-11 22:09 ET

### Deliverables created

**1. `gemma3-overnight` named model** (via `config/Modelfile.gemma3-overnight`)
- Based on gemma3:27b
- `num_ctx=4096`, `temperature=0.2`, `top_p=0.9`, `num_predict=500`
- Concise classification system prompt
- `keep_alive=0` handled at request time by lifecycle wrapper
- Built: `ollama create gemma3-overnight -f config/Modelfile.gemma3-overnight`
- Verified: `ollama list` shows `gemma3-overnight:latest` (17 GB)

**2. Smoke test: PASSED**
- Prompt: "Classify AAPL: growth, value, or income?"
- Response: "Growth." — 5.5s total, 8.3 tok/s
- VRAM: 13.64 GB (74% GPU), same profile as raw gemma3:27b

**3. `scripts/run_batch_overnight_gemma_pilot.sh` wrapper** (not scheduled)
- Sets `LOCAL_LLM_MODEL=gemma3-overnight` inside script only
- Safety: checks ALPACA_MODE, LLM_DISABLE_LIVE_EXECUTION, holdings guard
- Active hours gate: refuses during 9:30-16:00 ET
- GPU lifecycle: evict qwen → run pilot → unload gemma → restore qwen + nomic
- Fail-closed: exit 2 with manual intervention instructions if restore fails
- Timeout: 10 minutes default
- Logs to: `logs/gemma_overnight_pilot.log`
- Default: `--batch --llm --limit 1`

### What was NOT changed
- `.env` was NOT modified
- `LLM_BATCH_OVERNIGHT` remains unset (defaults to qwen3:14b)
- No cron entries added or modified
- No routing changes to STANDARD, REALTIME, EMBEDDING, or any other process type
- No broker, holdings, or execution changes
- qwen3:14b + nomic-embed-text fully restored (9.94 GB)

### Validation commands for controlled overnight test
```bash
# Run wrapper manually (outside market hours only)
./scripts/run_batch_overnight_gemma_pilot.sh

# Or with more symbols
./scripts/run_batch_overnight_gemma_pilot.sh --limit 5

# Check results
tail -50 logs/gemma_overnight_pilot.log
curl -s http://localhost:7777/api/v2/gpu-status | python3 -m json.tool
```
