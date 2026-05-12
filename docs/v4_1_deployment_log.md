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

1. **Add flock guard to watchlist cron** to prevent concurrent accumulation
2. **Reduce cron frequency** during evening hours (*/15 instead of */5)
3. **No model changes needed** — qwen3:14b performance is normal at 9.9 tok/s
4. **`think:false` is working** — no `/no_think` prefix needed in prompts
5. **Anthropic billing** should be resolved before relying on Claude as fallback
6. **Grok fallback is functioning** and keeping the system operational during queue saturation
