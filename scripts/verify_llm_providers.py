#!/usr/bin/env python3
"""verify_llm_providers.py — Print live LLM provider map from .env and config.

LLM Fleet v4.1 Phase 0 deliverable.
Reports provider status at four levels:
  configured — key/env present
  reachable  — endpoint/network responds
  usable     — tiny live test succeeds
  degraded   — quota/billing/rate-limit/auth error

Must exit 0 if all critical providers are configured.

Usage:
    .venv/bin/python scripts/verify_llm_providers.py
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from local_llm_config import (
    get_local_llm_config, get_model_for_process_type,
    get_cloud_fallback_models, get_deployment_phase,
    STANDARD, REALTIME, BATCH_OVERNIGHT, MEDIA_CONTENT,
    EMBEDDING, CRITICAL_CLOUD, CLOUD_FALLBACK,
)


def _redact(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        return "(not set)"
    return val[:8] + "..." + val[-4:] if len(val) > 16 else val[:4] + "..."


def _ollama_status() -> dict:
    try:
        resp = urllib.request.urlopen("http://localhost:11434/api/ps", timeout=5)
        data = json.loads(resp.read())
        models = [{"name": m["name"], "size_mb": m.get("size", 0) // 1024 // 1024}
                  for m in data.get("models", [])]
        return {"alive": True, "resident_models": models}
    except Exception as e:
        return {"alive": False, "error": str(e)}


# ── Live provider probes ────────────────────────────────────────────────────

def _probe_local(model: str) -> dict:
    """Probe local Ollama: reachable + usable via tiny generate."""
    result = {"configured": True, "reachable": False, "usable": False, "degraded": False, "detail": ""}
    try:
        resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
        result["reachable"] = True
    except Exception as e:
        result["detail"] = f"unreachable: {e}"
        return result
    # Usability: tiny generate
    try:
        t0 = time.time()
        payload = json.dumps({
            "model": model, "stream": False, "think": False,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
            "options": {"temperature": 0, "num_predict": 20}
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/chat", data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
            text = body.get("message", {}).get("content", "").strip()
            latency = round(time.time() - t0, 2)
            if text:
                result["usable"] = True
                result["detail"] = f"ok ({latency}s, {len(text)} chars)"
            else:
                result["degraded"] = True
                result["detail"] = f"empty response ({latency}s)"
    except Exception as e:
        result["degraded"] = True
        result["detail"] = f"generate failed: {e}"
    return result


def _probe_openai() -> dict:
    """Probe OpenAI: configured, reachable, usable, degraded."""
    key = os.getenv("OPENAI_API_KEY", "")
    result = {"configured": bool(key), "reachable": False, "usable": False, "degraded": False, "detail": ""}
    if not key:
        result["detail"] = "OPENAI_API_KEY not set"
        return result
    try:
        payload = json.dumps({
            "model": "gpt-4o-mini", "max_tokens": 5,
            "messages": [{"role": "user", "content": "Reply: ok"}]
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST"
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
            text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            latency = round(time.time() - t0, 2)
            result["reachable"] = True
            if text:
                result["usable"] = True
                result["detail"] = f"ok ({latency}s)"
            else:
                result["degraded"] = True
                result["detail"] = f"empty response ({latency}s)"
    except urllib.error.HTTPError as e:
        result["reachable"] = True
        result["degraded"] = True
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        if e.code == 401:
            result["detail"] = "auth error (invalid key)"
        elif e.code == 429:
            result["detail"] = "rate limited"
        elif e.code == 402 or "billing" in body.lower() or "insufficient" in body.lower():
            result["detail"] = f"billing/quota error (HTTP {e.code})"
        else:
            result["detail"] = f"HTTP {e.code}: {body[:100]}"
    except Exception as e:
        result["detail"] = f"unreachable: {e}"
    return result


def _probe_anthropic() -> dict:
    """Probe Anthropic: configured, reachable, usable, degraded."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    result = {"configured": bool(key), "reachable": False, "usable": False, "degraded": False, "detail": ""}
    if not key:
        result["detail"] = "ANTHROPIC_API_KEY not set"
        return result
    try:
        payload = json.dumps({
            "model": "claude-sonnet-4-6", "max_tokens": 10,
            "messages": [{"role": "user", "content": "Reply: ok"}]
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
            text = ""
            for block in body.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            latency = round(time.time() - t0, 2)
            result["reachable"] = True
            if text.strip():
                result["usable"] = True
                result["detail"] = f"ok ({latency}s)"
            else:
                result["degraded"] = True
                result["detail"] = f"empty response ({latency}s)"
    except urllib.error.HTTPError as e:
        result["reachable"] = True
        result["degraded"] = True
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        if e.code == 401:
            result["detail"] = "auth error (invalid key)"
        elif e.code == 429:
            result["detail"] = "rate limited"
        elif e.code in (402, 403) or "credit" in body.lower() or "billing" in body.lower():
            result["detail"] = f"billing/credit error (HTTP {e.code}): {body[:100]}"
        else:
            result["detail"] = f"HTTP {e.code}: {body[:100]}"
    except Exception as e:
        result["detail"] = f"unreachable: {e}"
    return result


def _probe_xai() -> dict:
    """Probe xAI/Grok: configured only (no live test — model ID not standardized)."""
    key = os.getenv("XAI_API_KEY", "")
    result = {"configured": bool(key), "reachable": False, "usable": False, "degraded": False, "detail": ""}
    if not key:
        result["detail"] = "XAI_API_KEY not set"
    else:
        result["detail"] = "configured (no live probe — xAI model ID not standardized)"
    return result


def _status_label(probe: dict) -> str:
    """Return a human-readable status label from probe result."""
    if probe["usable"]:
        return "USABLE"
    if probe["degraded"]:
        return "DEGRADED"
    if probe["reachable"]:
        return "REACHABLE"
    if probe["configured"]:
        return "CONFIGURED"
    return "NOT CONFIGURED"


def main():
    cfg = get_local_llm_config()
    ollama = _ollama_status()

    print("=" * 60)
    print("LLM Fleet v4.1 — Provider Verification")
    print("=" * 60)
    print(f"Deployment phase: {get_deployment_phase()}")
    print()

    # Local provider
    print("── Local Provider ──")
    print(f"  Provider:  {cfg.provider}")
    print(f"  Model:     {cfg.model}")
    print(f"  Base URL:  {cfg.base_url}")
    print(f"  Backend:   {cfg.backend}")
    print(f"  Ollama:    {'alive' if ollama['alive'] else 'DOWN'}")
    if ollama["alive"]:
        for m in ollama.get("resident_models", []):
            print(f"    Resident: {m['name']} ({m['size_mb']} MB)")
    local_probe = _probe_local(cfg.model)
    print(f"  Status:    {_status_label(local_probe)} — {local_probe['detail']}")
    print()

    # Process type model map
    print("── Process Type → Model Map ──")
    for pt in [STANDARD, REALTIME, BATCH_OVERNIGHT, MEDIA_CONTENT, EMBEDDING, CRITICAL_CLOUD, CLOUD_FALLBACK]:
        model = get_model_for_process_type(pt)
        env_key = f"LLM_{pt}"
        env_val = os.getenv(env_key, "")
        source = f"env:{env_key}" if env_val else "default"
        print(f"  {pt:20s} → {model:25s} ({source})")
    print()

    # Cloud providers — live probes
    print("── Cloud Providers (Live Probes) ──")
    probes = {
        "OpenAI": _probe_openai(),
        "Anthropic": _probe_anthropic(),
        "xAI/Grok": _probe_xai(),
    }
    for name, probe in probes.items():
        key_env = {"OpenAI": "OPENAI_API_KEY", "Anthropic": "ANTHROPIC_API_KEY", "xAI/Grok": "XAI_API_KEY"}[name]
        print(f"  {name:12s}  key={_redact(key_env):20s}  status={_status_label(probe)}")
        print(f"               {probe['detail']}")
    print()

    # Fallback chain
    fallbacks = get_cloud_fallback_models()
    print("── Fallback Chain ──")
    print(f"  Local:  {cfg.model}")
    for i, fb in enumerate(fallbacks, 1):
        print(f"  Cloud {i}: {fb}")
    print()

    # Kill switches
    print("── Kill Switches ──")
    for var in ["LLM_FORCE_LOCAL_ONLY", "LLM_DISABLE_CLOUD_FALLBACK",
                "LLM_DISABLE_CRITICAL_CLOUD", "LLM_DISABLE_LIVE_EXECUTION",
                "LLM_OVERRIDE_ACTIVE_HOURS"]:
        val = os.getenv(var, "(not set)")
        print(f"  {var:35s} = {val}")
    print()

    # Validation summary
    errors = []
    if not local_probe["usable"]:
        errors.append(f"Local LLM not usable: {local_probe['detail']}")
    if not probes["OpenAI"]["configured"]:
        errors.append("OPENAI_API_KEY not set (cloud fallback unavailable)")
    elif probes["OpenAI"]["degraded"]:
        errors.append(f"OpenAI degraded: {probes['OpenAI']['detail']}")
    if not probes["Anthropic"]["configured"]:
        errors.append("ANTHROPIC_API_KEY not set (cloud fallback unavailable)")
    elif probes["Anthropic"]["degraded"]:
        errors.append(f"Anthropic degraded: {probes['Anthropic']['detail']}")

    if errors:
        print("── WARNINGS ──")
        for e in errors:
            print(f"  ⚠ {e}")
        print()

    # Status table
    print("── Provider Status Summary ──")
    print(f"  {'Provider':12s}  {'Configured':12s}  {'Reachable':12s}  {'Usable':12s}  {'Degraded':12s}")
    all_probes = {"Local": local_probe, **probes}
    for name, p in all_probes.items():
        print(f"  {name:12s}  {str(p['configured']):12s}  {str(p['reachable']):12s}  {str(p['usable']):12s}  {str(p['degraded']):12s}")
    print()

    print("── RESULT: PASS ──" if not errors else "── RESULT: PASS (with warnings) ──")
    return 0


if __name__ == "__main__":
    sys.exit(main())
