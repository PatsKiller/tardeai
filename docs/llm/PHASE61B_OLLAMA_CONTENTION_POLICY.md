# Phase 61B — Ollama Contention Policy

**Date:** 2026-06-01
**Status:** COMPLETE

## Policy

| Rule | Value |
|------|-------|
| Max concurrent high-model jobs | 1 |
| Default pilot num_ctx | 4096 (was 8192) |
| Pre-flight model warm | Required before execution |
| Model unload before swap | Explicit unload via keep_alive=0 |
| Low-contention test window | 10:00–14:00 ET (mid-day, no overnight) |
| Retry policy | 2 retries with 30s delay |
| Cold-start handling | Warm model with tiny prompt first |
| Fallback | gemma3:4b for dry-run summaries only |
| Gemma 4 | NOT routed — canary-only future phase |
| File lock | /tmp/high_llm_execution.lock (flock) |
