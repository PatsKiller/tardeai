#!/usr/bin/env python3
"""llm_router.py — Smart LLM routing with fallback hierarchy.

Routes requests: local Ollama first → Grok → Claude → OpenAI.
Task-aware: high-impact synthesis goes to Claude, routine goes local.
Logs everything for cost/quality tracking.

Fallback thresholds:
- Local timeout: 8 seconds → fallback
- Confidence < 0.65 → fallback
- Empty/malformed response → immediate fallback
- High-impact tasks → prefer Claude directly

Provider performance:
| Provider      | Speed     | Cost/1K  | Best For                     | When to Prefer          |
|---------------|-----------|----------|------------------------------|-------------------------|
| Local Ollama  | Fast      | Free     | Routine agent tasks          | Always try first        |
| Grok (xAI)   | Very fast | ~$0.20   | Agent narratives, reasoning  | Most fallback tasks     |
| Claude Sonnet | Medium    | ~$1.00   | Deep synthesis, complex      | CIO synthesis, critical |
| GPT-4o        | Fast      | ~$0.50   | Versatile fallback           | Last resort             |

Usage:
    from llm_router import get_llm_response
    result = get_llm_response("agent_narrative", prompt, high_impact=False)
"""
import json, os, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Configuration ──────────────────────────────────────────────

LOCAL_TIMEOUT = 30      # seconds — qwen3 thinking mode needs 15-20s
CONFIDENCE_THRESHOLD = 0.65
LOCAL_MODEL = "qwen3:1.7b"
LOCAL_URL = "http://127.0.0.1:11434/api/generate"
DAILY_BUDGET_LIMIT = 2.00  # USD per day for external API calls

# Task → provider preference
_TASK_ROUTING = {
    "agent_narrative":          ["local", "grok", "claude"],
    "cio_synthesis":            ["local", "claude", "grok", "openai"],
    "catalyst_classification":  ["local", "grok"],
    "sentiment":                ["local", "grok"],
    "code_generation":          ["claude", "openai"],
    "fast_summary":             ["local"],
    "default":                  ["local", "grok", "claude", "openai"],
}

# High-impact tasks skip local for critical providers
_HIGH_IMPACT_ROUTING = {
    "cio_synthesis":   ["claude", "grok", "openai"],
    "agent_narrative": ["grok", "claude", "local"],
    "default":         ["claude", "grok", "local", "openai"],
}


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
            "prompt": prompt,
            "options": {"temperature": 0.3, "num_predict": max(500, max_tokens)}
        }).encode()
        req = urllib.request.Request(LOCAL_URL, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=max(30, _timeout + 20)) as resp:
            result = json.loads(resp.read())
            text = result.get("response", "").strip()
            latency = round(time.time() - t0, 2)
            return {
                "model_used": LOCAL_MODEL, "provider": "local",
                "response": text, "latency": latency,
                "success": bool(text and len(text) > 20),
                "cost_estimate": 0.0,
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
            "model": "grok-beta",
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
                "model_used": "grok-beta", "provider": "grok",
                "response": text.strip(), "latency": latency,
                "success": bool(text.strip()),
                "cost_estimate": round(0.0002 * max_tokens, 4),
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


def get_llm_response(
    task_type: str,
    prompt: str,
    context: dict = None,
    high_impact: bool = False,
    max_tokens: int = 800,
    local_timeout: int = None,
) -> dict:
    """Route LLM request through provider hierarchy. Returns best response.

    Args:
        task_type: agent_narrative, cio_synthesis, catalyst_classification, sentiment, etc.
        prompt: The full prompt text
        high_impact: If True, prefer Claude/Grok over local
        max_tokens: Max response tokens
        local_timeout: Override local timeout (default 8s for fallback trigger)

    Returns:
        dict with: model_used, provider, response, latency, cost_estimate, fallback_reason
    """
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

    # Local
    try:
        r = _call_local("Say 'ok' in one word.", max_tokens=10, timeout=5)
        results["local"] = {"available": r.get("success", False), "latency": r.get("latency"), "model": LOCAL_MODEL}
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

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── CLI for testing ──────────────────────────────────────────

if __name__ == "__main__":
    if "--test" in sys.argv:
        print("=== LLM Router Test ===")
        print()

        # Test 1: Local
        print("1. Testing local (agent_narrative)...")
        r = get_llm_response("agent_narrative", "Summarize SCHD as a dividend growth ETF in 2 sentences.", max_tokens=200)
        print(f"   Provider: {r['provider']} | Model: {r['model_used']} | Latency: {r['latency']}s | Cost: ${r.get('cost_estimate',0)}")
        print(f"   Response: {r['response'][:100]}...")
        print(f"   Fallbacks: {r.get('fallback_reasons', [])}")

        print()

        # Test 2: High-impact (should try Claude if available)
        print("2. Testing high-impact (cio_synthesis)...")
        r2 = get_llm_response("cio_synthesis", "Should we trim SCHD given RSI 63 and 11.79% portfolio weight? Respond in 2 sentences.", high_impact=True, max_tokens=200)
        print(f"   Provider: {r2['provider']} | Model: {r2['model_used']} | Latency: {r2['latency']}s | Cost: ${r2.get('cost_estimate',0)}")
        print(f"   Response: {r2['response'][:100]}...")
        print(f"   Fallbacks: {r2.get('fallback_reasons', [])}")

        print()
        print("=== Provider Availability ===")
        keys = _load_env()
        for name, key_name in [("Local Ollama", None), ("Grok (xAI)", "XAI_API_KEY"), ("Claude", "ANTHROPIC_API_KEY"), ("OpenAI", "OPENAI_API_KEY")]:
            if key_name is None:
                print(f"  {name}: AVAILABLE (localhost)")
            elif keys.get(key_name):
                print(f"  {name}: CONFIGURED")
            else:
                print(f"  {name}: NOT CONFIGURED")
    else:
        print("Usage: python3 scripts/llm_router.py --test")
