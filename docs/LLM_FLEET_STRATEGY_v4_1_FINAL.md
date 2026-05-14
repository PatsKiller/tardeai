# LLM Fleet Strategy v4.1 — Final Execution Revision

**Server:** ms01-openclaw, Ubuntu Linux
**GPU:** Intel Arc Pro B50, **16 GB GDDR6 dedicated VRAM** (224 GB/s, PCIe 5.0 x8), Vulkan backend
**Power:** 70W TBP (typical 50-55W operating)
**Network:** Air-gapped private LAN
**Date:** 2026-05-11
**Status:** Architecture document — FINAL EXECUTION READY. Phase 0 may proceed after gates; Phases 1-4 remain gated and should not be treated as pre-approved.
**Supersedes:** v3.4.1 (selected sections) and v4.0
**Final revision:** 2026-05-11 — adds integration guardrails, source-of-truth reconciliation, backup verification, RAG A/B baseline, alert-dispatch integration, and safer rollout order.


---

## Final Revision Header — What Changed in This Final Version

**Purpose:** This version keeps the original v4.1 direction and promotes the accepted review changes into final execution requirements so the original developer can implement safely against the *current* Trade AI v12 project state.

**Primary final execution decisions:**

1. **Phase 0 is approved conditionally** after all gates pass.
2. **Phase 1 is not automatically approved.** It remains optional and should only proceed after Phase 0 telemetry is clean and the operator explicitly approves it.
3. **`scripts/local_llm_config.py` remains the existing LLM configuration hub unless live code proves otherwise.** Any new `scripts/llm_config.py` must be a thin process-type wrapper or extension, not a competing source of truth.
4. **Cloud provider names and fallback order must be runtime-discovered from the current `.env` and existing config files.** Do not assume `grok-4.3`, `gpt-5-mini`, or any specific provider string exists.
5. **Backup commands and paths must be verified from the live script before use.** Do not assume `scripts/full_system_backup.py` supports all flags shown in this plan.
6. **RAG embedding migration requires an A/B baseline before changing defaults.** A 100% reindex alone is not a quality test.
7. **GPU/OOM failures must route through the central alert dispatcher.** Do not create another silent log-only failure channel.
8. **Service names must be detected, not assumed.** The plan must not restart `portfolio-server.service` unless that unit actually exists.

> **Implementation-note style:** Inline notes marked `FINAL IMPLEMENTATION NOTE` are intentionally left in this file for the original developer. They are binding execution guidance, not optional commentary.

---

## Document Purpose

This document defines the LLM fleet, routing architecture, GPU lifecycle management, and phased rollout for ms01-openclaw. **This annotated revision does not change the strategic goal; it adds implementation guardrails so the work aligns with the current project codebase and docs.**

**FINAL IMPLEMENTATION NOTE:** Treat this as a safer v4.1 implementation plan, not a green light to run all phases. Phase approval remains explicit and sequential.

**v4.1 Final** revises three things from the v4.1 draft:

1. **Phase 1 default model changed from `gemma4:26b-a4b` to `gemma3:27b`** — better hardware fit, longer context window (128K vs need for >8K), mature dense architecture, real production track record. The MoE `gemma4:26b-a4b` is at 18 GB on disk and would force aggressive Q3 quantization on a 16 GB card with no soak time on Intel Arc + Vulkan.
2. **Daytime test protocol added** — `LLM_OVERRIDE_ACTIVE_HOURS=true` enables one-shot testing during market hours with auto-restoration of qwen3:14b after the test.
3. **gemma4:26b-a4b revisit reminder set for 2026-08-11** (3 months out) — Appendix D and operator log entry. By then: MoE-on-Vulkan optimization should mature in Ollama, gemma4 ecosystem feedback should be public, and v4.1 will have its own audit baseline for comparison.

This is an **architecture and strategy document**. The companion file `CLAUDE_CODE_PROMPT_LLM_v4_1_FINAL.md` contains the annotated executable plan.

---

## Compliance Posture — Unchanged

Personal-use only. One beneficial user. No copy-trading, no signals service, no execution for others, no paid alerts. Paper-only until validation gate clears. Compliance review before commercialization.

---

## What Changed from v4.0 / v4.1 Draft — Read This

| Item | v4.0 | v4.1 Draft | v4.1 Final | Why |
|---|---|---|---|---|
| GPU VRAM model | UMA shared (wrong) | 16 GB GDDR6 dedicated | 16 GB GDDR6 dedicated | Factual correction |
| Phase 1 model | gemma4:26b-a4b | gemma4:26b-a4b | **gemma3:27b** | Fits better, mature, 128K context |
| Pre-execution gates | Freeze window check | Backup verification | Backup verification | Backup is real safety |
| GPU lifecycle | Single preload cron | First-class subsystem | First-class subsystem | Real lifecycle management |
| Daytime test protocol | Not specified | Not specified | **Explicit override + auto-restore** | Operator needs to test pre-market or weekends |
| Phase 0 observation | 48h | 24h | 24h | Backup-first allows fast rollback |
| Phase 1 observation | 7 days | 7 days | 7 days | Unchanged — model swap risk |
| Phase 2 observation | 7 days | 48h | 48h | Re-index validation is binary |
| Phase 3 observation | 7 days | 24h | 24h | Lowest-risk phase |
| Phase 4 observation | Manual sign-off | Manual sign-off | Manual sign-off | Unchanged |
| Audit writes | Synchronous | Async batched | Async batched | Performance |
| gemma4:26b revisit | Default choice | Fallback only | **Calendar reminder 2026-08-11** | Wait for MoE+Vulkan maturity |
| Total rollout | ~31 days | ~10 days | ~10 days | Risk-proportional |

---

## Honest GPU Assessment — Read This Before Phase 1

**Your card:** Intel Arc Pro B50, 16 GB GDDR6, 224 GB/s bandwidth, 70W TBP, PCIe 5.0 x8, Vulkan backend on Ubuntu via Mesa 25.2.8.

### Capacity table

| Model | On Disk | VRAM (Q4_K_M est.) | Coexistence with qwen3:14b (~10 GB) |
|---|---|---|---|
| `qwen3:14b` | ~9 GB | ~10 GB | self |
| `qwen3-embedding:8b` | ~5 GB | ~5 GB | ✅ Yes (15 GB total, 1 GB headroom — tight but OK) |
| `gemma4:e4b` | ~9.6 GB | ~3-4 GB Q4 | ✅ Yes (~13-14 GB total, OK) |
| `gemma3:27b` | ~17 GB BF16 | **~14-15 GB Q4_K_M** | ❌ NO — forces swap (resident alone with headroom) |
| `gemma4:26b-a4b` MoE | **18 GB** | Requires Q3 to fit | ❌ NO — and forces aggressive quantization |

### Why gemma3:27b is the right Phase 1 choice

1. **Fits comfortably at Q4_K_M.** ~14-15 GB resident, 1-2 GB VRAM headroom for context expansion. The 8K-context OOM risk is much lower than gemma4:26b.
2. **128K context window** vs 32K on qwen3:14b. Overnight strategy classification benefits from longer context for multi-symbol thesis review.
3. **Released March 2025** — 14 months mature as of deployment. Real production track record on Vulkan, llama.cpp, and Ollama. Bug fixes and quantization tuning are stable.
4. **Dense architecture** — straightforward on Vulkan/Intel Arc. No MoE expert routing complexity. Most performance optimization in Ollama and llama.cpp targets dense models first.
5. **Strong reasoning benchmarks.** Chatbot Arena Elo 1338, competitive with Llama-405B on text reasoning. Real capability win vs qwen3:14b for batch tasks.

### Phase 1 risks (mitigated, not eliminated)

- **Context-length OOM at 32K+.** Q4 footprint of 14-15 GB on 16 GB card means very long contexts may still OOM. The 8K-context OOM test in Phase 1.5 validates the typical case.
- **Mid-day swap disruption.** `gate_batch_overnight()` refuses BATCH_OVERNIGHT during 9:30 AM – 4:00 PM ET unless explicitly overridden.
- **Cold-start tax.** Every overnight job pays ~30-60s loading gemma3:27b plus ~30-60s reloading qwen3:14b afterward. The morning preload cron handles the daily case.

### gemma4:26b-a4b deferred to 2026-08-11

Documented in Appendix D as a future evaluation, not abandoned. Re-evaluate when:
- Ollama has 2+ minor releases with MoE-on-Vulkan optimizations
- gemma4 production-deployment writeups exist for Intel Arc class hardware
- v4.1 has 30+ days of audit baseline data for direct comparison

If the 2026-08-11 review shows gemma4:26b is mature and offers a measurable quality lift, it becomes Phase 6.

---

## Table of Contents

1. Architecture Principles
2. Process Type Taxonomy
3. Fleet Roster — Final
4. GPU Lifecycle Subsystem
5. **Daytime Test Protocol (NEW in v4.1 Final)**
6. LiteLLM Integration — Two Options
7. Sequenced Rollout
8. Backup-First Deployment Policy
9. `.env` Architecture
10. Fallback Policy Matrix
11. Kill Switches
12. Audit Table Design (async batched)
13. Hard Rules
14. Success Criteria per Phase
15. Risk Register
16. Rollback Procedures (Layered)
17. Appendix A — Delta from v3.4.1 and v4.0
18. Appendix B — LiteLLM SDK vs Proxy Decision Matrix
19. Appendix C — Deferred Work
20. **Appendix D — gemma4:26b-a4b Re-evaluation (2026-08-11)**

---

# 1. Architecture Principles

| # | Principle | Implication |
|---|---|---|
| P1 | Scripts declare intent, not models | Process type constants only |
| P2 | `.env` + existing config hub are the source of truth | `.env` stores assignments; `local_llm_config.py`/current hub resolves them |
| P3 | Local-first for STANDARD work | qwen3:14b handles the default path |
| P4 | Cloud-only for CRITICAL_CLOUD work | No local fallback for retirement/tax/CIO |
| P5 | Embedding never escalates to cloud | RAG embeddings local-only |
| P6 | Audit every request | Async batch writes for performance |
| P7 | Budgets are enforced, not advisory | LLM_DAILY_BUDGET_LIMIT blocks calls |
| P8 | Capability gain ships before procedural rigor | Pull model, validate, then test |
| P9 | Rollback in <10 minutes for layers 1-3 | Every phase documents revert |
| P10 | Backup before change, every time | Mandatory pre-deploy backup |
| P11 | Active-hours GPU is sacrosanct | BATCH_OVERNIGHT yields during market hours |
| P12 | Warmup and cooldown are explicit | No implicit model loading |
| P13 | **Daytime testing is opt-in and auto-restoring** | NEW — `LLM_OVERRIDE_ACTIVE_HOURS=true` snapshots state and restores after test |
| P14 | **Prefer mature models over leading-edge** | NEW — production system; new model classes wait for soak time |
| P15 | **No duplicate LLM config hubs** | Any new `llm_config.py` must wrap/extend current `local_llm_config.py`, not replace it silently |
| P16 | **Detect live names, do not assume** | Provider names, service names, backup flags, and model tags must be discovered from the running system |
| P17 | **Quality validation beats completion metrics** | RAG migration must prove retrieval quality, not only 100% completion |

---

# 2. Process Type Taxonomy

Unchanged from v3.4.1. Seven canonical types: REALTIME, STANDARD, BATCH_OVERNIGHT, MEDIA_CONTENT, EMBEDDING, CRITICAL_CLOUD, CLOUD_FALLBACK.

### Decision tree

```
Is a human waiting?                                        -> REALTIME
Part of a scheduled active-hours pipeline?                 -> STANDARD
Runs overnight or in a batch window?                       -> BATCH_OVERNIGHT
Generating prose, summaries, or content?                   -> MEDIA_CONTENT
Converting text to vectors?                                -> EMBEDDING
Financial decision, retirement, or tax-impact reasoning?   -> CRITICAL_CLOUD
Fallback when primary inference is unavailable?            -> CLOUD_FALLBACK
```

---

# 3. Fleet Roster — Final

## 3a. Local Models (Ollama on Arc Pro B50)

| Model | VRAM (Q4) | Process Type | Cohabitation | Status v4.1 Final |
|---|---|---|---|---|
| `qwen3:14b` | ~10 GB | STANDARD, REALTIME | Resident during active hours | KEEP — primary |
| **`gemma3:27b`** (as `gemma3-overnight`) | **~14-15 GB Q4_K_M** | BATCH_OVERNIGHT | Evicts qwen3:14b, keep_alive=0 | **ADD — Phase 1 (CHANGED from gemma4)** |
| `qwen3-embedding:8b` | ~5 GB | EMBEDDING | Coexists with qwen3:14b | ADD — Phase 2 |
| `gemma4:e4b` | ~3-4 GB | MEDIA_CONTENT | Coexists with qwen3:14b | ADD — Phase 3 |
| `qwen3:1.7b` | ~1 GB | rollback only | n/a | KEEP installed — DO NOT delete |
| `nomic-embed-text` | minimal | legacy | n/a | KEEP until Phase 2 verified + 48h |
| ~~`gemma4:26b-a4b`~~ | 18 GB | (deferred) | n/a | **NOT IN v4.1 FINAL — see Appendix D** |

## 3b. Cloud Providers

**Do not hardcode this table during implementation.** The current docs disagree on exact fallback order, and provider/model names may have drifted since prior sessions.

**Required implementation approach:**

1. Read the live `.env`.
2. Read existing routing/config files, especially `scripts/local_llm_config.py`, `scripts/local_llm.py`, and any existing `llm_router.py`/provider helper if present.
3. Print the provider map from `scripts/verify_llm_providers.py` before touching `.env`.
4. Only then add or update process-type variables.

**Expected policy, subject to live verification:**

| Process type | Intended policy | Implementation guardrail |
|---|---|---|
| STANDARD / REALTIME | local qwen3:14b primary | must remain fast and resident during active hours |
| BATCH_OVERNIGHT | gemma3-overnight only after Phase 1 approval | must be gated by active-hours check |
| EMBEDDING | local-only | must never call cloud |
| CRITICAL_CLOUD | cloud-only for retirement/tax/CIO-critical work | must fail loud if disabled/unavailable |
| CLOUD_FALLBACK | cloud fallback for non-critical local failures | provider/model name discovered from live config |

**FINAL IMPLEMENTATION NOTE:** Do not assume `grok-4.3`, `gpt-5-mini`, or `claude-sonnet-4-6` are valid model strings until the provider verification script confirms them.



## 3c. Existing Config Reconciliation — Mandatory Before Phase 0

Before adding `scripts/llm_config.py`, run a live source-of-truth discovery.

```bash
# Find all LLM/model/provider references before changes
grep -R "qwen3:\|gemma\|grok\|claude\|gpt-\|OLLAMA\|local_llm" \
  scripts apps config .env* \
  --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=dist \
  > docs/v4_1_llm_reference_scan_before.txt

# Inspect existing config hub(s)
ls -l scripts/*llm* scripts/*router* 2>/dev/null || true
sed -n '1,240p' scripts/local_llm_config.py 2>/dev/null || true
sed -n '1,240p' scripts/local_llm.py 2>/dev/null || true
```

**Decision rule:**

| Finding | Action |
|---|---|
| `local_llm_config.py` already centralizes model names | extend it or create wrapper constants that import from it |
| `local_llm.py` already owns execution | keep it as execution path; do not introduce a second direct Ollama caller |
| Existing scripts call Ollama directly | record them in a migration list; do not mass-refactor during Phase 0 |
| Existing fallback order differs from this doc | update this doc/deployment log and use the live order |

**FINAL IMPLEMENTATION NOTE:** The original plan correctly says “no hardcoded model names,” but Phase 0 must prove where the current model names actually live before new config files are created.

---

# 4. GPU Lifecycle Subsystem

## Why this exists

A 16 GB card running multiple models requires explicit lifecycle management. Implicit loading leads to cold-start tax at unpredictable times, active-hours disruption, silent OOMs, and no visibility.

v4.1 Final makes lifecycle explicit via `scripts/gpu_lifecycle.py`.

## API surface

```python
# scripts/gpu_lifecycle.py

def warmup(model: str, timeout: int = 90) -> dict:
    """Ensure model is resident. Returns: {model, was_resident, load_time_ms, vram_used_gb, vram_free_gb}"""

def cooldown(model: str = None) -> dict:
    """Unload model from VRAM. If None, unloads all."""

def status() -> dict:
    """Return current GPU state: {resident_models, vram_used_gb, vram_free_gb, vram_total_gb, active_hours}"""

def can_load(model_size_gb: float, current_resident: list = None) -> bool:
    """Returns True if model fits with >= LLM_VRAM_HEADROOM_GB free after load."""

def is_active_hours() -> bool:
    """True during 9:30 AM - 4:00 PM ET on weekdays."""

def gate_batch_overnight() -> None:
    """Raises GPULifecycleError during active hours unless LLM_OVERRIDE_ACTIVE_HOURS=true."""

def check_oom() -> dict:
    """Scrape Ollama logs for OOM events in last 5 min."""

# NEW v4.1 Final: test-mode context manager
def daytime_test(model: str):
    """Context manager for daytime testing. Snapshots resident state, swaps to test model,
    restores resident state on exit. Requires LLM_OVERRIDE_ACTIVE_HOURS=true."""
```

## Cron schedule

```bash
# Warmup qwen3:14b at 5:30 AM for active-hours readiness
30 5 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && \
    .venv/bin/python scripts/gpu_lifecycle.py warmup qwen3:14b \
    >> logs/gpu_warmup.log 2>&1

# Status report every 15 min during active hours
*/15 9-16 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && \
    .venv/bin/python scripts/gpu_lifecycle.py status \
    >> logs/gpu_status.log 2>&1

# OOM detector every 5 min
*/5 * * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && \
    .venv/bin/python scripts/gpu_lifecycle.py check_oom \
    >> logs/gpu_oom.log 2>&1
```

## Integration pattern

Every BATCH_OVERNIGHT script must use the lifecycle gate, but **do not blindly add per-script unload/reload churn to every overnight job.** Start with the highest-value batch scripts and prefer a batch-window lifecycle when multiple jobs run close together.

### Preferred integration pattern — pilot script

```python
from scripts.gpu_lifecycle import gate_batch_overnight, warmup, cooldown
from scripts.local_llm import execute
from scripts.llm_config import BATCH_OVERNIGHT

def main():
    gate_batch_overnight()
    warmup("gemma3-overnight")
    try:
        result = execute(
            process_type=BATCH_OVERNIGHT,
            prompt=prompt,
            script="multi_strategy_classifier.py",
            cron_job_name="overnight_strategy_classify",
        )
    finally:
        cooldown("gemma3-overnight")
        warmup("qwen3:14b")
```

### Preferred integration pattern — batch window

If several overnight scripts run together, wrap the group with a single lifecycle boundary instead of loading/unloading per script:

```bash
.venv/bin/python scripts/gpu_lifecycle.py warmup gemma3-overnight
.venv/bin/python scripts/multi_strategy_classifier.py --batch
.venv/bin/python scripts/strategy_weekly_review.py --batch
.venv/bin/python scripts/gpu_lifecycle.py cooldown gemma3-overnight
.venv/bin/python scripts/gpu_lifecycle.py warmup qwen3:14b
```

**FINAL IMPLEMENTATION NOTE:** The current overnight schedule contains many jobs. Repeated per-script GPU swapping can create cold-start tax and avoidable risk. Pilot first, then expand.

## API endpoint

**FINAL IMPLEMENTATION NOTE:** Add this endpoint without disrupting existing health endpoints. It should be read-only and safe to call frequently.

```
GET /api/v2/gpu-status
Response:
{
  "resident_models": [{"name": "qwen3:14b", "vram_gb": 9.8}],
  "vram_used_gb": 9.8,
  "vram_free_gb": 6.2,
  "vram_total_gb": 16.0,
  "active_hours": true,
  "active_hours_override": false,
  "last_oom_event": null,
  "last_warmup": "2026-05-11T05:30:02Z",
  "last_warmup_ms": 1245
}
```

---

# 5. Daytime Test Protocol (NEW in v4.1 Final)

## The problem

Phase 1 has three tests that need to run before observation begins:

1. **8K-context OOM test** — validates the model survives realistic context loads
2. **VRAM swap test** — validates the eviction/reload cycle works
3. **Full overnight batch** — validates integration with real pipeline scripts

All three load gemma3:27b, which evicts qwen3:14b. If the operator wants to validate during the day, the dashboard takes a ~1-2 minute hit while qwen3:14b cold-starts back in.

## The solution

**Three-tier test protocol** based on disruption tolerance.

### Tier 1 — Zero-disruption (Saturday/Sunday)

The default and recommended path. No active-hours impact, no override flags, no time pressure.

```bash
# Operator workflow
# Saturday/Sunday — no market open
.venv/bin/python scripts/gemma_8k_oom_test.py
.venv/bin/python scripts/gpu_lifecycle.py vram_swap_test
# Trigger manual overnight batch run
.venv/bin/python scripts/multi_strategy_classifier.py --manual-run --test-mode
```

**Cost:** None.
**Recovery:** None needed.

### Tier 2 — Pre-market (Mon-Fri before 9:00 AM ET)

Acceptable for tests 1 and 2. Test 3 (full overnight batch) should still run at its natural overnight slot.

```bash
# Operator workflow
# Run at 8:00-8:30 AM ET, recovery completes before market open
.venv/bin/python scripts/gemma_8k_oom_test.py
.venv/bin/python scripts/gpu_lifecycle.py vram_swap_test
# Warmup completes within 60s; qwen3:14b ready by 9:00 AM
.venv/bin/python scripts/gpu_lifecycle.py warmup qwen3:14b
```

**Cost:** None if completed before 9:30 AM.
**Recovery:** Built into the test sequence.

### Tier 3 — Active-hours with explicit override

When you need to test during market hours and accept a 1-2 minute dashboard slowdown.

```bash
# Operator workflow
# 1. Tell operator about the impact
echo "WARNING: This will evict qwen3:14b. Dashboard will be slow for ~2 minutes."

# 2. One-shot override (not persisted to .env)
export LLM_OVERRIDE_ACTIVE_HOURS=true

# 3. Use the daytime_test context manager
.venv/bin/python -c "
from scripts.gpu_lifecycle import daytime_test
with daytime_test('gemma3-overnight'):
    # Test work happens here
    import scripts.gemma_8k_oom_test as t
    t.run()
# Exits context — auto-restores qwen3:14b
"

# 4. Revert override
unset LLM_OVERRIDE_ACTIVE_HOURS
```

**Cost:** ~1-2 minutes of slow dashboard responses while qwen3:14b cold-starts back in.
**Recovery:** Automatic via the context manager's `finally` block.
**Audit:** The override usage is logged to `llm_routing_audit` with `deployment_phase` flagged as `daytime_test`.

## What the context manager does

```python
# Pseudocode for daytime_test()
@contextmanager
def daytime_test(test_model):
    # Verify override flag
    if not _truthy(os.getenv("LLM_OVERRIDE_ACTIVE_HOURS")):
        raise GPULifecycleError(
            "daytime_test requires LLM_OVERRIDE_ACTIVE_HOURS=true"
        )

    # Snapshot current state
    snapshot = status()
    previously_resident = [m["name"] for m in snapshot["resident_models"]]
    test_start = time.time()

    try:
        # Cooldown all currently resident (frees max VRAM)
        cooldown()

        # Warmup test model
        warmup(test_model)

        # Yield control to test code
        yield

    finally:
        # Always restore prior state, even on test failure
        cooldown(test_model)
        for model in previously_resident:
            warmup(model)

        # Log the daytime test event
        _log_audit_event({
            "process_type": "daytime_test",
            "script": "gpu_lifecycle.daytime_test",
            "resolved_model": test_model,
            "deployment_phase": "daytime_test",
            "total_latency_ms": int((time.time() - test_start) * 1000),
            "fallback_chain": f"test:{test_model};restored:{','.join(previously_resident)}",
        })
```

## Hard rule update

Hard rule HR-12 in section 13 is updated to:

> **HR-12:** Every BATCH_OVERNIGHT script in production MUST call `gate_batch_overnight()`. `gate_batch_overnight()` refuses during active hours unless `LLM_OVERRIDE_ACTIVE_HOURS=true`. Override usage is logged and audited.

---

# 6. LiteLLM Integration — Two Options

Unchanged from v4.0 section 4. Two options (SDK vs Proxy), pros/cons, decision matrix. Architect's default: **Option A (SDK)** unless operator specifies otherwise before Phase 4.

---

# 7. Sequenced Rollout

## Reviewed rollout recommendation

The original phase definitions are useful, but the safest execution order is:

1. **Phase 0 — Foundation + GPU lifecycle**: approved after gates.
2. **Observe Phase 0 for 24 hours.** No Phase 1 work during this window.
3. **Choose either Phase 3 or Phase 2 next** if a lower-risk visible win is desired.
4. **Phase 1 last** unless the operator specifically wants the overnight model upgrade first and accepts the risk.

**FINAL IMPLEMENTATION NOTE:** Phase 1 remains the highest-risk phase because it evicts the active-hours model and introduces a large resident model. The infrastructure from Phase 0 is useful even if Phase 1 is deferred.

## Phase 0 — Foundation + GPU Lifecycle

**Goal:** Deploy routing visibility, provider verification, GPU lifecycle visibility, alerting hooks, and audit foundations. No new production model routing. No new VRAM contention.

| Step | Action | Authorization |
|---|---|---|
| 0.0 | **Operator runs pre-deploy backup** | Operator only |
| 0.0a | Verify `scripts/full_system_backup.py --help`; document supported flags and actual output path | Claude Code reads; operator runs backup |
| 0.0b | Run hardcoded model/provider scan and save to `docs/v4_1_llm_reference_scan_before.txt` | Claude Code |
| 0.0c | Detect current service units (`systemctl --user list-units`, `systemctl list-units`) and document actual restart targets | Claude Code |
| 0.0d | Inspect existing `local_llm_config.py` / `local_llm.py` and decide wrapper-vs-extension path | Claude Code |
| 0.1 | Create `llm_routing_audit` table via migration if it does not already exist | Claude Code |
| 0.2 | Deploy process-type constants by extending current config hub or creating `llm_config.py` as a thin wrapper | Claude Code |
| 0.3 | Modify `local_llm.py` only if it is the current execution path; add async audit batching without changing semantics | Claude Code |
| 0.4 | Deploy `gpu_lifecycle.py` (status, warmup, cooldown, OOM check, daytime test) | Claude Code |
| 0.5 | Deploy `verify_llm_providers.py`; it must print live provider map from `.env` and config | Claude Code |
| 0.6 | Update `.env` additively only; do not remove existing provider vars | Claude Code |
| 0.7 | Add 3 GPU lifecycle cron entries only after recording current crontab backup path | Claude Code |
| 0.8 | Add read-only `/api/v2/gpu-status` endpoint | Claude Code |
| 0.8a | Route GPU OOM / qwen warmup failure into central alert dispatcher if available; otherwise log TODO and do not create a new noisy Telegram sender | Claude Code |
| 0.9 | Document restoration drill procedure using the actual backup format | Claude Code |
| 0.10 | **Operator runs restoration drill** | Operator |
| 0.11 | Run `verify_llm_providers.py` — must exit 0 and print provider/fallback order | Operator approval |
| 0.12 | **24-hour observation** | Operator gate |

**Success criteria:** live provider map printed, hardcoded-reference scan captured, >100 audit rows from >5 scripts after normal operation, zero `llm_audit_failures.log` entries, gpu-status endpoint reports correctly, warmup cron runs on first morning, OOM/warmup failure alert path is registered, restoration drill succeeded.

**Rollback:** env-only disable if possible; otherwise git revert Phase 0 files using detected service restart targets. Do not assume service unit names.

## Phase 1 — Overnight Reasoning (gemma3:27b) — OPTIONAL / HIGHER RISK

**Goal:** BATCH_OVERNIGHT process type uses gemma3:27b after Phase 0 telemetry is stable.

**Reviewer gate:** Do not start Phase 1 until Phase 0 has completed 24h clean observation and the operator says `Begin Phase 1`.

| Step | Action | Authorization |
|---|---|---|
| 1.0 | **Operator runs pre-deploy backup** | Operator only |
| 1.1 | **Operator pulls `gemma3:27b`** | Operator only |
| 1.2 | **Operator creates `gemma3-overnight` Modelfile with `keep_alive=0`** | Operator only |
| 1.3 | Update `.env`: `LLM_BATCH_OVERNIGHT=gemma3-overnight` only after pilot scripts are ready | Claude Code |
| 1.4 | Pilot only: refactor `multi_strategy_classifier.py` and `strategy_weekly_review.py` first; do not mass-refactor every overnight script | Claude Code |
| 1.5 | **Operator runs 8K-context OOM test** | Operator |
| 1.5a | Optional: 16K context benchmark if 8K passes and VRAM headroom remains acceptable | Operator |
| 1.5b | 32K context only as a separate benchmark; not required for deployment | Operator |
| 1.6 | **Operator runs VRAM swap test** | Operator |
| 1.7 | **Operator runs one full overnight batch at natural overnight window** | Operator |
| 1.8 | Document validation results in `docs/v4_1_deployment_log.md` | Claude Code |
| 1.9 | **7-day observation** | Operator gate |

**Success criteria:** 8K context passes without OOM, qwen3 warmup after batch returns successfully before pre-market, pilot batch completes within acceptable runtime, no mid-day BATCH_OVERNIGHT attempts, no OOM alerts, no audit failures.

**Rollback:** `LLM_BATCH_OVERNIGHT=qwen3:14b`, cooldown gemma, warm qwen. No model deletion.

## Phase 2 — Embedding Upgrade (qwen3-embedding:8b) — QUALITY-GATED

**Reviewer change:** 100% reindex is not sufficient. Run an A/B retrieval baseline before promotion.

| Step | Action | Authorization |
|---|---|---|
| 2.0 | **Operator runs pre-deploy backup including DB/RAG state** | Operator only |
| 2.1 | **Operator pulls `qwen3-embedding:8b`** | Operator only |
| 2.2 | Create `scripts/embedding_ab_baseline.py` with 20 known-good queries and expected useful results | Claude Code |
| 2.3 | Run baseline against current `nomic-embed-text`; save JSON/CSV results | Operator |
| 2.4 | Build new embeddings in a parallel namespace/table/index if the current schema supports it; otherwise stop and ask before destructive full-reindex | Operator + Claude Code design |
| 2.5 | Compare top-5 overlap, useful-result rate, latency, and error rate | Operator validation |
| 2.6 | Only after A/B pass: update `.env`: `LLM_EMBEDDING=qwen3-embedding:8b` | Claude Code |
| 2.7 | **48-hour observation** | Operator gate |
| 2.8 | After 48h clean: operator may remove `nomic-embed-text` only with explicit command | Operator only |

**Success criteria:** retrieval quality matches or improves baseline, no retrieval errors, latency acceptable, rollback plan tested.

## Phase 3 — Media/Content (gemma4:e4b) — LOWER RISK

**Reviewer note:** This may be safer to run before Phase 1 after Phase 0 is stable, because it should coexist with qwen3:14b.

| Step | Action | Authorization |
|---|---|---|
| 3.0 | **Operator runs pre-deploy backup** | Operator only |
| 3.1 | **Operator pulls `gemma4:e4b`** | Operator only |
| 3.2 | Update `.env`: `LLM_MEDIA_CONTENT=gemma4:e4b` after provider verification | Claude Code |
| 3.3 | Pilot one or two MEDIA_CONTENT scripts first; do not mass-refactor all prose scripts | Claude Code |
| 3.4 | **Operator verifies VRAM coexistence** via `/api/v2/gpu-status` | Operator |
| 3.5 | **24-hour observation** | Operator gate |

## Phase 4 — Cloud Fallback (LiteLLM)

No implementation until provider map reconciliation is complete and operator chooses SDK vs proxy. Pin dependency versions and test each provider individually before enabling budgeted fallback.

# 8. Backup-First Deployment Policy

## The rule

**Every phase's step 0 is a mandatory backup, and the backup command must be verified from the live script before use.** Claude Code does not deploy any file change without verifying a backup taken within the last 4 hours exists.

**FINAL IMPLEMENTATION NOTE:** The original plan assumes a specific backup path and set of flags. Do not rely on that assumption until `scripts/full_system_backup.py --help` confirms it.

## Required pre-backup discovery

```bash
.venv/bin/python scripts/full_system_backup.py --help | tee docs/v4_1_backup_help.txt
find . -maxdepth 4 -type d \( -name '*backup*' -o -name 'backups' \) -print | tee docs/v4_1_backup_locations.txt
```

## Preferred backup scope

Use the broadest supported live command. If these flags are supported, use them:

```bash
.venv/bin/python scripts/full_system_backup.py \
    --tag llm_v4_1_phase_${N} \
    --include-state \
    --include-rag-index \
    --include-env \
    --include-crontab
```

If those flags are **not** supported, write the actual supported command into `docs/v4_1_deployment_log.md` and stop for operator approval before proceeding.

Backup must include or be paired with:

- `data/portfolios/state/holdings.json`
- `.env` or a secure restore path for it
- current crontab (`crontab -l`)
- PostgreSQL dump or restoreable DB backup
- RAG index / embeddings state for Phase 2
- all Python files in `scripts/`
- current git SHA and branch

## Claude Code gate

```bash
# Discover phase-tagged backup in known locations, not just data/backups
find data backups docs/backups ~/db_backups -type f 2>/dev/null \
  | grep -E "llm_v4_1_phase_${N}|trade_ai|backup" \
  | xargs -r ls -lt \
  | head -20
```

If no recent phase-appropriate backup exists, Claude Code MUST refuse to proceed and give the operator the verified command from `--help`.

## Restoration drill

Backup restoration must be tested **once** during Phase 0 by the operator. Untested backups are not backups.

```bash
# Drill procedure
# 1. Pick a non-critical file
# 2. Hash it
# 3. Modify it
# 4. Restore from backup
# 5. Verify hash matches original
# 6. Document drill completion in v4_1_deployment_log.md
```

# 9. `.env` Architecture

**FINAL IMPLEMENTATION NOTE:** This block is the intended target shape. Do not paste it blindly. Add variables incrementally after `verify_llm_providers.py` prints the live provider map.

```bash
# ============================================================
# LLM Fleet v4.1 — Process-Type Model Assignments
# ============================================================

# Local generation models
LLM_STANDARD=qwen3:14b
LLM_REALTIME=qwen3:14b
LLM_BATCH_OVERNIGHT=qwen3:14b              # Keep qwen in Phase 0; switch only in Phase 1
LLM_MEDIA_CONTENT=qwen3:14b                # Switch only in Phase 3
LLM_EMBEDDING=nomic-embed-text             # Switch only after Phase 2 A/B pass

# Cloud models — do not assume names; verify from live provider config first
LLM_CRITICAL_CLOUD=<detected_critical_cloud_model>
LLM_CLOUD_FALLBACK=<detected_cloud_fallback_model>
LLM_CLOUD_FALLBACK_2=<detected_secondary_fallback_model>
LLM_OPENCLAW_PRIMARY=<detected_openclaw_primary_model>

# Local fallback for BATCH_OVERNIGHT
LLM_BATCH_OVERNIGHT_FALLBACK=qwen3:14b

# ============================================================
# GPU lifecycle controls
# ============================================================

LLM_VRAM_HEADROOM_GB=0.5
LLM_WARMUP_TIMEOUT_SEC=90
LLM_AUDIT_BATCH_SIZE=50
LLM_AUDIT_FLUSH_INTERVAL_SEC=30

# Active-hours override is normally absent or false.
# It must never be persisted as true in .env.
LLM_OVERRIDE_ACTIVE_HOURS=false

# ============================================================
# Budget and kill switches
# ============================================================

LLM_DAILY_BUDGET_LIMIT=<keep_existing_value_unless_operator_changes>
LLM_FORCE_LOCAL_ONLY=false
LLM_DISABLE_CLOUD_FALLBACK=false
LLM_DISABLE_CRITICAL_CLOUD=false
LLM_DISABLE_LIVE_EXECUTION=true

# ============================================================
# Deployment phase tag
# ============================================================

LLM_DEPLOYMENT_PHASE=v4_1_phase_0
```

**Phase-specific flips:**

| Phase | Variable change |
|---|---|
| Phase 0 | no production model change |
| Phase 1 | `LLM_BATCH_OVERNIGHT=gemma3-overnight` after tests |
| Phase 2 | `LLM_EMBEDDING=qwen3-embedding:8b` after A/B pass |
| Phase 3 | `LLM_MEDIA_CONTENT=gemma4:e4b` after coexistence pass |
| Phase 4 | cloud fallback variables only after provider test pass |

# 10. Fallback Policy Matrix

Unchanged from v3.4.1 / v4.0. See v4.0 section 7.

---

# 11. Kill Switches

| Variable | Effect |
|---|---|
| `LLM_FORCE_LOCAL_ONLY=true` | Blocks all cloud calls. CRITICAL_CLOUD fails loud. |
| `LLM_DISABLE_CLOUD_FALLBACK=true` | Blocks fallback cloud only. |
| `LLM_DISABLE_LIVE_EXECUTION=true` | Blocks live order routing. Stays true until validation gate. |
| `LLM_DISABLE_CRITICAL_CLOUD=true` | Makes CRITICAL_CLOUD raise immediately. |
| `LLM_OVERRIDE_ACTIVE_HOURS=true` | Allows BATCH_OVERNIGHT jobs during 9:30-16:00 ET (test only) |
| `LLM_AUDIT_FORCE_FAILURE=true` | Test-only. Forces audit write failure. |

---

# 12. Audit Table Design (async batched)

Schema unchanged from v4.0 section 9.

## Async batched writes

```python
# scripts/local_llm.py (excerpt)

import queue
import threading

_audit_queue = queue.Queue(maxsize=10000)

def _audit_writer_loop():
    batch = []
    last_flush = time.time()
    batch_size = int(os.getenv("LLM_AUDIT_BATCH_SIZE", "50"))
    flush_interval = int(os.getenv("LLM_AUDIT_FLUSH_INTERVAL_SEC", "30"))

    while True:
        try:
            record = _audit_queue.get(timeout=1)
            batch.append(record)
        except queue.Empty:
            pass

        now = time.time()
        if len(batch) >= batch_size or (batch and now - last_flush > flush_interval):
            _flush_audit_batch(batch)
            batch = []
            last_flush = now
```

**Benefit:** 50-row batches every 30 seconds maximum. Hundreds of LLM calls/minute don't translate to hundreds of DB transactions.

---

# 13. Hard Rules

| # | Rule |
|---|---|
| H1 | No new hardcoded model names in scripts. All new references through `.env` and the existing config hub/wrapper. |
| H2 | No script bypasses `local_llm.execute()` in new code. No new direct `requests.post(OLLAMA_URL)` calls. |
| H3 | CRITICAL_CLOUD requests never silently degrade to local. |
| H4 | EMBEDDING requests never call a cloud endpoint. |
| H5 | No new model pulled by Claude Code. Operator only. |
| H6 | No full re-index initiated by Claude Code. Operator only. |
| H7 | `LLM_DISABLE_LIVE_EXECUTION=true` must remain true throughout v4.1. |
| H8 | Holdings, broker orders, paper trades, and live execution code are out of scope. |
| H9 | No cron entry added/modified except the approved Phase 0.7 entries. |
| H10 | No phase advances without operator approval after observation. |
| H11 | No deploy without backup verified <4 hours old using the live-supported backup command. |
| H12 | Every BATCH_OVERNIGHT script created or modified must call `gate_batch_overnight()` or be run inside an approved batch-window lifecycle wrapper. |
| H13 | Every model load written in new code must go through `gpu_lifecycle.warmup()` or the approved lifecycle wrapper. |
| H14 | `gemma4:26b-a4b` is NOT deployed in v4.1. Re-evaluate on 2026-08-11 per Appendix D. |
| H15 | Daytime tests use the `daytime_test()` context manager only. Manual loads during active hours are forbidden. |
| H16 | `llm_config.py` must not become a competing source of truth. It must extend/wrap the current config hub. |
| H17 | Service names must be detected from systemd before restart commands are documented or used. |
| H18 | GPU OOM, qwen warmup failure, and active-hours override usage must be logged and routed into the central alert dispatcher if available. |
| H19 | RAG embedding migration requires baseline retrieval comparison before default model flip. |
| H20 | Phase 1 starts as a pilot with selected scripts only. No mass overnight refactor until pilot passes. |

# 14. Success Criteria per Phase

| Phase | Key Validation |
|---|---|
| 0 | provider map reconciled, model-reference scan captured, config-hub path chosen, gpu-status endpoint works, audit batching active, OOM/warmup alert path registered, restoration drill passes, 24h observation clean |
| 1 | pilot scripts only, 8K-context test passes, optional 16K benchmark recorded, VRAM swap clean, overnight pilot completes, qwen is warm before pre-market, 7d observation clean |
| 2 | 20-query baseline captured, new embedding A/B matches or beats baseline, no retrieval errors, 48h observation clean |
| 3 | coexistence verified, pilot content scripts only, no STANDARD throughput regression, 24h observation clean |
| 4 | provider tests pass individually, budget enforcement active, fallback order logged, manual sign-off |

# 15. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | gemma3:27b OOM at very long contexts (>16K/32K) | Medium | High | 8K required test; 16K optional; 32K separate benchmark only |
| R2 | Mid-day overnight job evicts qwen3:14b | High → Low | Medium | `gate_batch_overnight()` and daytime context manager |
| R3 | Repeated warm/cool cycles thrash GPU overnight | Medium | Medium | Pilot scripts; prefer batch-window lifecycle |
| R4 | Audit table write failures spike | Low | Medium | Async batch + JSONL fallback log |
| R5 | Backup command flags are invalid | Medium | High | `full_system_backup.py --help` before Phase 0 |
| R6 | Backup doesn't actually restore | Low | High | Phase 0 restoration drill mandatory |
| R7 | Re-index produces lower retrieval quality | Medium | High | 20-query A/B retrieval baseline before promotion |
| R8 | LiteLLM upgrade breaks a provider | Medium | Medium | Pin version, test each provider |
| R9 | Process type misclassified | Medium | Medium | Weekly audit review |
| R10 | Cloud budget exhaustion silently fails | Low | High | Explicit logging, budget gate in code |
| R11 | qwen3:1.7b accidentally removed | Low | Medium | Hard rule prohibits deletion |
| R12 | `.env` edit drops a key | Low | High | additive edits only + provider verification |
| R13 | Active-hours override left enabled in `.env` | Low | Medium | never persist true; scan `.env` in preflight |
| R14 | GPU lifecycle script itself fails | Low | High | calling scripts fail loud; alert dispatcher event |
| R15 | Daytime test forgets to restore qwen3:14b | Low | Medium | context manager `finally` block and post-test warmup check |
| R16 | Wrong systemd service restarted | Medium | Medium | detect unit names before documenting rollback |
| R17 | Duplicate config hub causes model drift | Medium | High | wrapper/extension rule for `llm_config.py` |
| R18 | Provider names in plan don't exist in `.env` | Medium | Medium | `verify_llm_providers.py` live map required |

# 16. Rollback Procedures (Layered)

**FINAL IMPLEMENTATION NOTE:** Rollback commands must use detected service names. Do not assume `portfolio-server.service` exists.

### Precompute restart targets before any deploy

```bash
systemctl --user list-units --type=service --type=timer | grep -Ei 'trade|portfolio|openclaw|aegis|ollama' || true
systemctl list-units --type=service --type=timer | grep -Ei 'trade|portfolio|openclaw|ollama' || true
```

Write the detected units into `docs/v4_1_deployment_log.md`.

### Layer 1 — Single `.env` edit (90% of cases)

```bash
# Phase 1 example
sed -i 's/^LLM_BATCH_OVERNIGHT=.*/LLM_BATCH_OVERNIGHT=qwen3:14b/' .env
.venv/bin/python scripts/gpu_lifecycle.py cooldown gemma3-overnight || true
.venv/bin/python scripts/gpu_lifecycle.py warmup qwen3:14b
```

**Recovery:** <2 minutes. **Use when:** bad output quality, slow runtime, model-level issue.

### Layer 2 — Kill switch + GPU cooldown

```bash
if grep -q '^LLM_FORCE_LOCAL_ONLY=' .env; then
  sed -i 's/^LLM_FORCE_LOCAL_ONLY=.*/LLM_FORCE_LOCAL_ONLY=true/' .env
else
  echo 'LLM_FORCE_LOCAL_ONLY=true' >> .env
fi
.venv/bin/python scripts/gpu_lifecycle.py cooldown
.venv/bin/python scripts/gpu_lifecycle.py warmup qwen3:14b
```

### Layer 3 — Git revert

```bash
# Identify exact pre-phase commit from deployment log
git log --oneline -20
# Example only; replace <sha> with logged baseline
git checkout <sha> -- scripts/local_llm.py scripts/local_llm_config.py scripts/llm_config.py scripts/gpu_lifecycle.py .env
# Restart only detected services, not assumed names
```

### Layer 4 — Full backup restore

Use the actual restore procedure documented from the live backup system. Do not invent `full_system_restore.py` unless it exists.

```bash
ls scripts/*restore* docs/*RESTORE* 2>/dev/null || true
```

### Decision tree

```
Phase deployed, something is wrong
        ↓
Bad output / slow runtime?               → Layer 1 env rollback
        ↓
GPU stuck / warmup failure?              → Layer 2 kill switch + cooldown + alert
        ↓
Router/config bug?                       → Layer 3 git checkout/revert + detected service restart
        ↓
DB/RAG/holdings damage?                  → Layer 4 restore from verified backup
```

### Don'ts

- Do NOT delete models as rollback.
- Do NOT restore from a later phase backup when rolling back an earlier phase.
- Do NOT restart guessed service names.
- Do NOT leave active-hours override enabled in `.env`.

# 17. Appendix A — Delta from v3.4.1 and v4.0

### v4.0 → v4.1 Final changes

| Item | v4.0 | v4.1 Final |
|---|---|---|
| GPU VRAM characterization | UMA shared | Dedicated 16 GB GDDR6 |
| Phase 1 model | gemma4:26b-a4b | **gemma3:27b** |
| gemma4:26b-a4b | Default choice | Calendar reminder 2026-08-11 |
| Freeze window gate | Required | Removed (backup verification) |
| GPU lifecycle | Single preload cron | First-class subsystem |
| Daytime test protocol | Not specified | 3-tier protocol with auto-restore |
| Active-hours guard | None | `gate_batch_overnight()` |
| 8K-context OOM test | Not in plan | Required Phase 1.5 |
| Audit writes | Synchronous | Async batched |
| Phase 0 observation | 48h | 24h |
| Phase 2 observation | 7 days | 48h |
| Phase 3 observation | 7 days | 24h |
| Backup before deploy | Mentioned | Mandatory (HR-11) |
| Restoration drill | Not required | Phase 0 required |
| Total rollout | ~31 days | ~10 days |

### v3.4.1 → v4.x carry-overs

See v4.0 Appendix A. Burn-in B, fcntl removal, qwen3:1.7b deletion remain deferred.

---

# 18. Appendix B — LiteLLM SDK vs Proxy Decision Matrix

Unchanged from v4.0 Appendix B.

---

# 19. Appendix C — Deferred Work

Items deliberately not in v4.1 Final. Each has a re-entry criterion.

| Item | Re-entry Criterion |
|---|---|
| Burn-in B (queue stress test) | Concurrent users >1 OR audit log shows concurrent-request failures |
| `fcntl` removal | Burn-in B passes with measurable throughput improvement |
| qwen3:1.7b removal | v4.1 stable for 30+ consecutive days; no rollback events |
| Full 15-test pytest suite | Quarterly hardening cycle |
| OpenClaw qwen3:14b upgrade | After v4.1 stable; separate maturity track |
| Qwen Code on dev box | Trading system reaches 30+ closed paper trades |
| Cohere/Command-R | Never (wrong fit for code-capable cold path) |
| Cohere Rerank-3.5 for RAG | Open as future RAG quality improvement |
| LiteLLM Proxy migration | Cloud spend >$50/month OR semantic caching matters |
| **gemma4:26b-a4b** | **2026-08-11 calendar review (Appendix D)** |

---

# 20. Appendix D — gemma4:26b-a4b Re-evaluation (2026-08-11)

## Why this exists

`gemma4:26b-a4b` was the original Phase 1 choice in v3.4.1 and v4.0. v4.1 Final defers it because:

1. **Hardware fit:** 18 GB on disk on a 16 GB card requires Q3 quantization with quality loss
2. **MoE architecture:** Mixture-of-Experts with 4B active parameters — less optimization work on Intel Arc/Vulkan than dense models
3. **Maturity:** Released early May 2026 — no production track record at deployment time
4. **Risk-proportional choice:** gemma3:27b offers a real capability win with substantially lower risk

This is not a permanent rejection. The re-evaluation date is set so the decision gets re-examined when conditions change.

## Trigger date: 2026-08-11

Three months after v4.1 Final ships.

## Pre-conditions before re-evaluation begins

1. v4.1 Final has been stable for ≥30 consecutive days (no rollback events)
2. v4.1 audit table has ≥30 days of baseline data on gemma3:27b for BATCH_OVERNIGHT
3. Ollama has released ≥2 minor versions with documented MoE improvements
4. Operator has bandwidth for a Phase 6 deployment cycle

If any precondition fails, push the review to 2026-09-11.

## Evaluation procedure

### Step 1 — Research check (30 minutes)

Operator (or Claude) web-searches:
- Recent benchmarks of `gemma4:26b-a4b` vs `gemma3:27b` for reasoning tasks
- Production deployment writeups on Intel Arc, Vulkan, or other ~16 GB cards
- Ollama release notes for MoE-on-Vulkan optimization
- Community feedback on `gemma4:26b-a4b` stability and quality

**Gate:** If no credible production deployments exist on similar hardware, defer 3 more months.

### Step 2 — Capacity check (15 minutes)

```bash
# What size is the model currently?
ollama show gemma4:26b-a4b
# Look for Q3, Q4_K_S, Q4_K_M variants
```

**Gate:** If only Q3 variant fits on 16 GB, evaluate whether Q3 quality is acceptable. If Q4_K_S or higher now fits (Ollama optimization improvements), proceed.

### Step 3 — Side-by-side benchmark (Phase 6.1, half day)

Operator pulls `gemma4:26b-a4b` (test only, doesn't replace gemma3:27b yet).

Run the existing `multi_strategy_classifier.py` with:
1. Current production: gemma3:27b
2. Test alternative: gemma4:26b-a4b

Compare on the same input dataset (last 7 days of overnight batches):
- Classification accuracy (manual review of 20 samples)
- Runtime per batch
- Peak VRAM during inference
- Any OOM events

### Step 4 — Decision

| Result | Action |
|---|---|
| gemma4 clearly better, no stability issues | Promote to Phase 6 — full deployment |
| gemma4 marginally better, stable | Defer 3 more months; keep gemma3:27b |
| gemma4 worse OR unstable | Reject permanently; remove from re-evaluation list |
| Cannot fit cleanly on 16 GB | Defer until hardware upgrade considered |

### Step 5 — Document

Whatever the outcome, write the result in `docs/v4_1_deployment_log.md` and update memory. Either:
- gemma4:26b-a4b is promoted to a new Phase 6 plan with its own backup-first, observation-window approach
- gemma4:26b-a4b is deferred again with a new review date
- gemma4:26b-a4b is permanently removed from consideration

## Calendar reminder

Add to operator's calendar:

```
Title:    LLM Fleet — gemma4:26b-a4b Re-evaluation
Date:     2026-08-11
Duration: 1 hour
Notes:    Review Appendix D of LLM_FLEET_STRATEGY_v4_1.md.
          Check preconditions, run research check, decide.
```

## Why this approach matters

This is the right pattern for any "leading edge but not yet ready" technology. Decisions don't need to be permanent rejections — they need to be **deferred decisions with a calendar trigger** so they get re-examined when conditions change.

The risk of leaving this implicit is forgetting about it entirely. The risk of forcing it now is deploying a poorly-fitted MoE model on unproven Vulkan infrastructure during a critical paper-trading validation period.

The calendar reminder is the cheap insurance.

---

# Closing Note

This is v4.1 Final. The companion execution prompt is `CLAUDE_CODE_PROMPT_LLM_v4_1.md`.

**Three pieces of honest advice:**

1. **gemma3:27b is the boring, correct choice.** It's mature, fits well, and the 128K context window is a genuine win. It's not the latest, and that's why it works.

2. **The backup-first policy is the most important single change.** Most "failed deploy" stories are recoverable from backup. The few that aren't are recoverable from backup that wasn't taken.

3. **You don't have to do Phase 1.** The 4-phase plan defaults to running all of them, but the architecture works fine if you only ship Phases 0, 2, and 3. Phase 1 (overnight reasoning upgrade) is the highest-risk phase and lowest-immediately-visible-value phase. Defer it if anything feels uncertain. The infrastructure deployed in Phase 0 makes Phase 1 a future drop-in, not a from-scratch effort.

---

**Document version:** 4.1 Final — Final Execution Revision
**Last updated:** 2026-05-11
**Author:** Claude (architecture review, v4.1 optimization + gemma3 correction)
**Review annotations:** ChatGPT, 2026-05-11 — implementation safety pass
**Operator:** John (approval required for execution)
**Next scheduled review:** 2026-08-11 (Appendix D — gemma4:26b-a4b)

---

# Appendix E — Initial Script Routing Matrix

This matrix answers the operational question: “Which local-LLM scripts should use which model going forward?” It is an initial routing map, not permission to mass-refactor. Claude Code must validate it with the Phase 0 hardcoded-reference scan and live source inspection before changing any specific file.

## Core rule

Scripts should not name models directly. Scripts should declare a process type, and the existing config hub/wrapper should resolve the model from `.env`.

```python
from scripts.local_llm import execute
from scripts.llm_config import STANDARD  # or REALTIME / BATCH_OVERNIGHT / etc.

result = execute(prompt, process_type=STANDARD, script="script_name.py")
```

## Initial routing map

| Script / workflow | Process type | Model policy after rollout | Phase | Notes |
|---|---:|---|---:|---|
| `scripts/process_watchlist_agent_jobs.py` | STANDARD | `qwen3:14b` | Phase 0 | Main backend agent processor. Keep fast/local and compatible with active-hours operation. Do not move this wholesale to gemma3. |
| Maria / Steph / Risk backend analysis through shared job processor | STANDARD | `qwen3:14b` | Phase 0 | Existing two-pass and peer/RAG context path should stay on resident active-hours model unless later benchmark proves otherwise. |
| `scripts/incubator_llm_screener.py` | STANDARD | `qwen3:14b` | Phase 0 | Runs around premarket/evening; keep stable. Do not make it depend on gemma3 until pilot data exists. |
| `scripts/topic_curator.py` | STANDARD | `qwen3:14b` | Phase 0 | Daily curation and query improvement. Morning path should not trigger large-model GPU swaps. |
| `scripts/llm_intelligence_enrichment.py` | STANDARD | `qwen3:14b` | Phase 0 | Daily intelligence narratives. Keep stable during initial rollout. |
| `scripts/aegis_morning_brief_delivery.py` | STANDARD / REALTIME | `qwen3:14b` | Phase 0 | Morning operator-facing brief. Must remain reliable and quick. |
| `scripts/local_llm.py` | Execution path | no direct model; resolve from config | Phase 0 | Add audit/gating here only if this is confirmed as current execution path. |
| `scripts/local_llm_config.py` | Config hub | source of truth / extended hub | Phase 0 | Do not replace silently. New `llm_config.py`, if created, must wrap or extend this. |
| `scripts/multi_strategy_classifier.py` | BATCH_OVERNIGHT | `gemma3-overnight` after Phase 1 approval | Phase 1 pilot | First pilot candidate only. Must call `gate_batch_overnight()` or run under batch-window wrapper. |
| `scripts/strategy_weekly_review.py` | BATCH_OVERNIGHT | `gemma3-overnight` after Phase 1 approval | Phase 1 pilot | Second pilot candidate. Must restore/warm qwen before premarket. |
| `scripts/weekly_incubator_builder.py --llm` | BATCH_OVERNIGHT candidate | Candidate for `gemma3-overnight` after pilot passes | Later Phase 1 expansion | Do not change during initial pilot unless explicitly approved. |
| Overnight synthesis / long-form batch classifiers | BATCH_OVERNIGHT candidate | Candidate for `gemma3-overnight` | Later Phase 1 expansion | Group jobs behind one lifecycle wrapper where possible to avoid GPU thrash. |
| `scripts/rag_indexer.py` and embedding calls | EMBEDDING | `qwen3-embedding:8b` only after Phase 2 A/B pass | Phase 2 | `nomic-embed-text` remains default until retrieval-quality A/B passes and 48h observation is clean. |
| RAG retrieval query embedding helpers | EMBEDDING | `qwen3-embedding:8b` after Phase 2 | Phase 2 | Must never call cloud. |
| Report/document prose generation such as weekly/monthly summaries | MEDIA_CONTENT candidate | `gemma4:e4b` only after Phase 3 approval | Phase 3 pilot | Pilot one or two scripts first. Do not move all prose scripts at once. |
| YouTube/transcript summarization or article summarization workflows | MEDIA_CONTENT candidate | `gemma4:e4b` after Phase 3 pilot | Phase 3 | Keep qwen until coexistence and throughput tests pass. |
| Alex retirement, Roth, SSDI, IRMAA, complex tax decisions | CRITICAL_CLOUD | Cloud-only, fail loud | Existing/Phase 0 verified | No local fallback for critical retirement/tax decisions. Use live provider map from `.env`. |
| CIO synthesis or high-impact portfolio decisions | CRITICAL_CLOUD or cloud escalation | Cloud-required if policy says so | Existing/Phase 0 verified | Provider names must be discovered from live config. |
| Any direct `requests.post(...11434...)` Ollama caller found by grep | Migration list | no new direct calls; migrate gradually | Phase 0 inventory | Record in migration list. Do not mass-refactor in Phase 0. |

## What this does and does not do

This document does address the current local-LLM routing question, but it deliberately does it through a process-type migration pattern rather than hardcoding every script to a model. Phase 0 creates the live inventory and routing/audit layer. Phase 1 changes only pilot batch scripts. Phase 2 changes embeddings only after A/B retrieval validation. Phase 3 changes only pilot media/content scripts.

---

## Phase 2 — RAG Embedding A/B Testing (Active)

Full Phase 2 documentation is at `docs/llm_fleet/phase2_embedding_ab/`.

Phase 2 evaluates replacing `nomic-embed-text` with `qwen3-embedding:8b`.
Candidate installed (4.7 GB, 4096 dims). Baseline established 2026-05-14.
A/B embedding comparison complete: nomic 23ms/768d vs candidate 295ms/4096d.
Retrieval quality comparison pending Phase 2B parallel index.

See `docs/llm_fleet/phase2_embedding_ab/00_README.md` for read order
and current gate status.

