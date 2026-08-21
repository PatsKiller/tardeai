#!/usr/bin/env python3
"""llm_router.py — Smart LLM routing with fallback hierarchy.

Routes requests through provider chain. Task-aware routing.
Logs everything for cost/quality tracking.

═══ PROVIDER CHAIN (2026-08-21 inventory) ═══════════════════════════════════

  LOCAL gemma3:4b (default)  →  governed DeepSeek Flash  →  ChatGPT OAuth overnight
  Installed: gemma3:4b / 12b / 27b / gemma3-overnight. qwen3:1.7b is NOT installed.
  Do not buy GPU for 1.7b. US overnight judgment = ChatGPT OAuth, not gemma.

Provider   Speed      Cost/1K   Quality    Best For
─────────  ─────────  ────────  ─────────  ────────────────────────────────
Local      Fast       Free      Medium     Routine batch, overnight, tagging
Grok       Very fast  ~$0.01    Good       Agent analyses, debates, sector alerts
                                           *** PRIMARY TESTING PROVIDER ***
Claude     Medium     ~$1.00    Best       Retirement, disability, Roth, CIO synthesis
OpenAI     Fast       ~$0.50    Good       Last resort only

═══ LOCAL INVENTORY (do not buy GPU for 1.7b) ════════════════════════════════

  Live default is gemma3:4b (local_llm_config.DEFAULT_LOCAL_LLM_MODEL).
  qwen3:1.7b is NOT installed. The old "1.7b is the quality ceiling / buy a GPU"
  conclusion is obsolete — strike it from hardware decisions.

  Optional future: LOCAL_LLM_MODEL=qwen3:14b only after that model is installed.
  Do not revert to qwen3:1.7b; revert to gemma3:4b.

═══ TASK ROUTING ════════════════════════════════════════════════════════════

  Live (gemma3:4b / 12b / 27b):  governed DeepSeek Flash for agent tasks
  Retirement/disability:         still policy-gated (not this module's spend path)
  US overnight judgment:         ChatGPT OAuth, not gemma (overnight_llm_policy)

Usage:
    from llm_router import get_llm_response
    result = get_llm_response("agent_narrative", prompt, high_impact=False)
    result = get_llm_response("agent_debate", prompt, high_impact=True)
"""
import json, os, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Configuration ──────────────────────────────────────────────────────────

LOCAL_TIMEOUT = 90      # seconds — qwen3:14b agent prompts with RAG context need 60-90s on Intel Arc B580
CONFIDENCE_THRESHOLD = 0.65

from local_llm_config import get_local_llm_model, get_local_llm_base_url, apply_ollama_runtime_env

apply_ollama_runtime_env()

LOCAL_MODEL = get_local_llm_model()

LOCAL_URL = get_local_llm_base_url().rstrip("/") + "/api/chat"
DAILY_BUDGET_LIMIT = 1.50  # USD/day — allows cloud fallback when Ollama offline (typical spend ~$0.02/day)

# ── Task routing — auto-adjusts based on LOCAL_MODEL ─────────────────────

# Governed DeepSeek Flash only for agent watchlist workloads (issue #283 / PR #284).
# No silent local/Grok/Claude/OpenAI fallback on paid agent tasks.
_TASK_ROUTING_PRE_GPU = {
    "agent_narrative":          ["deepseek-flash"],
    "agent_debate":             ["deepseek-flash"],
    "sector_correlation":       ["deepseek-flash"],
    "cio_synthesis":            ["deepseek-flash"],
    "catalyst_classification":  ["deepseek-flash"],
    "sentiment":                ["deepseek-flash"],
    "code_generation":          ["deepseek-flash"],
    "fast_summary":             ["deepseek-flash"],
    "default":                  ["deepseek-flash"],
}

_TASK_ROUTING_POST_GPU = {
    "agent_narrative":          ["deepseek-flash"],
    "agent_debate":             ["deepseek-flash"],
    "sector_correlation":       ["deepseek-flash"],
    "cio_synthesis":            ["deepseek-flash"],
    "catalyst_classification":  ["deepseek-flash"],
    "sentiment":                ["deepseek-flash"],
    "code_generation":          ["deepseek-flash"],
    "fast_summary":             ["deepseek-flash"],
    "default":                  ["deepseek-flash"],
}

# High-impact agent tasks still use governed Flash only (no Pro on this path).
_HIGH_IMPACT_ROUTING = {
    "cio_synthesis":        ["deepseek-flash"],
    "agent_narrative":      ["deepseek-flash"],
    "agent_debate":         ["deepseek-flash"],
    "sector_correlation":   ["deepseek-flash"],
    "default":              ["deepseek-flash"],
}

# Select routing table based on current model
_IS_GPU = LOCAL_MODEL != "qwen3:1.7b" and "1.7b" not in LOCAL_MODEL  # GPU mode if model upgraded from 1.7b
_TASK_ROUTING = _TASK_ROUTING_POST_GPU if _IS_GPU else _TASK_ROUTING_PRE_GPU

if _IS_GPU:
    print(f"[llm_router] GPU mode: {LOCAL_MODEL} — Grok demoted to fallback, local is primary")


def _load_env():
    """Load API keys from .env."""
    keys = {}
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("\"'")
                if v:
                    keys[k] = v
    return keys


def _call_local(prompt: str, max_tokens: int = 800, timeout: int = None) -> dict:
    """Call local Ollama."""
    t0 = time.time()
    _timeout = timeout or LOCAL_TIMEOUT
    try:
        # num_ctx: without an explicit value Ollama allocated the model's FULL 131k context
        # (7.2 GB KV cache for gemma3:4b) — observed 16-25 tok/s on 2026-07-03. Agent prompts
        # run 0.5-3k tokens; 8k leaves ample headroom at a fraction of the VRAM and prefill
        # cost. keep_alive pins the model resident between the worker's back-to-back calls
        # instead of load/unload churn. Both env-tunable.
        payload = json.dumps({
            "model": LOCAL_MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content": prompt}],
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            "options": {"temperature": 0.3, "num_predict": max(500, max_tokens),
                        "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192"))}
        }).encode()
        req = urllib.request.Request(LOCAL_URL, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=max(30, _timeout + 20)) as resp:
            result = json.loads(resp.read())
            text = result.get("message", {}).get("content", "").strip()
            latency = round(time.time() - t0, 2)
            # Diagnostic: capture Ollama internals for Phase 0B analysis
            eval_count = result.get("eval_count", 0)
            prompt_eval_count = result.get("prompt_eval_count", 0)
            eval_dur_s = round(result.get("eval_duration", 0) / 1e9, 2)
            prompt_eval_dur_s = round(result.get("prompt_eval_duration", 0) / 1e9, 2)
            total_dur_s = round(result.get("total_duration", 0) / 1e9, 2)
            tok_per_s = round(eval_count / eval_dur_s, 1) if eval_dur_s > 0 else 0
            return {
                "model_used": LOCAL_MODEL, "provider": "local",
                "response": text, "latency": latency,
                "success": bool(text and len(text) > 20),
                "cost_estimate": 0.0,
                # Phase 0B diagnostics (backward-compatible, ignored by consumers)
                "eval_count": eval_count, "prompt_eval_count": prompt_eval_count,
                "eval_duration_s": eval_dur_s, "prompt_eval_duration_s": prompt_eval_dur_s,
                "total_duration_s": total_dur_s, "tok_per_s": tok_per_s,
            }
    except Exception as e:
        return {"model_used": LOCAL_MODEL, "provider": "local",
                "response": "", "latency": round(time.time() - t0, 2),
                "success": False, "error": str(e), "cost_estimate": 0.0}


def _call_anthropic(prompt: str, max_tokens: int = 2000) -> dict:
    """Legacy Claude path — rejected for agent_flash governance (issue #283).

    Pro/Claude must not be used as silent fallback for watchlist agent automation.
    """
    return {
        "success": False,
        "error": "POLICY_NOT_ALLOWED: Claude/Pro not permitted on agent_flash governed path",
        "provider": "claude",
        "cost_estimate": 0.0,
        "latency": 0.0,
    }


def _call_deepseek_v4_legacy_rejected(prompt: str, max_tokens: int = 2000) -> dict:
    """Ambiguous deepseek-v4 / Pro path — always rejected on this router."""
    return {
        "success": False,
        "error": "LEGACY_MODEL_REJECTED: deepseek-v4 / Pro aliases forbidden; use governed deepseek-flash only",
        "provider": "deepseek",
        "cost_estimate": 0.0,
        "latency": 0.0,
    }


def _call_deepseek_flash_governed(
    prompt: str,
    max_tokens: int = 800,
    *,
    task_type: str = "agent_narrative",
    metadata: dict | None = None,
    job_key: str | None = None,
) -> dict:
    """Governed DeepSeek V4 Flash only (issue #283). No legacy IDs. No silent fallback."""
    from lib.agent_flash_governance import governed_flash_call
    return governed_flash_call(
        prompt,
        task_type=task_type,
        max_tokens=max_tokens,
        metadata=metadata,
        job_key=job_key,
    )


def _call_openai(prompt: str, max_tokens: int = 2000) -> dict:
    """Legacy name kept for provider map key only — routes to governed DeepSeek Flash.

    Does NOT call OpenAI. Does NOT label results as deepseek-chat.
    """
    # task_type threaded via get_llm_response → _current_task_type
    tt = getattr(_call_openai, "_current_task_type", "agent_narrative")
    meta = getattr(_call_openai, "_current_metadata", None)
    job_key = getattr(_call_openai, "_current_job_key", None)
    return _call_deepseek_flash_governed(
        prompt, max_tokens=max_tokens, task_type=tt, metadata=meta, job_key=job_key,
    )


def _call_grok(prompt: str, max_tokens: int = 2000) -> dict:
    """Call xAI Grok API."""
    keys = _load_env()
    api_key = keys.get("XAI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "XAI_API_KEY not configured", "provider": "grok"}

    t0 = time.time()
    try:
        payload = json.dumps({
            "model": "grok-3-mini",  # grok-3-mini: fast + cheap for agent tasks
            # GPU upgrade: stays as grok-3-mini even after GPU — Grok used as cloud fallback
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            latency = round(time.time() - t0, 2)
            return {
                "model_used": "grok-3-mini", "provider": "grok",
                "response": text.strip(), "latency": latency,
                "success": bool(text.strip()),
                # grok-3-mini: ~$0.30/1M input, $0.50/1M output (estimate)
                "cost_estimate": round((max_tokens * 0.0005) / 1000, 5),
            }
    except Exception as e:
        return {"success": False, "error": str(e), "provider": "grok",
                "latency": round(time.time() - t0, 2), "cost_estimate": 0.0}


_PROVIDERS = {
    "local": _call_local,
    "deepseek-flash": _call_openai,  # → governed deepseek-v4-flash (issue #283)
    "deepseek-v4": _call_deepseek_v4_legacy_rejected,
    "grok": _call_grok,
    "claude": _call_anthropic,
    "openai": _call_openai,  # alias → governed flash, not OpenAI API
}


def get_llm_response(
    task_type: str,
    prompt: str,
    context: dict = None,
    high_impact: bool = False,
    max_tokens: int = 800,
    local_timeout: int = None,
    *,
    metadata: dict | None = None,
    job_key: str | None = None,
) -> dict:
    """Route LLM request through provider hierarchy. Returns best response.

    Args:
        task_type: agent_narrative, cio_synthesis, catalyst_classification, sentiment, etc.
        prompt: The full prompt text
        high_impact: If True, use high-impact routing table (still Flash-only for agents)
        max_tokens: Max response tokens
        local_timeout: Override local timeout (default 8s for fallback trigger)
        metadata: optional job metadata (symbol, agent) — no private prompt echo
        job_key: stable job id for dedupe

    Returns:
        dict with: model_used, provider, response, latency, cost_estimate, fallback_reason
    """
    # Thread task context into governed DeepSeek provider
    _call_openai._current_task_type = task_type or "agent_narrative"  # type: ignore[attr-defined]
    _call_openai._current_metadata = metadata  # type: ignore[attr-defined]
    _call_openai._current_job_key = job_key  # type: ignore[attr-defined]

    # Determine provider order
    if high_impact:
        providers = _HIGH_IMPACT_ROUTING.get(task_type, _HIGH_IMPACT_ROUTING["default"])
    else:
        providers = _TASK_ROUTING.get(task_type, _TASK_ROUTING["default"])

    fallback_reasons = []
    total_cost = 0.0

    for provider_name in providers:
        caller = _PROVIDERS.get(provider_name)
        if not caller:
            continue

        # Governed DeepSeek path: no chain fallback on hard policy/cost failures
        if provider_name == "deepseek-flash":
            result = _call_deepseek_flash_governed(
                prompt,
                max_tokens=max_tokens,
                task_type=task_type or "agent_narrative",
                metadata=metadata,
                job_key=job_key,
            )
            result["task_type"] = task_type
            result["high_impact"] = high_impact
            if result.get("success"):
                result["fallback_reasons"] = fallback_reasons
                result["total_cost"] = round(float(result.get("cost_estimate") or 0), 6)
                _log_call(task_type, result)
                return result
            # Dedupe skip is not a circuit failure — surface cleanly
            err = str(result.get("error") or "")
            if err.startswith("DEDUPE_SKIP"):
                result["fallback_reasons"] = fallback_reasons
                _log_call(task_type, result)
                return result
            # Policy / cost / mismatch — do not fall through to local (no silent fallback)
            if any(x in err.upper() for x in (
                "COST_CAP", "COST_CONFIGURATION", "POLICY_NOT", "LEGACY_MODEL",
                "MISMATCHED", "PROCESS_NOT", "CIRCUIT_OPEN", "FALLBACK_FORBIDDEN",
                "INPUT_LIMIT", "COST_PERSISTENCE",
            )):
                result["fallback_reasons"] = fallback_reasons
                _log_call(task_type, result)
                return result
            fallback_reasons.append(f"deepseek-flash: {err[:120]}")
            # only continue if another free provider remains in chain
            continue

        # Budget check for external providers
        if provider_name != "local":
            daily_spend = _get_daily_spend()
            if daily_spend >= DAILY_BUDGET_LIMIT:
                fallback_reasons.append(f"{provider_name}: daily budget exceeded (${daily_spend:.2f}/${DAILY_BUDGET_LIMIT:.2f})")
                continue

        if provider_name == "local":
            result = caller(prompt, max_tokens=max_tokens, timeout=local_timeout)
        else:
            result = caller(prompt, max_tokens=max_tokens)

        total_cost += result.get("cost_estimate", 0)

        if result.get("success"):
            result["fallback_reasons"] = fallback_reasons
            result["total_cost"] = round(total_cost, 4)
            result["task_type"] = task_type
            result["high_impact"] = high_impact

            # Log the call
            _log_call(task_type, result)
            return result

        # Record failure and try next
        reason = f"{provider_name}: {result.get('error', 'empty response')}"
        fallback_reasons.append(reason)

    # All failed
    return {
        "model_used": "none", "provider": "none",
        "response": "", "latency": 0, "success": False,
        "fallback_reasons": fallback_reasons,
        "total_cost": round(total_cost, 4),
        "task_type": task_type,
        "error": "All providers failed",
    }


def _get_daily_spend() -> float:
    """Get total external API spend for today from logs."""
    log_file = PROJECT_ROOT / "logs" / "llm_router.log"
    if not log_file.exists():
        return 0.0
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0.0
    try:
        for line in log_file.read_text().splitlines():
            if today in line:
                entry = json.loads(line)
                if entry.get("provider") != "local":
                    total += entry.get("cost", 0)
    except Exception:
        pass
    return round(total, 4)


def health_check() -> dict:
    """Test all providers and return availability status."""
    results = {}

    # Local — check model residency via /api/ps (fast, <100ms).
    # A full generate probe is too slow (~50-60s with qwen3 thinking) for a health endpoint.
    try:
        t0 = time.time()
        ps_req = urllib.request.urlopen("http://localhost:11434/api/ps", timeout=5)
        ps_data = json.loads(ps_req.read())
        latency = round(time.time() - t0, 3)
        resident = [m["name"] for m in ps_data.get("models", [])]
        alive = LOCAL_MODEL in resident or any(LOCAL_MODEL.split(":")[0] in m for m in resident)
        results["local"] = {"available": alive, "latency": latency, "model": LOCAL_MODEL,
                            "resident_models": resident}
    except Exception as e:
        results["local"] = {"available": False, "error": str(e)}

    # External providers
    keys = _load_env()
    for name, key_name in [("grok", "XAI_API_KEY"), ("claude", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")]:
        results[name] = {"available": bool(keys.get(key_name)), "configured": bool(keys.get(key_name))}

    results["daily_spend"] = _get_daily_spend()
    results["daily_budget"] = DAILY_BUDGET_LIMIT
    results["budget_remaining"] = round(DAILY_BUDGET_LIMIT - _get_daily_spend(), 4)

    return results


def _log_call(task_type: str, result: dict):
    """Log LLM call for cost/quality tracking."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "llm_router.log"

    # Determine routing reason
    hi = result.get("high_impact", False)
    prov = result.get("provider", "?")
    fallbacks = result.get("fallback_reasons", [])
    if not hi and prov == "local":
        routing_reason = "routine → local (default)"
    elif hi and prov == "local":
        routing_reason = f"high_impact but cloud unavailable ({len(fallbacks)} fallbacks) → local"
    elif hi and prov == "claude":
        routing_reason = "high_impact → claude (primary)"
    elif hi and prov in ("grok", "openai"):
        routing_reason = f"high_impact → {prov} (claude unavailable)"
    else:
        routing_reason = f"{prov} (task={task_type})"

    resp_text = result.get("response", "")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "task_type": task_type,
        "provider": prov,
        "model": result.get("model_used"),
        "routing_reason": routing_reason,
        "latency": result.get("latency"),
        "cost": result.get("cost_estimate", 0),
        "response_len": len(resp_text),
        "est_tokens": len(resp_text) // 4,
        "prompt_len": len(result.get("_prompt", "")) if "_prompt" in result else 0,
        "fallbacks": fallbacks,
        "high_impact": hi,
    }
    # Phase 0B: include Ollama diagnostics when available
    if result.get("eval_count"):
        entry["ollama_eval_count"] = result["eval_count"]
        entry["ollama_prompt_eval_count"] = result.get("prompt_eval_count", 0)
        entry["ollama_eval_duration_s"] = result.get("eval_duration_s", 0)
        entry["ollama_prompt_eval_dur_s"] = result.get("prompt_eval_duration_s", 0)
        entry["ollama_total_dur_s"] = result.get("total_duration_s", 0)
        entry["ollama_tok_per_s"] = result.get("tok_per_s", 0)

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── CLI for testing ──────────────────────────────────────────

if __name__ == "__main__":
    if "--test" in sys.argv or "--test-grok" in sys.argv:
        print("=== LLM Router Test ===")
        print(f"LOCAL_MODEL: {LOCAL_MODEL} ({'GPU mode' if _IS_GPU else 'pre-GPU mode'})")
        print(f"DAILY_BUDGET_LIMIT: ${DAILY_BUDGET_LIMIT:.2f}")
        print()

        # Test 1: Local
        print("1. Testing local (agent_narrative)...")
        r = get_llm_response("agent_narrative", "Summarize SCHD as a dividend growth ETF in 2 sentences.", max_tokens=200)
        print(f"   Provider: {r['provider']} | Model: {r['model_used']} | Latency: {r['latency']}s | Cost: ${r.get('cost_estimate',0)}")
        print(f"   Response: {r['response'][:100]}...")
        print(f"   Fallbacks: {r.get('fallback_reasons', [])}")
        print()

        # Test 2: Grok (agent_debate — new task type)
        if "--test-grok" in sys.argv or True:
            print("2. Testing Grok (agent_debate — primary testing provider)...")
            r2 = get_llm_response("agent_debate",
                "Should we trim LMT given RSI 48 and stop triggered? Risk says HOLD 50%, Steph says TRIM 85%. "
                "Portfolio heat is 6.2% (elevated). Respond as consensus moderator in 2 sentences.",
                high_impact=True, max_tokens=200)
            print(f"   Provider: {r2['provider']} | Model: {r2['model_used']} | Latency: {r2['latency']}s | Cost: ${r2.get('cost_estimate',0)}")
            print(f"   Response: {r2['response'][:150]}...")
            print(f"   Fallbacks: {r2.get('fallback_reasons', [])}")
            print()

        # Test 3: High-impact (should use Claude if available)
        print("3. Testing high-impact (cio_synthesis)...")
        r3 = get_llm_response("cio_synthesis",
            "Should we trim SCHD given RSI 63 and 11.79% portfolio weight? Respond in 2 sentences.",
            high_impact=True, max_tokens=200)
        print(f"   Provider: {r3['provider']} | Model: {r3['model_used']} | Latency: {r3['latency']}s | Cost: ${r3.get('cost_estimate',0)}")
        print(f"   Response: {r3['response'][:100]}...")
        print()

        print("=== Provider Availability ===")
        keys = _load_env()
        for name, key_name in [("Local Ollama", None), ("Grok (xAI)", "XAI_API_KEY"),
                                ("Claude", "ANTHROPIC_API_KEY"), ("OpenAI", "OPENAI_API_KEY")]:
            if key_name is None:
                print(f"  {name}: AVAILABLE (localhost:{LOCAL_MODEL})")
            elif keys.get(key_name):
                print(f"  {name}: CONFIGURED ✓")
            else:
                print(f"  {name}: NOT CONFIGURED")

        print()
        print(f"=== GPU Upgrade Status ===")
        print(f"  Current model: {LOCAL_MODEL}")
        if _IS_GPU:
            print(f"  Mode: POST-GPU — local is primary, Grok is fallback")
        else:
            print(f"  Mode: PRE-GPU — Grok is primary cloud testing provider")
            print(f"  To activate GPU: echo 'LOCAL_LLM_MODEL=qwen3:14b' >> .env")

    elif "--routing" in sys.argv:
        print("=== Current Task Routing ===")
        print(f"Mode: {'POST-GPU' if _IS_GPU else 'PRE-GPU'} | LOCAL_MODEL: {LOCAL_MODEL}")
        print()
        for task, chain in _TASK_ROUTING.items():
            print(f"  {task:30} {' → '.join(chain)}")
        print()
        print("High-impact overrides:")
        for task, chain in _HIGH_IMPACT_ROUTING.items():
            print(f"  {task:30} {' → '.join(chain)}")
    else:
        print("Usage:")
        print("  python3 scripts/llm_router.py --test        # Test all providers")
        print("  python3 scripts/llm_router.py --test-grok   # Test Grok specifically")
        print("  python3 scripts/llm_router.py --routing     # Show current routing table")
