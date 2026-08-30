#!/usr/bin/env python3
"""Governed cloud LLM routing for Trade AI production.

The production graph contains no local generative provider or fallback. Local
Ollama is outside this router and may serve only the separately enforced pinned
nomic embedding contract. Math remains deterministic Python.

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

CONFIDENCE_THRESHOLD = 0.65
DAILY_BUDGET_LIMIT = 1.50  # USD/day — allows cloud fallback when Ollama offline (typical spend ~$0.02/day)

# ── Task routing ─────────────────────────────────────────────────────────

# Governed DeepSeek Flash only for agent watchlist workloads (issue #283 / PR #284).
# No silent local/Grok/Claude/OpenAI fallback on paid agent tasks.
# Live chains below never include "local". filter_local_providers is a guardrail
# if a future table edit tries to add a local generative provider.
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

_TASK_ROUTING = _TASK_ROUTING_POST_GPU


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
    """Grok via the GOVERNED lane. Was a direct api.x.ai POST.

    This read XAI_API_KEY and urlopen'd api.x.ai/v1/chat/completions with NO
    reservation, NO ledger row and NO cap, while being reachable from scheduled
    jobs (iterate_research_topics, agent_watchlist_engine, overnight_batch,
    api_v2). Its `cost_estimate` was arithmetic on max_tokens — a guess
    recorded as a fact. Audited 2026-08-30.

    llm_lane carries a governed `grok` lane through the xAI proxy
    (HERMES_XAI_PROXY_URL, default 127.0.0.1:8645). Cost now comes from the
    consumption ledger instead of from a token ceiling.
    """
    t0 = time.time()
    try:
        try:
            from llm_lane import generate
        except Exception:                                        # noqa: BLE001
            from scripts.llm_lane import generate                # type: ignore
        text = generate(
            prompt,
            lane="grok",
            max_tokens=max_tokens,
            process_id=getattr(_call_grok, "_process_id", "llm_router"),
            task_summary="llm_router:grok",
        ) or ""
        return {
            "model_used": "grok-3-mini", "provider": "grok",
            "response": str(text).strip(),
            "latency": round(time.time() - t0, 2),
            "success": bool(str(text).strip()),
            "cost_estimate": None,      # settled by the ledger, not guessed
            "governed": True,
        }
    except Exception as e:                                       # noqa: BLE001
        return {"success": False, "error": str(e), "provider": "grok",
                "latency": round(time.time() - t0, 2),
                "cost_estimate": None, "governed": True}


_PROVIDERS = {
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
        providers = list(_HIGH_IMPACT_ROUTING.get(task_type, _HIGH_IMPACT_ROUTING["default"]))
    else:
        providers = list(_TASK_ROUTING.get(task_type, _TASK_ROUTING["default"]))

    fallback_reasons = []
    total_cost = 0.0

    # Defense in depth: strip any future local-provider table edit.
    try:
        from lib.llm_task_policy import filter_local_providers
        providers, local_skip = filter_local_providers(task_type or "default", providers)
        if local_skip:
            fallback_reasons.append(local_skip)
    except Exception:
        # Fail closed if policy import fails.
        if "local" in providers:
            fallback_reasons.append(
                "local: POLICY_LOCAL_JUDGMENT_FORBIDDEN (policy module unavailable)"
            )
            providers = [p for p in providers if p != "local"]

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

    results["local_generative"] = {
        "available": False,
        "policy": "FORBIDDEN",
        "gpu_mode": "EMBEDDINGS_ONLY_OR_DISABLED",
    }

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
    if "--test" in sys.argv or "--test-grok" in sys.argv:
        print("=== LLM Router Test ===")
        print("LOCAL_GENERATIVE: FORBIDDEN")
        print(f"DAILY_BUDGET_LIMIT: ${DAILY_BUDGET_LIMIT:.2f}")
        print()

        print("1. Testing governed cloud (agent_narrative)...")
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
        for name, key_name in [("Grok (xAI)", "XAI_API_KEY"),
                                ("Claude", "ANTHROPIC_API_KEY"), ("OpenAI", "OPENAI_API_KEY")]:
            if keys.get(key_name):
                print(f"  {name}: CONFIGURED ✓")
            else:
                print(f"  {name}: NOT CONFIGURED")

        print()
        print("=== GPU Policy ===")
        print("  Local generative: FORBIDDEN")
        print("  Candidate local workload: pinned nomic embeddings only")

    elif "--routing" in sys.argv:
        print("=== Current Task Routing ===")
        print("Mode: CLOUD_GENERATIVE_ONLY")
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
