#!/usr/bin/env python3
"""llm_router.py — Smart LLM routing with fallback hierarchy.

Routes requests through provider chain. Task-aware routing.
Logs everything for cost/quality tracking.

═══ PROVIDER CHAIN (May 2026 — GPU testing phase) ═══════════════════════════

  LOCAL qwen3:1.7b  →  GROK (xAI)  →  CLAUDE (Anthropic)  →  OPENAI

Provider   Speed      Cost/1K   Quality    Best For
─────────  ─────────  ────────  ─────────  ────────────────────────────────
Local      Fast       Free      Medium     Routine batch, overnight, tagging
Grok       Very fast  ~$0.01    Good       Agent analyses, debates, sector alerts
                                           *** PRIMARY TESTING PROVIDER ***
Claude     Medium     ~$1.00    Best       Retirement, disability, Roth, CIO synthesis
OpenAI     Fast       ~$0.50    Good       Last resort only

═══ GPU UPGRADE FAILBACK PLAN ════════════════════════════════════════════════

When qwen3:14b is installed on GPU:
  1. Set LOCAL_MODEL = "qwen3:14b" in this file OR set in .env:
       echo "LOCAL_MODEL=qwen3:14b" >> .env
  2. Grok auto-demotes from primary testing → fallback (code below handles this)
  3. Local handles: agent_narrative, agent_debate, sector_correlation, sentiment
  4. Claude remains for: cio_synthesis, retirement, disability (always best)
  5. Verify: python3 scripts/llm_router.py --test

  REVERT if GPU fails: set LOCAL_MODEL=qwen3:1.7b — Grok auto-promotes back.
  No other changes needed. Single-line failback.

═══ TASK ROUTING ════════════════════════════════════════════════════════════

  Pre-GPU (qwen3:1.7b):          local → grok → claude
  Post-GPU (qwen3:14b):          local → claude → grok
  Retirement/disability:         claude → grok → local (always Claude-first)
  Sector correlation/debate:     grok → local → claude (Grok fast + good reasoning)

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

# Pre-GPU routing: Grok is primary cloud (local quality limited)
_TASK_ROUTING_PRE_GPU = {
    "agent_narrative":          ["local", "grok", "claude"],
    "agent_debate":             ["local", "grok", "claude"],
    "sector_correlation":       ["grok", "local", "claude"],
    "cio_synthesis":            ["local", "claude", "grok", "openai"],
    "catalyst_classification":  ["local", "grok"],
    "sentiment":                ["local", "grok"],
    "code_generation":          ["claude", "openai"],
    "fast_summary":             ["local"],
    "default":                  ["local", "grok", "claude", "openai"],
}

# Post-GPU routing: local is high quality, Grok demoted to fallback
_TASK_ROUTING_POST_GPU = {
    "agent_narrative":          ["local", "claude", "grok"],
    "agent_debate":             ["local", "claude", "grok"],
    "sector_correlation":       ["local", "grok", "claude"],
    "cio_synthesis":            ["local", "claude", "grok", "openai"],
    "catalyst_classification":  ["local", "grok"],
    "sentiment":                ["local"],
    "code_generation":          ["claude", "openai"],
    "fast_summary":             ["local"],
    "default":                  ["local", "claude", "grok", "openai"],
}

# High-impact always prefers Claude, regardless of GPU state
_HIGH_IMPACT_ROUTING = {
    "cio_synthesis":        ["claude", "grok", "openai"],
    "agent_narrative":      ["grok", "claude", "local"],
    "agent_debate":         ["grok", "claude", "local"],
    "sector_correlation":   ["grok", "claude", "local"],
    "default":              ["claude", "grok", "local", "openai"],
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
        payload = json.dumps({
            "model": LOCAL_MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.3, "num_predict": max(500, max_tokens)}
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
    """Call Anthropic Claude API."""
    keys = _load_env()
    api_key = keys.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY not configured", "provider": "claude"}

    t0 = time.time()
    try:
        payload = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            latency = round(time.time() - t0, 2)
            tokens = result.get("usage", {})
            cost = (tokens.get("input_tokens", 0) * 3 + tokens.get("output_tokens", 0) * 15) / 1_000_000
            return {
                "model_used": "claude-sonnet-4-20250514", "provider": "claude",
                "response": text.strip(), "latency": latency,
                "success": bool(text.strip()),
                "cost_estimate": round(cost, 4),
                "tokens": tokens,
            }
    except Exception as e:
        return {"success": False, "error": str(e), "provider": "claude",
                "latency": round(time.time() - t0, 2), "cost_estimate": 0.0}


def _call_openai(prompt: str, max_tokens: int = 2000) -> dict:
    """Call OpenAI GPT-4o API."""
    keys = _load_env()
    api_key = keys.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "OPENAI_API_KEY not configured", "provider": "openai"}

    t0 = time.time()
    try:
        payload = json.dumps({
            "model": "gpt-4o",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            latency = round(time.time() - t0, 2)
            tokens = result.get("usage", {})
            cost = (tokens.get("prompt_tokens", 0) * 2.5 + tokens.get("completion_tokens", 0) * 10) / 1_000_000
            return {
                "model_used": "gpt-4o", "provider": "openai",
                "response": text.strip(), "latency": latency,
                "success": bool(text.strip()),
                "cost_estimate": round(cost, 4),
                "tokens": tokens,
            }
    except Exception as e:
        return {"success": False, "error": str(e), "provider": "openai",
                "latency": round(time.time() - t0, 2), "cost_estimate": 0.0}


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
    "grok": _call_grok,
    "claude": _call_anthropic,
    "openai": _call_openai,
}

# Providers that cost no money. `local` is the only zero-cost provider in this router
# (grok/claude/openai all bill a metered API key). When free_only=True is requested, every
# other provider is filtered out of the chain BEFORE any call is made, so an automated caller
# can never silently fall back onto a paid lane. This is the structural backstop behind the
# Hermes research budget guard: even if a producer's task_type maps to a paid-capable chain,
# free_only forces the chain down to the no-cost set and returns failure rather than spending.
_FREE_PROVIDERS = {"local"}


def get_llm_response(
    task_type: str,
    prompt: str,
    context: dict = None,
    high_impact: bool = False,
    max_tokens: int = 800,
    local_timeout: int = None,
    free_only: bool = False,
) -> dict:
    """Route LLM request through provider hierarchy. Returns best response.

    Args:
        task_type: agent_narrative, cio_synthesis, catalyst_classification, sentiment, etc.
        prompt: The full prompt text
        high_impact: If True, prefer Claude/Grok over local
        max_tokens: Max response tokens
        local_timeout: Override local timeout (default 8s for fallback trigger)
        free_only: If True, restrict the provider chain to zero-cost lanes (_FREE_PROVIDERS).
                   No paid provider is ever called, even as a fallback. Automated research
                   producers MUST pass free_only=True — paid lanes are reserved for explicit,
                   operator-authorized oversight paths, never for automated fallback.

    Returns:
        dict with: model_used, provider, response, latency, cost_estimate, fallback_reason
    """
    # Determine provider order
    if high_impact:
        providers = _HIGH_IMPACT_ROUTING.get(task_type, _HIGH_IMPACT_ROUTING["default"])
    else:
        providers = _TASK_ROUTING.get(task_type, _TASK_ROUTING["default"])

    if free_only:
        # Strip every paid provider out of the chain up front. If nothing free remains, the
        # request fails closed (no paid spend) rather than escalating to a billed lane.
        providers = [p for p in providers if p in _FREE_PROVIDERS] or ["local"]

    fallback_reasons = []
    total_cost = 0.0

    for provider_name in providers:
        caller = _PROVIDERS.get(provider_name)
        if not caller:
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
