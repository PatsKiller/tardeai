# LLM Fleet Strategy Plan

**Server:** ms01-openclaw, Ubuntu Linux  
**GPU:** Intel Arc Pro B50, 16 GB VRAM, Vulkan backend  
**Date:** May 9, 2026  
**Version:** 3.4.1 — final execution candidate  
**Applies to:** Trade AI v12, Portfolio Intelligence v1.2, OpenClaw, and any future tooling on ms01-openclaw  
**Status:** Ready for Claude Code Implementation Order steps 2–15 after all required tests pass. Burn-in A, Burn-in B, fcntl removal, and qwen3:1.7b removal remain operator-approved stages only.

**Execution hold:** Blocked until Phase 2 cron freeze observation window clears. Earliest eligible date: **2026-05-14**. See `docs/project/PHASE2_EARLY_INSTALL_FREEZE_AND_OBSERVATION_RUNBOOK.md`.

---

## Compliance Posture — Read First

This system is designed and operated for **personal use only** on a single owner's accounts.

### Hard invariants

| Invariant | Rule |
|-----------|------|
| One beneficial user | The only person trading through this system is the owner. No client accounts, no pooled funds, no shared logins. |
| No copy-trading or signals service | Outputs are not sold, distributed, or re-broadcast as recommendations to anyone else. |
| No execution for others | The system does not connect to anyone else's brokerage account. |
| No paid alerts or model portfolios | No commercial dissemination of trade ideas, scores, rankings, or performance results. |
| Paper-only until validation gate clears | Live trading remains disabled in code until the 6-month paper validation criteria are met and explicit operator approval is given. |
| Compliance review before commercialization | Crossing any of the above boundaries requires securities counsel review before code changes. |

**Why this matters:** the system stays on the "trader-for-self" side of the line. Any change that turns it into paid advice, client account management, copy-trading, trade execution for others, or public recommendations changes the regulatory profile completely.

---

## Table of Contents

1. Purpose & Scope
2. Process Type Taxonomy
3. Complete Fleet
4. Toll Gate — Two-Phase Burn-in
5. Routing Telemetry
6. `.env` Architecture
7. `llm_config.py` — Router and Policy Hub
8. `local_llm.py` — Execution Wrapper and Audit Owner
9. Fallback Policy Matrix
10. Provider Slug Verification
11. Kill Switches
12. Broker Regime Abstraction
13. Trade AI v12 Process Type Assignments
14. Gemma 4 Integration
15. Embedding Upgrade Plan
16. Deprecate qwen3:1.7b
17. Required Tests
18. Implementation Order
19. Claude Code Prompt
20. Fleet Reference

---

# 1. Purpose & Scope

This document defines the LLM fleet and routing architecture for ms01-openclaw.

It is **project-agnostic**. The process type taxonomy, `.env` model mapping, router policy, execution wrapper, audit logging, fallback behavior, kill switches, and burn-in gates apply to any current or future tool running on the server.

Current projects using this architecture:

- Trade AI v12 — trading intelligence and paper-trading pipeline
- Portfolio Intelligence v1.2 — portfolio analytics and agent layer
- OpenClaw — conversational agent gateway for Telegram and WhatsApp
- RAG intelligence library — embeddings and semantic retrieval

### Core principle

Scripts never hardcode model names. They declare the kind of work they are doing.

The router resolves the model.  
The execution wrapper executes the request.  
The audit table records the outcome.  
The `.env` block is the source of truth for model assignments.

Changing the LLM fleet should require editing the `.env` model map and passing the provider verification and test gates, not editing every script.

---

# 2. Process Type Taxonomy

The system uses seven canonical process types. These describe the **nature of the work**, not the project or script name.

| Process Type | Constant | Description | Latency | Cost Sensitivity |
|---|---|---|---|---|
| REALTIME | `REALTIME` | User-facing response. Telegram, OpenClaw, live dashboard, interactive request. | <5s | UX priority |
| STANDARD | `STANDARD` | Active-hours pipeline work. Scoring, classification, enrichment, normal agent work. | <30s | Medium |
| BATCH_OVERNIGHT | `BATCH_OVERNIGHT` | Time-insensitive deep jobs. Strategy classification, thesis review, pattern extraction. | No limit | Local preferred |
| MEDIA_CONTENT | `MEDIA_CONTENT` | Lightweight prose, summaries, transcript scoring, query generation, narrative polish. | <10s | Medium |
| EMBEDDING | `EMBEDDING` | Vector creation for RAG and semantic search. Never generation. | Batch | Local only |
| CRITICAL_CLOUD | `CRITICAL_CLOUD` | High-stakes retirement, tax, SSDI/IRMAA, CIO synthesis, legal/compliance reasoning. | No limit | Budget-exempt |
| CLOUD_FALLBACK | `CLOUD_FALLBACK` | Secondary cloud option after local or primary provider failure. | <60s | Medium |

### Decision tree

```
Is a human waiting?                                        → REALTIME
Part of a scheduled active-hours pipeline?                 → STANDARD
Runs overnight or in a batch window?                       → BATCH_OVERNIGHT
Generating prose, summaries, or content?                   → MEDIA_CONTENT
Converting text to vectors?                                → EMBEDDING
Financial decision, retirement, or tax-impact reasoning?   → CRITICAL_CLOUD
Fallback when primary inference is unavailable?            → CLOUD_FALLBACK
```

---

# 3. Complete Fleet

## 3a. Local Models — Ollama on Intel Arc Pro B50

| Model | Pull Command | VRAM Estimate | Process Type | Status |
|---|---|---|---|---|
| `qwen3:14b` | already installed | ~10 GB Q4 | STANDARD, REALTIME | Keep — primary |
| `qwen3-embedding:8b` | `ollama pull qwen3-embedding:8b` | ~5 GB | EMBEDDING | Install — upgrade |
| `gemma4:26b-a4b` | `ollama pull gemma4:26b-a4b` | ~15 GB | BATCH_OVERNIGHT | Install |
| `gemma4:e4b` | `ollama pull gemma4:e4b` | ~3 GB | MEDIA_CONTENT | Install |
| `qwen3:1.7b` | already installed | ~1 GB | none | Deprecated, rollback only |
| `nomic-embed-text` | already installed | minimal | none | Remove after re-index 100% confirmed |

### VRAM cohabitation rule

`gemma4:26b-a4b` and `qwen3:14b` cannot both safely remain loaded on a 16 GB GPU.

```
qwen3:14b            persistent during active hours
gemma4:26b-a4b       overnight only, keep_alive=0
gemma4:e4b           lightweight, content tasks
qwen3-embedding:8b   embedding jobs only
```

### Morning preload requirement

After overnight Gemma jobs unload, `qwen3:14b` may not be resident in VRAM. The first 6 AM request can otherwise pay a 30–60 second cold start.

Schedule a **5:30 AM preload cron** that sends a one-token request to `qwen3:14b`.

## 3b. Cloud Providers

| Provider | Model ID | Process Type | Use |
|---|---|---|---|
| Anthropic | `claude-sonnet-4-6` | CRITICAL_CLOUD | Retirement, tax, SSDI/IRMAA, CIO synthesis |
| xAI | `grok-4.3` | CLOUD_FALLBACK | First cloud fallback |
| OpenAI | `gpt-5-mini` | CLOUD_FALLBACK_2, OpenClaw | Tertiary fallback and OpenClaw conversational model |
| ChatGPT manual | n/a | not wired | Operator second opinion only |

### Provider rule

Cloud model IDs must be verified before deployment using `scripts/verify_llm_providers.py`. Any `.env` change touching cloud slugs is blocked until verification exits 0.

---

# 4. Toll Gate — Two-Phase Burn-in

## Current toll gate

`local_llm.py` currently uses `fcntl.flock(LOCK_EX)` on `/tmp/ollama_llm_gate.lock`.

That serialized LLM calls safely in the CPU era. With GPU-backed Ollama and native queueing, it is now too blunt:

- exactly one request at a time
- no native queue depth visibility
- stale lock risk
- 600-second lock wait is not the right HTTP-service abstraction

## Why two burn-ins are required

If `fcntl` remains enabled, requests are serialized **before they hit Ollama**. That means Ollama's native queue is not exercised.

- **Burn-in A** validates routing, audit, provider slugs, costs, cold starts, and safety while `fcntl` remains active.
- **Burn-in B** bypasses `fcntl` in a controlled test-only window to validate Ollama queue behavior.

## Burn-in A — Safe baseline

**Duration:** 2 full market days plus 2 overnight batches  
**Config:**

```bash
LLM_DEPLOYMENT_PHASE=baseline_fcntl
LLM_BYPASS_FCNTL=false
```

**Validates:**

- routing coverage
- provider slugs
- audit logging
- cloud fallback chain
- critical-cloud behavior
- daily spend tracking
- qwen3 morning preload
- no stale file locks
- no audit-write failures

### Burn-in A pass criteria

```
Audit table receives rows from every script
verify_llm_providers.py exits 0
logs/llm_audit_failures.log has zero new failures
qwen3 preload completes <60s
first real post-preload request <5s
no CRITICAL_CLOUD silent degradation
daily cloud spend within LLM_DAILY_BUDGET_LIMIT
no stale fcntl lock events
```

## Burn-in B — Queue validation

**Duration:** ~2 hours, off-hours  
**Config:**

```bash
LLM_DEPLOYMENT_PHASE=queue_shadow
LLM_BYPASS_FCNTL=true
LLM_DISABLE_CLOUD_FALLBACK=true
```

`LLM_BYPASS_FCNTL=true` is refused unless `LLM_DEPLOYMENT_PHASE=queue_shadow`.

Burn-in B uses `scripts/queue_stress_test.py`.

## queue_stress_test.py

```python
# scripts/queue_stress_test.py
"""
Controlled queue stress test for Burn-in B.

PRECONDITIONS:
  LLM_DEPLOYMENT_PHASE=queue_shadow
  LLM_BYPASS_FCNTL=true
  LLM_DISABLE_CLOUD_FALLBACK=true

This script is operator-run only.
Claude Code must deploy it but must NOT execute it.
"""

import os
import time
import concurrent.futures

from scripts import local_llm
from scripts.llm_config import STANDARD, MEDIA_CONTENT

assert os.getenv("LLM_DEPLOYMENT_PHASE") == "queue_shadow", \
    "Set LLM_DEPLOYMENT_PHASE=queue_shadow before running"

assert os.getenv("LLM_BYPASS_FCNTL") == "true", \
    "Set LLM_BYPASS_FCNTL=true before running"

assert os.getenv("LLM_DISABLE_CLOUD_FALLBACK") == "true", \
    "Phase 1 requires LLM_DISABLE_CLOUD_FALLBACK=true"


def _fire(idx, process_type, phase, max_attempts=1):
    return local_llm.execute(
        process_type=process_type,
        prompt=f"Stress test {idx}",
        script="queue_stress_test.py",
        cron_job_name=phase,
        max_attempts=max_attempts,
    )


def phase_1_queue_capacity():
    """30 concurrent STANDARD calls with cloud fallback disabled.
    Measures local queue behavior only.
    """
    phase = "phase_1_queue_capacity"
    print("Phase 1: Queue capacity — cloud fallback disabled")

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        futures = [
            ex.submit(_fire, i, STANDARD, phase, 1)
            for i in range(30)
        ]

        results = []
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(("ok", f.result(timeout=600)))
            except Exception as e:
                results.append(("err", str(e)[:100]))

    ok = sum(1 for r in results if r[0] == "ok")
    print(f"Phase 1 completed: {ok}/30")
    print("Errors may be expected if Ollama returns 503 under load.")


def phase_2_fallback_behavior():
    """Deterministic fallback test using simulated Ollama 503.
    LLM_SIMULATE_OLLAMA_503 is honored only during queue_shadow.
    """
    phase = "phase_2_fallback_behavior"
    print("Phase 2: Fallback behavior — deterministic simulated 503")

    os.environ["LLM_DISABLE_CLOUD_FALLBACK"] = "false"
    os.environ["LLM_SIMULATE_OLLAMA_503"] = "true"

    try:
        result = local_llm.execute(
            process_type=STANDARD,
            prompt="Fallback test",
            script="queue_stress_test.py",
            cron_job_name=phase,
            max_attempts=3,
        )

        print(
            f"Fallback succeeded: model={result['model']}, "
            f"cost=${result['cost']:.4f}"
        )
    finally:
        os.environ["LLM_SIMULATE_OLLAMA_503"] = "false"
        os.environ["LLM_DISABLE_CLOUD_FALLBACK"] = "true"


def phase_3_model_swap():
    """Cloud fallback stays disabled.
    Tests local model swap behavior under MAX_LOADED_MODELS=1.
    """
    phase = "phase_3_model_swap"
    print("Phase 3: Model swap — cloud fallback disabled")

    assert os.getenv("LLM_DISABLE_CLOUD_FALLBACK") == "true"

    _fire(2000, STANDARD, phase, 1)       # warm qwen3
    _fire(2001, MEDIA_CONTENT, phase, 1)  # swap to gemma4:e4b
    _fire(2002, STANDARD, phase, 1)       # swap back to qwen3

    print("Phase 3 completed. Verify model_cold_start_ms populated on swap calls.")


if __name__ == "__main__":
    phase_1_queue_capacity()
    phase_2_fallback_behavior()
    phase_3_model_swap()

    print("\nVerification queries:")
    print("""
-- Phase 1 cloud spend must be zero
SELECT COALESCE(SUM(cost_estimate_usd), 0)
FROM llm_routing_audit
WHERE deployment_phase = 'queue_shadow'
  AND script = 'queue_stress_test.py'
  AND cron_job_name = 'phase_1_queue_capacity'
  AND fallback_chain && ARRAY['anthropic','xai','openai'];

-- Phase 2 fallback chain must be populated
-- Expected: fallback_chain = ['ollama', 'xai'] (xai = LLM_CLOUD_FALLBACK provider)
SELECT request_id, fallback_chain, resolved_model, provider, cost_estimate_usd
FROM llm_routing_audit
WHERE deployment_phase = 'queue_shadow'
  AND script = 'queue_stress_test.py'
  AND cron_job_name = 'phase_2_fallback_behavior'
  AND array_length(fallback_chain, 1) >= 2;

-- Phase 3 cold start must be populated on the two swap calls
SELECT request_id, resolved_model, model_cold_start_ms
FROM llm_routing_audit
WHERE deployment_phase = 'queue_shadow'
  AND script = 'queue_stress_test.py'
  AND cron_job_name = 'phase_3_model_swap'
  AND model_cold_start_ms IS NOT NULL;
""")
```

## Burn-in B pass criteria

```
Phase 1 cloud spend = $0.00
ollama_overhead_ms p95 < 1s under load
model_cold_start_ms < 60s on first call after swap
503 rate < 1% under sustained load, unless deliberately saturated during capacity test
zero GPU OOM events
zero CPU fallback events
Phase 2 fallback_chain length >= 2 (typical: ['ollama','xai'])
Phase 3 model_cold_start_ms populated on swap calls (2001, 2002)
```

## Production cutover

Only after Burn-in A and Burn-in B pass:

1. Remove `fcntl.flock()` from `local_llm.py`.
2. Replace lock-timeout fallback with HTTP 503 detection.
3. Set `LLM_DEPLOYMENT_PHASE=no_fcntl`, `LLM_BYPASS_FCNTL=false`.
4. Keep the 600-second HTTP timeout.
5. Monitor first full market day.
6. If stable, set `LLM_DEPLOYMENT_PHASE=post_cutover`.

---

# 5. Routing Telemetry

The audit table is the prerequisite for everything else. Every logical LLM request writes exactly one audit row, written by `local_llm.py`, not `llm_config.py`.

## Audit table schema

```sql
CREATE TABLE IF NOT EXISTS llm_routing_audit (
  id BIGSERIAL PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  request_id UUID NOT NULL,
  prompt_hash TEXT,

  script TEXT NOT NULL,
  process_type TEXT NOT NULL,
  resolved_model TEXT NOT NULL,
  provider TEXT NOT NULL,

  lock_wait_ms INTEGER,
  ollama_overhead_ms INTEGER,
  provider_latency_ms INTEGER,
  model_cold_start_ms INTEGER,
  total_latency_ms INTEGER NOT NULL,

  status TEXT NOT NULL,
  fallback_reason TEXT,
  fallback_chain TEXT[],
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cost_estimate_usd NUMERIC(10,6),
  critical_cloud_flag BOOLEAN NOT NULL DEFAULT FALSE,
  http_status_code INTEGER,
  error_message TEXT,

  caller_pid INTEGER,
  cron_job_name TEXT,
  deployment_phase TEXT NOT NULL DEFAULT 'baseline_fcntl'
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp
  ON llm_routing_audit (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_process_type
  ON llm_routing_audit (process_type, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_phase
  ON llm_routing_audit (deployment_phase, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_status
  ON llm_routing_audit (status)
  WHERE status != 'success';

CREATE INDEX IF NOT EXISTS idx_audit_request_id
  ON llm_routing_audit (request_id);
```

## Idempotent migration from v3.3 / v3.4

```sql
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'llm_routing_audit'
      AND column_name = 'ollama_queue_wait_ms'
  ) THEN
    ALTER TABLE llm_routing_audit
      RENAME COLUMN ollama_queue_wait_ms TO ollama_overhead_ms;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'llm_routing_audit'
      AND column_name = 'ollama_overhead_ms'
  ) THEN
    ALTER TABLE llm_routing_audit
      ADD COLUMN ollama_overhead_ms INTEGER;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'llm_routing_audit'
      AND column_name = 'model_cold_start_ms'
  ) THEN
    ALTER TABLE llm_routing_audit
      ADD COLUMN model_cold_start_ms INTEGER;
  END IF;
END $$;

COMMENT ON COLUMN llm_routing_audit.ollama_overhead_ms IS
'Wall-clock time not accounted for by Ollama total_duration. Includes HTTP transit, local scheduling, Ollama scheduling, and other overhead. Not pure queue wait.';

COMMENT ON COLUMN llm_routing_audit.model_cold_start_ms IS
'Model load time from Ollama load_duration, populated only when load_duration exceeds warm-cache threshold.';
```

Run this migration twice during verification. Both runs must succeed.

## Metric meanings

| Metric | Meaning |
|---|---|
| `lock_wait_ms` | Time waiting on the old `fcntl` lock. Null or 0 when bypassed/removed. |
| `ollama_overhead_ms` | Wall-clock time not accounted for by Ollama `total_duration`. Includes HTTP transit, local scheduling, Ollama scheduling, and other overhead. Not pure queue wait. |
| `provider_latency_ms` | Provider-reported inference/generation time when local; raw HTTP wall-clock for cloud. |
| `model_cold_start_ms` | Ollama `load_duration`, populated only when load time exceeds warm-cache threshold. |
| `total_latency_ms` | End-to-end wall-clock time for the logical LLM request. |

## Dashboard queries

```sql
-- p95 overhead and cold start by process type during queue_shadow
SELECT process_type,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ollama_overhead_ms) AS p95_overhead_ms,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY model_cold_start_ms)
         FILTER (WHERE model_cold_start_ms IS NOT NULL) AS p95_cold_start_ms,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_total_ms,
       COUNT(*) AS calls
FROM llm_routing_audit
WHERE deployment_phase = 'queue_shadow'
  AND status = 'success'
GROUP BY process_type;

-- 503 rate by phase and process type
SELECT deployment_phase,
       process_type,
       COUNT(*) AS total,
       SUM((http_status_code = 503)::int) AS blocked_503,
       ROUND(100.0 * SUM((http_status_code = 503)::int) / COUNT(*), 2) AS pct_503
FROM llm_routing_audit
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY deployment_phase, process_type;

-- Cloud spend, UTC day
SELECT provider,
       COUNT(*) AS calls,
       SUM(cost_estimate_usd) AS total_usd,
       SUM(CASE WHEN critical_cloud_flag THEN cost_estimate_usd ELSE 0 END) AS critical_usd,
       SUM(CASE WHEN NOT critical_cloud_flag THEN cost_estimate_usd ELSE 0 END) AS discretionary_usd
FROM llm_routing_audit
WHERE timestamp >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
  AND provider != 'ollama'
GROUP BY provider;

-- Phase 1 cloud spend must be zero
SELECT COALESCE(SUM(cost_estimate_usd), 0) AS phase1_cloud_spend_must_be_zero
FROM llm_routing_audit
WHERE deployment_phase = 'queue_shadow'
  AND script = 'queue_stress_test.py'
  AND cron_job_name = 'phase_1_queue_capacity'
  AND fallback_chain && ARRAY['anthropic','xai','openai'];
```

---

# 6. `.env` Architecture

## Production `.env`

```bash
# ==============================================================
# LLM FLEET — ms01-openclaw — v3.4.1
# ==============================================================

# PROCESS TYPE → MODEL ASSIGNMENTS
LLM_REALTIME=qwen3:14b
LLM_STANDARD=qwen3:14b
LLM_BATCH_OVERNIGHT=gemma4:26b-a4b
LLM_MEDIA_CONTENT=gemma4:e4b
LLM_EMBEDDING=qwen3-embedding:8b

# Cloud models
LLM_CRITICAL_CLOUD=claude-sonnet-4-6
LLM_CLOUD_FALLBACK=grok-4.3
LLM_CLOUD_FALLBACK_2=gpt-5-mini
LLM_OPENCLAW=gpt-5-mini

# Batch fallback — never cloud
LLM_BATCH_OVERNIGHT_FALLBACK=qwen3:14b

# Daily cloud budget, UTC reset
LLM_DAILY_BUDGET_LIMIT=2.00

# Kill switches
LLM_FORCE_LOCAL_ONLY=false
LLM_DISABLE_CLOUD_FALLBACK=false
LLM_DISABLE_LIVE_EXECUTION=true
LLM_DISABLE_CRITICAL_CLOUD=false

# Deployment phase
LLM_DEPLOYMENT_PHASE=baseline_fcntl
# valid: baseline_fcntl | queue_shadow | no_fcntl | post_cutover

# fcntl bypass, refused unless phase is queue_shadow
LLM_BYPASS_FCNTL=false

# audit-failure alert threshold
LLM_AUDIT_FAILURE_ALERT_THRESHOLD=5

# Database
DATABASE_URL=
DB_HOST=localhost
DB_PORT=5432
DB_NAME=trade_ai
DB_USER=trade_ai
DB_PASSWORD=<your-password>

# API keys
ANTHROPIC_API_KEY=<rotate-immediately>
OPENAI_API_KEY=<rotate-immediately>
XAI_API_KEY=<your-key>

# Broker regime
BROKER_MARGIN_REGIME=legacy_pdt
# valid: legacy_pdt | intraday_margin | cash
```

## `.env.example` only — test flags

Do not put these in production `.env`.

```bash
# TEST ONLY — do not copy into production .env.
# Forces audit-write failure path without touching DB.
LLM_AUDIT_FORCE_FAILURE=false

# TEST ONLY — do not copy into production .env.
# Simulates an Ollama 503 for deterministic fallback testing.
# Honored only when LLM_DEPLOYMENT_PHASE=queue_shadow.
LLM_SIMULATE_OLLAMA_503=false
```

Verification:

```bash
grep -n "LLM_AUDIT_FORCE_FAILURE" .env
grep -n "LLM_SIMULATE_OLLAMA_503" .env
```

Expected: no output.

---

# 7. `llm_config.py` — Router and Policy Hub

`llm_config.py` resolves models and fallback policy only. It does **not** execute LLM calls and does **not** write audit rows.

```python
# scripts/llm_config.py

import os
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

REALTIME = "REALTIME"
STANDARD = "STANDARD"
BATCH_OVERNIGHT = "BATCH_OVERNIGHT"
MEDIA_CONTENT = "MEDIA_CONTENT"
EMBEDDING = "EMBEDDING"
CRITICAL_CLOUD = "CRITICAL_CLOUD"
CLOUD_FALLBACK = "CLOUD_FALLBACK"

_ENV_MAP = {
    REALTIME: "LLM_REALTIME",
    STANDARD: "LLM_STANDARD",
    BATCH_OVERNIGHT: "LLM_BATCH_OVERNIGHT",
    MEDIA_CONTENT: "LLM_MEDIA_CONTENT",
    EMBEDDING: "LLM_EMBEDDING",
    CRITICAL_CLOUD: "LLM_CRITICAL_CLOUD",
    CLOUD_FALLBACK: "LLM_CLOUD_FALLBACK",
}


def get_model_for(process_type: str) -> str:
    env_key = _ENV_MAP.get(process_type)
    if not env_key:
        raise ValueError(f"Unknown process type: {process_type}")

    model = os.getenv(env_key)
    if not model:
        raise ValueError(f"No model configured for {process_type} ({env_key})")

    if process_type == CRITICAL_CLOUD and _truthy("LLM_DISABLE_CRITICAL_CLOUD"):
        raise RuntimeError("LLM_DISABLE_CRITICAL_CLOUD is active")

    if process_type == CRITICAL_CLOUD:
        return model

    if not is_cloud_model(model):
        if not is_ollama_available(model):
            return get_local_fallback(process_type)

    return model


def max_attempts_for(process_type: str) -> int:
    if process_type == EMBEDDING:
        return 6
    if process_type == BATCH_OVERNIGHT:
        return 4
    return 3


def get_fallback_action(process_type: str, http_status: int, attempt: int) -> dict:
    if process_type == CRITICAL_CLOUD:
        return {
            "action": "fail",
            "model": None,
            "delay_seconds": 0,
            "reason": "CRITICAL_CLOUD does not fall back; operator review required",
        }

    if process_type == EMBEDDING:
        if attempt < 5:
            return {
                "action": "retry",
                "model": None,
                "delay_seconds": min(2 ** attempt, 30),
                "reason": "EMBEDDING retries locally only",
            }
        return {
            "action": "fail",
            "model": None,
            "delay_seconds": 0,
            "reason": "EMBEDDING max retries exhausted",
        }

    cloud_blocked = _truthy("LLM_FORCE_LOCAL_ONLY") or _truthy("LLM_DISABLE_CLOUD_FALLBACK")

    if process_type == REALTIME:
        if attempt == 1 and not cloud_blocked:
            return {
                "action": "fallback_cloud",
                "model": os.getenv("LLM_CLOUD_FALLBACK"),
                "delay_seconds": 0,
                "reason": "REALTIME prioritizes UX",
            }

    if process_type == STANDARD:
        if attempt == 1:
            return {
                "action": "retry",
                "model": None,
                "delay_seconds": 5,
                "reason": "STANDARD: one local retry",
            }
        if attempt == 2 and not cloud_blocked:
            return {
                "action": "fallback_cloud",
                "model": os.getenv("LLM_CLOUD_FALLBACK"),
                "delay_seconds": 0,
                "reason": "STANDARD: cloud fallback after local retry",
            }

    if process_type == BATCH_OVERNIGHT:
        if attempt < 3:
            return {
                "action": "retry",
                "model": None,
                "delay_seconds": 30 * (2 ** attempt),
                "reason": "BATCH_OVERNIGHT: retry locally",
            }
        return {
            "action": "fallback_local",
            "model": os.getenv("LLM_BATCH_OVERNIGHT_FALLBACK", "qwen3:14b"),
            "delay_seconds": 0,
            "reason": "BATCH_OVERNIGHT: local fallback only",
        }

    if process_type == MEDIA_CONTENT:
        if attempt == 1:
            return {
                "action": "retry",
                "model": None,
                "delay_seconds": 10,
                "reason": "MEDIA_CONTENT: one local retry",
            }
        if budget_remaining() > 0 and not cloud_blocked:
            return {
                "action": "fallback_cloud",
                "model": os.getenv("LLM_CLOUD_FALLBACK"),
                "delay_seconds": 0,
                "reason": "MEDIA_CONTENT: cloud fallback, budget allows",
            }
        return {
            "action": "fail",
            "model": None,
            "delay_seconds": 0,
            "reason": "MEDIA_CONTENT: budget exhausted or cloud blocked",
        }

    if process_type == CLOUD_FALLBACK:
        if attempt == 1:
            return {
                "action": "fallback_cloud",
                "model": os.getenv("LLM_CLOUD_FALLBACK_2"),
                "delay_seconds": 0,
                "reason": "CLOUD_FALLBACK: secondary cloud provider",
            }
        return {
            "action": "fail",
            "model": None,
            "delay_seconds": 0,
            "reason": "CLOUD_FALLBACK: both cloud providers failed",
        }

    return {
        "action": "fail",
        "model": None,
        "delay_seconds": 0,
        "reason": f"No fallback action for {process_type}, attempt={attempt}",
    }


def get_standard_model():
    return get_model_for(STANDARD)


def get_realtime_model():
    return get_model_for(REALTIME)


def get_overnight_model():
    return get_model_for(BATCH_OVERNIGHT)


def get_media_model():
    return get_model_for(MEDIA_CONTENT)


def get_embedding_model():
    return get_model_for(EMBEDDING)


def get_critical_model():
    return get_model_for(CRITICAL_CLOUD)


def get_best_model():
    return get_model_for(STANDARD)


def is_cloud_model(model: str) -> bool:
    return any(model.startswith(p) for p in ("claude", "grok", "openai", "gpt", "anthropic"))


def provider_for(model: str) -> str:
    if model.startswith("claude") or model.startswith("anthropic"):
        return "anthropic"
    if model.startswith("grok"):
        return "xai"
    if model.startswith("gpt") or model.startswith("openai"):
        return "openai"
    return "ollama"


def is_ollama_available(model_name: str) -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return any(model_name in m for m in models)
    except Exception:
        return False


def get_local_fallback(process_type: str) -> str:
    if process_type == BATCH_OVERNIGHT:
        return os.getenv("LLM_BATCH_OVERNIGHT_FALLBACK", "qwen3:14b")
    return os.getenv("LLM_STANDARD", "qwen3:14b")


def db_connect():
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg2.connect(url)

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD"),
    )


def budget_remaining() -> float:
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(SUM(cost_estimate_usd), 0)
                    FROM llm_routing_audit
                    WHERE timestamp >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                      AND NOT critical_cloud_flag
                """)
                spent = float(cur.fetchone()[0])

        limit = float(os.getenv("LLM_DAILY_BUDGET_LIMIT", "2.00"))
        return max(0.0, limit - spent)
    except Exception:
        return 0.0


def _truthy(name: str) -> bool:
    return os.getenv(name, "false").lower() == "true"
```

---

# 8. `local_llm.py` — Execution Wrapper and Audit Owner

`local_llm.py` executes requests, handles fallback, handles `fcntl`, and writes one audit row per logical LLM request.

Key behaviors:

- Owns audit writing.
- Writes audit in `finally`.
- Writes durable audit-failure log if DB write fails.
- Honors `LLM_BYPASS_FCNTL` only during `queue_shadow`.
- Honors `LLM_AUDIT_FORCE_FAILURE` only if explicitly exported in a test context.
- Honors `LLM_SIMULATE_OLLAMA_503` only during `queue_shadow`.

```python
# scripts/local_llm.py

import os
import time
import uuid
import json
import hashlib
import requests
from datetime import datetime

from scripts import llm_config as cfg

OLLAMA_URL = "http://localhost:11434/api/generate"
AUDIT_FAILURES_LOG = "logs/llm_audit_failures.log"


class _LLMError(Exception):
    def __init__(self, msg, http_code=0):
        super().__init__(msg)
        self.http_code = http_code


def execute(process_type: str, prompt: str, *,
            script: str,
            cron_job_name: str = None,
            max_attempts: int = None) -> dict:
    request_id = str(uuid.uuid4())
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:32]

    if max_attempts is None:
        max_attempts = cfg.max_attempts_for(process_type)

    fallback_chain = []
    record = _new_audit(request_id, prompt_hash, script, process_type, cron_job_name)

    try:
        attempt = 0
        current_model = cfg.get_model_for(process_type)
        record["resolved_model"] = current_model

        while attempt < max_attempts:
            attempt += 1

            provider = cfg.provider_for(current_model)
            record["provider"] = provider
            fallback_chain.append(provider)
            record["fallback_chain"] = fallback_chain.copy()

            t_lock_start = time.monotonic()
            lock_handle = _maybe_acquire_fcntl()
            record["lock_wait_ms"] = int((time.monotonic() - t_lock_start) * 1000)

            try:
                t_request = time.monotonic()
                response_data, http_code = _send_request(current_model, prompt)
                total_http_ms = int((time.monotonic() - t_request) * 1000)

                if cfg.is_cloud_model(current_model):
                    record["ollama_overhead_ms"] = None
                    record["provider_latency_ms"] = total_http_ms
                    record["model_cold_start_ms"] = None
                else:
                    inference_ns = response_data.get("total_duration", 0)
                    load_ns = response_data.get("load_duration", 0)

                    inference_ms = inference_ns // 1_000_000
                    load_ms = load_ns // 1_000_000

                    record["provider_latency_ms"] = inference_ms
                    record["ollama_overhead_ms"] = max(0, total_http_ms - inference_ms)
                    record["model_cold_start_ms"] = load_ms if load_ms > 50 else None

                record["status"] = "success"
                record["http_status_code"] = http_code
                record["prompt_tokens"] = response_data.get("prompt_eval_count")
                record["completion_tokens"] = response_data.get("eval_count")
                record["cost_estimate_usd"] = _estimate_cost(current_model, response_data)

                return {
                    "text": response_data.get("response", ""),
                    "tokens": record["completion_tokens"] or 0,
                    "cost": record["cost_estimate_usd"] or 0.0,
                    "model": current_model,
                    "request_id": request_id,
                }

            except _LLMError as e:
                action = cfg.get_fallback_action(process_type, e.http_code, attempt)
                record["fallback_reason"] = action["reason"]
                record["http_status_code"] = e.http_code

                if action["action"] == "fail":
                    record["status"] = "error"
                    record["error_message"] = str(e)[:500]
                    raise RuntimeError(f"LLM call failed: {action['reason']}")

                if action["action"] == "retry":
                    if action["delay_seconds"]:
                        time.sleep(action["delay_seconds"])
                    continue

                if action["action"] in ("fallback_cloud", "fallback_local"):
                    current_model = action["model"]
                    record["resolved_model"] = current_model
                    continue

            finally:
                _release_fcntl(lock_handle)

        record["status"] = "error"
        record["error_message"] = f"max_attempts ({max_attempts}) exhausted"
        raise RuntimeError(record["error_message"])

    finally:
        record["total_latency_ms"] = int((time.monotonic() - record.pop("_t_start")) * 1000)
        _write_audit_row_safe(record)


def _new_audit(request_id, prompt_hash, script, process_type, cron_job_name):
    return {
        "request_id": request_id,
        "prompt_hash": prompt_hash,
        "script": script,
        "process_type": process_type,
        "resolved_model": None,
        "provider": "unknown",
        "lock_wait_ms": None,
        "ollama_overhead_ms": None,
        "provider_latency_ms": None,
        "model_cold_start_ms": None,
        "total_latency_ms": None,
        "status": "pending",
        "fallback_reason": None,
        "fallback_chain": [],
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_estimate_usd": None,
        "critical_cloud_flag": process_type == cfg.CRITICAL_CLOUD,
        "http_status_code": None,
        "error_message": None,
        "caller_pid": os.getpid(),
        "cron_job_name": cron_job_name,
        "deployment_phase": os.getenv("LLM_DEPLOYMENT_PHASE", "baseline_fcntl"),
        "_t_start": time.monotonic(),
    }


def _maybe_acquire_fcntl():
    if os.getenv("LLM_BYPASS_FCNTL", "false").lower() == "true":
        if os.getenv("LLM_DEPLOYMENT_PHASE") != "queue_shadow":
            raise RuntimeError(
                "LLM_BYPASS_FCNTL=true is only allowed when "
                "LLM_DEPLOYMENT_PHASE=queue_shadow"
            )
        return None

    import fcntl
    fh = open("/tmp/ollama_llm_gate.lock", "w")
    fcntl.flock(fh, fcntl.LOCK_EX)
    fh.write(f"{os.getpid()}:{time.time()}\n")
    fh.flush()
    return fh


def _release_fcntl(handle):
    if handle is None:
        return
    import fcntl
    fcntl.flock(handle, fcntl.LOCK_UN)
    handle.close()


def _send_request(model, prompt):
    if cfg.is_cloud_model(model):
        return _send_cloud(model, prompt)
    return _send_ollama(model, prompt)


def _send_ollama(model, prompt):
    if os.getenv("LLM_SIMULATE_OLLAMA_503", "false").lower() == "true":
        if os.getenv("LLM_DEPLOYMENT_PHASE") != "queue_shadow":
            raise RuntimeError(
                "LLM_SIMULATE_OLLAMA_503=true is only allowed during queue_shadow"
            )
        raise _LLMError("Simulated Ollama 503 for fallback test", http_code=503)

    r = requests.post(
        OLLAMA_URL,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=600,
    )

    if r.status_code == 503:
        raise _LLMError("Ollama queue full", http_code=503)

    if r.status_code != 200:
        raise _LLMError(
            f"Ollama HTTP {r.status_code}: {r.text[:200]}",
            http_code=r.status_code,
        )

    return r.json(), r.status_code


def _send_cloud(model, prompt):
    raise NotImplementedError("Cloud provider dispatch implemented in repo")


def _estimate_cost(model, response):
    if not cfg.is_cloud_model(model):
        return 0.0
    return 0.0


def _write_audit_row_safe(record):
    if os.getenv("LLM_AUDIT_FORCE_FAILURE", "false").lower() == "true":
        try:
            raise RuntimeError("LLM_AUDIT_FORCE_FAILURE=true")
        except Exception as e:
            _log_audit_failure(record, e, forced=True)
            _check_audit_failure_rate_and_alert()
        return

    try:
        _write_audit_row(record)
    except Exception as e:
        _log_audit_failure(record, e, forced=False)
        _check_audit_failure_rate_and_alert()


def _log_audit_failure(record, error, forced=False):
    print(f"[local_llm] audit write FAILED: {error}")

    os.makedirs(os.path.dirname(AUDIT_FAILURES_LOG), exist_ok=True)

    line = json.dumps({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "request_id": record.get("request_id"),
        "script": record.get("script"),
        "process_type": record.get("process_type"),
        "error": str(error)[:500],
        "forced_failure": forced,
        "record": {k: v for k, v in record.items() if k != "_t_start"},
    }, default=str)

    with open(AUDIT_FAILURES_LOG, "a") as f:
        f.write(line + "\n")


def _check_audit_failure_rate_and_alert():
    try:
        threshold = int(os.getenv("LLM_AUDIT_FAILURE_ALERT_THRESHOLD", "5"))
        cutoff = time.time() - 3600
        recent = 0

        if os.path.exists(AUDIT_FAILURES_LOG):
            with open(AUDIT_FAILURES_LOG) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(
                            entry["timestamp"].replace("Z", "")
                        ).timestamp()
                        if ts > cutoff:
                            recent += 1
                    except Exception:
                        continue

        if recent > threshold:
            from scripts.telegram_notify import send_alert
            send_alert(
                f"LLM audit-write failures: {recent} in the last hour. "
                f"Check {AUDIT_FAILURES_LOG}."
            )
    except Exception:
        pass


def _write_audit_row(record):
    sql = """
      INSERT INTO llm_routing_audit
        (request_id, prompt_hash, script, process_type, resolved_model, provider,
         lock_wait_ms, ollama_overhead_ms, provider_latency_ms, model_cold_start_ms,
         total_latency_ms, status, fallback_reason, fallback_chain,
         prompt_tokens, completion_tokens, cost_estimate_usd,
         critical_cloud_flag, http_status_code, error_message,
         caller_pid, cron_job_name, deployment_phase)
      VALUES
        (%(request_id)s, %(prompt_hash)s, %(script)s, %(process_type)s,
         %(resolved_model)s, %(provider)s,
         %(lock_wait_ms)s, %(ollama_overhead_ms)s, %(provider_latency_ms)s,
         %(model_cold_start_ms)s, %(total_latency_ms)s,
         %(status)s, %(fallback_reason)s, %(fallback_chain)s,
         %(prompt_tokens)s, %(completion_tokens)s, %(cost_estimate_usd)s,
         %(critical_cloud_flag)s, %(http_status_code)s, %(error_message)s,
         %(caller_pid)s, %(cron_job_name)s, %(deployment_phase)s)
    """

    with cfg.db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, record)
        conn.commit()
```

---

# 9. Fallback Policy Matrix

| Process Type | Attempt 1 | Attempt 2 | Attempt 3+ | Cloud Allowed | Max Attempts |
|---|---|---|---|---|---|
| REALTIME | Cloud fallback immediately | n/a | n/a | Yes | 3 |
| STANDARD | Retry local | Cloud fallback | Execute fallback / fail | Yes | 3 |
| BATCH_OVERNIGHT | Retry local | Retry local | Local fallback to STANDARD model | No | 4 |
| MEDIA_CONTENT | Retry local | Cloud fallback if budget allows | Fail | Yes, if budget | 3 |
| EMBEDDING | Retry local | Retry local | Up to 5 retries, then fail | No | 6 |
| CRITICAL_CLOUD | Cloud primary | Fail loud on cloud failure | n/a | Already cloud | 3 |
| CLOUD_FALLBACK | Try `_2` provider | Fail | n/a | n/a | 3 |

### Hard rules

```
EMBEDDING never falls back to cloud.
CRITICAL_CLOUD never falls back to local.
BATCH_OVERNIGHT never escalates to cloud.
LLM_FORCE_LOCAL_ONLY blocks cloud calls.
LLM_DISABLE_CLOUD_FALLBACK blocks fallback cloud calls.
LLM_DISABLE_CRITICAL_CLOUD makes CRITICAL_CLOUD fail loud.
```

---

# 10. Provider Slug Verification

Run before any deployment that touches provider slugs.

Expected current IDs:

```
Anthropic: claude-sonnet-4-6
xAI:       grok-4.3
OpenAI:    gpt-5-mini
```

Verification command:

```bash
python3 scripts/verify_llm_providers.py
```

Gate:

```
exit code must be 0
no provider failures
no skipped required providers
```

Any failure blocks deployment.

---

# 11. Kill Switches

| Variable | Effect |
|---|---|
| `LLM_FORCE_LOCAL_ONLY=true` | Blocks all cloud calls. CRITICAL_CLOUD fails loud. |
| `LLM_DISABLE_CLOUD_FALLBACK=true` | Blocks fallback cloud calls. CRITICAL_CLOUD still allowed unless separately disabled. |
| `LLM_DISABLE_LIVE_EXECUTION=true` | Blocks live order routing. Must remain true until validation gate clears. |
| `LLM_DISABLE_CRITICAL_CLOUD=true` | Makes CRITICAL_CLOUD raise immediately. |
| `LLM_BYPASS_FCNTL=true` | Bypasses file lock only during `queue_shadow`. |
| `LLM_AUDIT_FORCE_FAILURE=true` | Test-only. Do not place in production `.env`. |
| `LLM_SIMULATE_OLLAMA_503=true` | Test-only. Honored only during `queue_shadow`. |

---

# 12. Broker Regime Abstraction

```bash
BROKER_MARGIN_REGIME=legacy_pdt
```

Allowed values: `legacy_pdt`, `intraday_margin`, `cash`.

No code, dashboard, strategy, or risk gate hardcodes PDT rules. All day-trade and margin behavior reads `BROKER_MARGIN_REGIME`.

| Component | Behavior |
|---|---|
| `risk_gate.py` | day-trade and equity checks |
| `proposal_lifecycle.py` | intraday close classification |
| dashboard header | active regime banner |
| strategy YAMLs | `requires_pdt` strategy availability |
| Telegram `/status` | reports active regime |

Switch-over requires operator confirmation with broker.

---

# 13. Trade AI v12 Process Type Assignments

## Active hours

| Task | Script | Process Type | Model |
|---|---|---|---|
| Screener scoring + catalyst classification | `trade_ai_orchestrator.py` | STANDARD | `qwen3:14b` |
| Proposal 4-chunk LLM review | `proposal_llm_reviewer.py` | STANDARD | `qwen3:14b` |
| Incubator LLM screening | `incubator_llm_screener.py` | STANDARD | `qwen3:14b` |
| Agent analysis | `process_watchlist_agent_jobs.py` | STANDARD | `qwen3:14b` |
| Fast enrichment labels | `portfolio_orchestrator.py` | STANDARD | `qwen3:14b` |
| Telegram/OpenClaw realtime | OpenClaw gateway | REALTIME | `qwen3:14b` |
| CIO synthesis | `cio_synthesis.py` | CRITICAL_CLOUD | `claude-sonnet-4-6` |
| Alex retirement | `alex_retirement_advisor.py` | CRITICAL_CLOUD | `claude-sonnet-4-6` |
| OpenClaw conversational | OpenClaw config | separate | `gpt-5-mini` |

## Overnight

| Task | Script | Process Type | Model |
|---|---|---|---|
| Strategy classification | `multi_strategy_classifier.py` | BATCH_OVERNIGHT | `gemma4:26b-a4b` |
| Post-trade thesis review | `strategy_weekly_review.py` | BATCH_OVERNIGHT | `gemma4:26b-a4b` |
| Pattern extraction | `pattern_extractor.py` | BATCH_OVERNIGHT | `gemma4:26b-a4b` |
| Aegis phases 1–7 | `aegis_synthesis.py` | STANDARD | `qwen3:14b` |
| Aegis retirement phase | `aegis_synthesis.py` | CRITICAL_CLOUD | `claude-sonnet-4-6` |
| Holdings refresh | `holdings_llm_refresh.py` | STANDARD | `qwen3:14b` |
| RAG re-indexing | `rag_indexer.py` | EMBEDDING | `qwen3-embedding:8b` |
| Monthly retirement report | `alex_retirement_advisor.py --monthly-report` | CRITICAL_CLOUD | `claude-sonnet-4-6` |

## Media / content

| Task | Script | Process Type | Model |
|---|---|---|---|
| YouTube transcript quality | `topic_curator.py` | MEDIA_CONTENT | `gemma4:e4b` |
| News summaries | `news_ingestion.py` | MEDIA_CONTENT | `gemma4:e4b` |
| Topic query generation | `topic_ingestion.py --curate` | MEDIA_CONTENT | `gemma4:e4b` |
| Morning brief prose | `morning_digest.py` | MEDIA_CONTENT | `gemma4:e4b` |

---

# 14. Gemma 4 Integration

```bash
ollama pull gemma4:e4b
ollama pull gemma4:26b-a4b
ollama list
```

Create overnight Modelfile:

```bash
cat > /tmp/Modelfile.gemma4-overnight << 'EOF'
FROM gemma4:26b-a4b
PARAMETER keep_alive 0
PARAMETER num_ctx 8192
EOF

ollama create gemma4-overnight -f /tmp/Modelfile.gemma4-overnight
```

Then set:

```bash
LLM_BATCH_OVERNIGHT=gemma4-overnight
```

Do not install `gemma4:31b` on the 16 GB GPU.

---

# 15. Embedding Upgrade Plan

Target:

```bash
LLM_EMBEDDING=qwen3-embedding:8b
```

Migration:

```bash
ollama pull qwen3-embedding:8b
python3 scripts/rag_indexer.py --full-reindex
python3 scripts/rag_indexer.py --status
```

Only after 100% verified:

```bash
ollama rm nomic-embed-text
```

Never mix old `nomic-embed-text` vectors and new `qwen3-embedding:8b` vectors in the same active index.

---

# 16. Deprecate qwen3:1.7b

Status: deprecated, rollback only.

Removal requires all gates:

```
router deployed
grep -R "qwen3:1.7b" returns zero production references
OpenClaw agents confirmed not using it
Burn-in A passed
Burn-in B passed
fcntl removed and post-cutover stable
morning preload verified
```

Then:

```bash
ollama rm qwen3:1.7b
ollama list
```

---

# 17. Required Tests

v3.4.1 requires 15 tests.

```
tests/test_fallback_loop.py
  test_batch_overnight_executes_local_fallback
  test_embedding_retries_up_to_five_times_then_fails
  test_standard_retries_once_then_cloud
  test_critical_cloud_fails_loud_no_fallback

tests/test_fallback_policy.py
  test_cloud_fallback_tries_secondary
  test_killswitch_force_local_only_blocks_cloud
  test_killswitch_disable_critical_cloud_raises
  test_realtime_immediate_cloud_fallback

tests/test_audit_integrity.py
  test_provider_field_always_set
  test_ollama_overhead_calculation
  test_model_cold_start_populated_on_swap
  test_audit_failure_writes_to_failures_log
  test_audit_force_failure_flag_skips_db
  test_bypass_fcntl_refused_outside_queue_shadow

tests/test_queue_stress_safety.py
  test_phase1_rows_are_tagged_separately
  test_simulated_503_only_allowed_in_queue_shadow
```

Run:

```bash
pytest \
  tests/test_fallback_loop.py \
  tests/test_fallback_policy.py \
  tests/test_audit_integrity.py \
  tests/test_queue_stress_safety.py
```

Expected: `15 passed`.

No implementation step proceeds unless all tests pass.

---

# 18. Implementation Order

| Step | Action | Gate |
|---:|---|---|
| 1 | Rotate `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` | Operator-only, immediate |
| 2 | Deploy audit table and idempotent migration | No behavior change |
| 3 | Deploy `llm_config.py` | Tests pass |
| 4 | Deploy `local_llm.py` | Tests pass |
| 5 | Run required pytest suite | 15/15 pass |
| 6 | Run provider verification | Zero failures |
| 7 | Update production `.env` | Do not include test-only flags |
| 8 | Configure Ollama systemd override | fcntl stays active |
| 9 | Re-run provider verification | Zero failures |
| 10 | Pull `qwen3-embedding:8b` and `gemma4:e4b` | Safe |
| 11 | Schedule 5:30 AM qwen3 preload cron | Verified |
| 12 | Run full RAG re-index after hours | Must reach 100% |
| 13 | Remove `nomic-embed-text` after verified 100% | Not before |
| 14 | Pull `gemma4:26b-a4b` and create Modelfile | Weekend or off-hours |
| 15 | Update overnight/media scripts to new process helpers | Tests pass |
| 16 | Burn-in A | Operator-run, 2 market days + 2 overnight batches |
| 17 | Burn-in B | Operator-run, queue_shadow stress |
| 18 | Remove `fcntl` | Operator approval required |
| 19 | Monitor first market day post-cutover | Rollback if metrics regress |
| 20 | Remove qwen3:1.7b | Only after all milestones clear |

Claude Code is authorized for **steps 2–15 only**. Claude Code must not execute Burn-in A, Burn-in B, fcntl removal, or qwen3:1.7b removal.

**Execution hold:** Steps 2–15 are blocked until the Phase 2 cron freeze observation window clears (earliest 2026-05-14).

---

# 19. Claude Code Prompt

Use this prompt verbatim for implementation.

```text
You are executing the Trade AI v12 / Portfolio Intelligence / OpenClaw LLM Fleet
upgrade per docs/llm_fleet_strategy_v3_4_1.md on ms01-openclaw.

============================================================
HARD RULES
============================================================

1. BACKUP BEFORE CHANGE — NO EXCEPTIONS

Before modifying any file, copy it to a session-scoped backup directory.

Create at session start:

BACKUP_DIR=/home/johnclaw/trade-ai-v12-rebuild/.backups/$(date -u +%Y%m%dT%H%M%SZ)_v3_4_1_llm_fleet
mkdir -p "$BACKUP_DIR"

For every file before edit:

cp -p <file> "$BACKUP_DIR/<relative-path-preserving-structure>"
ls -la "$BACKUP_DIR/<relative-path-preserving-structure>"

For .env:

cp -p .env "$BACKUP_DIR/.env.pre_v3_4_1"

For Postgres:

pg_dump --schema-only trade_ai > "$BACKUP_DIR/full_schema.sql"

For systemd override:

cp -p /etc/systemd/system/ollama.service.d/override.conf \
  "$BACKUP_DIR/ollama.override.conf" 2>/dev/null || \
  echo "no existing override" > "$BACKUP_DIR/ollama.override.conf.NOEXIST"

For cron:

crontab -l > "$BACKUP_DIR/crontab.pre_v3_4_1"

2. ROLLBACK CONTRACT

For every implementation step, write to:

$BACKUP_DIR/ROLLBACK_STEPS.md

Each entry must include:
- forward command
- rollback command
- verification command

3. TESTS ARE BLOCKING

Before any implementation step, run:

pytest tests/test_fallback_loop.py tests/test_fallback_policy.py tests/test_audit_integrity.py tests/test_queue_stress_safety.py

Expected: 15 passed.

If any test fails, halt.

4. AUDIT TABLE FIRST

Do not deploy llm_config.py or local_llm.py changes before the audit table and
idempotent migration exist.

5. PROVIDER VERIFICATION IS BLOCKING

Run scripts/verify_llm_providers.py before and after .env changes touching
model slugs. If it exits non-zero, halt.

6. TEST-ONLY FLAGS

Do not put these in production .env:

LLM_AUDIT_FORCE_FAILURE
LLM_SIMULATE_OLLAMA_503

They may appear in .env.example and docs only. Code must default both to false
if absent.

7. NO LIVE TRADING TOGGLES

Do not set LLM_DISABLE_LIVE_EXECUTION=false. Do not touch any live execution
guard.

8. DO NOT EXECUTE BURN-IN OR CUTOVER

This session stops after Implementation Order step 15. Do not run:
- Burn-in A
- Burn-in B
- queue_stress_test.py
- fcntl removal
- qwen3:1.7b removal

9. MIGRATION HYGIENE

Audit table migration must be idempotent. If the DB already has
ollama_queue_wait_ms, rename it. If it already has ollama_overhead_ms, do
nothing. Add COMMENT ON COLUMN statements for ollama_overhead_ms and
model_cold_start_ms. Run the migration twice during verification — both runs
must succeed.

10. COMPLIANCE INVARIANTS

Do not make any change that:
- enables live trading
- connects client brokerage accounts
- broadcasts trade recommendations externally
- removes paper-only enforcement
- disables human approval

============================================================
WHAT TO DO
============================================================

Execute Implementation Order steps 2 through 15 only.

After each step, output exactly this structure:

✓ Step N complete: <description>
Backup: $BACKUP_DIR/<files modified>
Verification: <what was verified and result>
Rollback: see $BACKUP_DIR/ROLLBACK_STEPS.md step N

Commit at the end of each logical step:
git add -A
git commit -m "v3.4.1 step <N>: <description>"

Do not commit if any verification gate failed in that step.

============================================================
ABORT CONDITIONS
============================================================

Stop immediately and surface to operator if:
- backup verification fails (cp -p didn't produce the expected file)
- pytest fails (any of the 15 tests)
- provider verification fails
- audit migration fails or is not idempotent on second run
- production .env would include LLM_AUDIT_FORCE_FAILURE or LLM_SIMULATE_OLLAMA_503
- qwen3:1.7b disappears unexpectedly (means another session is racing)
- nomic-embed-text disappears before re-index reaches 100%
- any live trading guard would be changed
- any compliance invariant would be touched
```

---

# 20. Fleet Reference

```
PROCESS TYPE      MODEL                 MAX ATTEMPTS      USE
REALTIME          qwen3:14b             3                 user-facing
STANDARD          qwen3:14b             3                 pipeline workhorse
BATCH_OVERNIGHT   gemma4:26b-a4b        4                 deep overnight
MEDIA_CONTENT     gemma4:e4b            3                 summaries/prose
EMBEDDING         qwen3-embedding:8b    6                 vectors only
CRITICAL_CLOUD    claude-sonnet-4-6     3                 high-stakes, fail loud
CLOUD_FALLBACK    grok-4.3              3                 local fallback
FALLBACK_2        gpt-5-mini            n/a               tertiary
```

Infrastructure:

```
Ollama:
  OLLAMA_NUM_PARALLEL=1
  OLLAMA_MAX_QUEUE=20
  OLLAMA_MAX_LOADED_MODELS=1

Telemetry:
  llm_routing_audit
  ollama_overhead_ms
  provider_latency_ms
  model_cold_start_ms
  total_latency_ms

Audit owner:
  local_llm.py

Routing owner:
  llm_config.py

Stress test:
  queue_shadow only
  LLM_BYPASS_FCNTL=true
  Phase 1 cloud fallback disabled
  Phase 2 deterministic simulated 503
  Phase 3 model swap

Kill switches:
  LLM_FORCE_LOCAL_ONLY
  LLM_DISABLE_CLOUD_FALLBACK
  LLM_DISABLE_LIVE_EXECUTION
  LLM_DISABLE_CRITICAL_CLOUD

Test-only flags:
  LLM_AUDIT_FORCE_FAILURE
  LLM_SIMULATE_OLLAMA_503
  not allowed in production .env
```

Removal rules:

```
nomic-embed-text:
  remove only after qwen3-embedding re-index is 100% verified

qwen3:1.7b:
  remove only after Burn-in A, Burn-in B, fcntl cutover, and post-cutover stability

fcntl:
  remove only after Burn-in B passes and operator explicitly approves
```

Compliance invariants:

```
Personal use only
One beneficial user
No commercialization
No client accounts
No copy-trading
Paper-only until validation gate
Human approval required before any live trading consideration
```

---

# Final Status

```
Version: v3.4.1
Status: Final execution candidate
Architecture changes vs v3.4: none
Compliance changes vs v3.4: none
Risk posture: improved
Tests required: 15/15
Claude Code scope: steps 2–15 only
Burn-in A/B: operator-run only
fcntl cutover: operator approval required
```

After this v3.4.1 document is reviewed, execute with Claude Code for **steps 2–15 only**.

Execution is blocked until Phase 2 cron freeze observation window clears (earliest 2026-05-14). See `docs/project/PHASE2_EARLY_INSTALL_FREEZE_AND_OBSERVATION_RUNBOOK.md`.
